from __future__ import annotations

import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field

from call4me.audio import PulseAudioManager, PulseAudioPlayback
from call4me.browser import GoogleVoiceController
from call4me.cli import InteractiveCLI
from call4me.config import Call4MeConfig
from call4me.llm import Chat2APIClient
from call4me.memory import CallMemoryService, PostCallExtractor
from call4me.planner import CallScript, SpeculativeCache
from call4me.prompts import TaskPrompt, build_system_prompt
from call4me.stt import TranscriptEvent, WhisperStreamingTranscriber
from call4me.tts import PiperTTS


@dataclass(slots=True)
class CallRequest:
    phone_number: str
    task_prompt: TaskPrompt
    user_info: dict[str, str] = field(default_factory=dict)
    company: str = ""
    call_script: CallScript | None = None
    cli: InteractiveCLI | None = None
    interactive: bool = False
    max_duration_sec: int | None = None


@dataclass(slots=True)
class CallResult:
    completed: bool
    summary: str
    company: str
    duration_sec: int
    ivr_steps: list[str]
    transcripts: list[TranscriptEvent]


class Call4MeAgent:
    def __init__(self, config: Call4MeConfig):
        self.config = config
        self.logger = logging.getLogger("call4me")
        self.pulse = PulseAudioManager(config.audio)
        self.playback = PulseAudioPlayback(config.audio)
        self.tts = PiperTTS(config.tts, self.playback)
        self.llm = Chat2APIClient(config.llm)  # fast model for real-time calls
        # Smarter model for pre-call planning (falls back to llm if not configured)
        self.planner_llm = Chat2APIClient(config.planner_llm) if config.planner_llm else self.llm
        self.browser = GoogleVoiceController(config.browser)
        self.stt = WhisperStreamingTranscriber(config.audio, config.stt)
        self.memory = CallMemoryService(
            db_path=config.memory.db_path,
            embed_model=config.memory.embed_model,
        )
        self.extractor = PostCallExtractor(self.llm, self.memory, self.logger)

    def run(self, request: CallRequest) -> CallResult:
        transcripts: list[TranscriptEvent] = []
        history: list[dict[str, str]] = []
        ivr_steps: list[str] = []
        transcript_queue: "queue.Queue[TranscriptEvent]" = queue.Queue()
        stop_event = threading.Event()
        company = self._resolve_company(request)
        completed = False
        summary = ""
        hold_active = False
        pending_override: str | None = None
        runtime_guidance: list[str] = []
        last_activity = time.monotonic()
        last_hold_log = time.monotonic()
        max_duration = request.max_duration_sec or self.config.agent.max_duration_sec
        start_time = time.monotonic()
        deadline = start_time + max_duration
        speculative_cache: SpeculativeCache | None = None

        memory_context = self.memory.get_context_for_call(company, request.task_prompt.task)
        system_prompt = build_system_prompt(
            request.task_prompt,
            request.user_info,
            memory_context=memory_context,
        )
        system_prompt = self._augment_for_script(system_prompt, request.call_script)

        self.stt.warmup()
        cached_responses: dict[str, str] = {}
        first_turn = False
        if request.call_script is not None:
            speculative_cache = SpeculativeCache(self.llm, self.tts, request.call_script)
            cached_count = speculative_cache.precache_script(request.call_script)
            self.logger.info("Pre-cached %d script responses", cached_count)
            if request.cli:
                request.cli.show_info(f"Pre-cached {cached_count} planned responses.")
        else:
            # Non-interactive mode: pre-cache greeting responses for first turn
            cached_responses = self._precache_responses(request)
            first_turn = True

        self.pulse.ensure_devices()

        thread = threading.Thread(
            target=self.stt.run_loop,
            args=(stop_event, transcript_queue),
            daemon=True,
        )
        thread.start()

        self.browser.connect()
        if not self.browser.dial(request.phone_number):
            stop_event.set()
            thread.join(timeout=5)
            self.browser.close()
            raise RuntimeError("Failed to dial number in Google Voice")

        time.sleep(3.0)
        moved = self.pulse.move_sink_inputs()
        self.logger.info("Moved %s browser sink inputs to %s", moved, self.config.audio.capture_sink)
        if request.cli and request.interactive:
            request.cli.start_input_listener()

        while not transcript_queue.empty():
            try:
                transcript_queue.get_nowait()
            except queue.Empty:
                break
        self.logger.info("Drained pre-call transcripts, STT model is hot")

        # In interactive mode, suppress all INFO logs once the actual call starts.
        # Pre-call logs (warmup, pre-cache, audio setup) are still visible above.
        if request.interactive:
            logging.getLogger("call4me").setLevel(logging.WARNING)

        try:
            while time.monotonic() < deadline:
                pending_override, stop_requested = self._drain_user_commands(
                    request=request,
                    runtime_guidance=runtime_guidance,
                    pending_override=pending_override,
                )
                if stop_requested:
                    self.browser.hangup()
                    summary = "Call stopped by user."
                    break

                try:
                    event = transcript_queue.get(timeout=1.0)
                except queue.Empty:
                    if hold_active and (time.monotonic() - last_hold_log) >= self.config.agent.on_hold_message_interval_sec:
                        self.logger.info("Still on hold...")
                        last_hold_log = time.monotonic()
                    if not self.browser.is_call_active() and transcripts:
                        summary = "Call ended before the assistant marked the goal as completed."
                        break
                    if (time.monotonic() - last_activity) >= self.config.agent.idle_timeout_sec and transcripts:
                        self.logger.info("No new transcripts for %ss", self.config.agent.idle_timeout_sec)
                        last_activity = time.monotonic()
                    continue

                transcripts.append(event)
                last_activity = time.monotonic()
                if request.cli:
                    request.cli.show_them(event.text, event.timestamp)
                self.logger.info(
                    "[%s] %.1fs audio / %.1fs STT | %s",
                    event.timestamp,
                    event.audio_duration,
                    event.stt_duration,
                    event.text,
                )

                hold_active = self._looks_like_hold_prompt(event.text)
                history.append({"role": "user", "content": event.text})
                history = history[-self.config.agent.transcript_history_limit :]

                if first_turn and cached_responses:
                    first_turn = False
                    greeting_text, greeting_wav = self._pick_cached_response(event.text, cached_responses)
                    if greeting_wav:
                        self.logger.info("Playing cached greeting: %s", greeting_text)
                        self.playback.play_file(greeting_wav)
                        history.append({"role": "assistant", "content": greeting_text})
                        history = history[-self.config.agent.transcript_history_limit :]
                        continue

                if pending_override:
                    override = pending_override
                    pending_override = None
                    if request.cli:
                        request.cli.show_us(override, source="user")
                    self.tts.speak(override)
                    history.append({"role": "assistant", "content": override})
                    history = history[-self.config.agent.transcript_history_limit :]
                    if speculative_cache and not self._looks_like_ivr_prompt(event.text):
                        speculative_cache.speculate_async(history, event.text)
                    continue

                if speculative_cache and not self._looks_like_ivr_prompt(event.text):
                    cached = speculative_cache.match(event.text)
                    if cached is not None:
                        cached_text, cached_wav = cached
                        if request.cli:
                            request.cli.show_cache_hit(cached_text)
                        self.playback.play_file(cached_wav)
                        history.append({"role": "assistant", "content": cached_text})
                        history = history[-self.config.agent.transcript_history_limit :]
                        speculative_cache.speculate_async(history, event.text)
                        continue

                active_system_prompt = self._apply_runtime_guidance(system_prompt, runtime_guidance)
                action = self.llm.next_action(active_system_prompt, history)
                self.logger.info("Assistant action: %s", action.raw)
                history.append({"role": "assistant", "content": action.raw})
                history = history[-self.config.agent.transcript_history_limit :]

                if action.kind == "dtmf":
                    self.browser.press_key(action.digit)
                    ivr_steps.append(action.digit)
                    if request.cli:
                        request.cli.show_action(f"DTMF {action.digit}")
                    continue
                if action.kind == "hold_wait":
                    hold_active = True
                    if request.cli:
                        request.cli.show_action("HOLD_WAIT")
                    continue
                if action.kind == "call_done":
                    completed = True
                    summary = action.summary or "Call completed."
                    if self.config.agent.auto_hangup_on_complete:
                        self.browser.hangup()
                    break
                if action.kind == "speak":
                    hold_active = False
                    if request.cli:
                        request.cli.show_us(action.text, source="bot")
                    self.tts.speak(action.text)

                    # If the LLM combined speech with CALL_DONE, finish after speaking
                    if action.pending_done:
                        completed = True
                        summary = action.pending_done
                        if self.config.agent.auto_hangup_on_complete:
                            self.browser.hangup()
                        break

                    if speculative_cache and not self._looks_like_ivr_prompt(event.text):
                        speculative_cache.speculate_async(history, event.text)

            if not summary:
                summary = "Call finished without a final summary."
        finally:
            # Restore INFO logging for post-call processing
            if request.interactive:
                logging.getLogger("call4me").setLevel(logging.INFO)
            stop_event.set()
            thread.join(timeout=5)
            if speculative_cache is not None:
                speculative_cache.stop()
            if request.cli and request.interactive:
                request.cli.stop_input_listener()
            self.browser.close()

        return CallResult(
            completed=completed,
            summary=summary,
            company=company,
            duration_sec=int(time.monotonic() - start_time),
            ivr_steps=ivr_steps,
            transcripts=transcripts,
        )

    def learn_from_result(self, request: CallRequest, result: CallResult) -> None:
        self.extractor.extract_and_save(
            company=result.company,
            phone=request.phone_number,
            task=request.task_prompt.task,
            transcripts=result.transcripts,
            result=result,
            ivr_steps=result.ivr_steps,
        )

    @staticmethod
    def _looks_like_hold_prompt(text: str) -> bool:
        normalized = text.casefold()
        hold_markers = (
            "please hold",
            "continue to hold",
            "your call is important",
            "next available agent",
            "representative will be with you",
        )
        return any(marker in normalized for marker in hold_markers)

    @staticmethod
    def _looks_like_ivr_prompt(text: str) -> bool:
        normalized = text.casefold()
        ivr_markers = (
            "press ",
            "for english",
            "main menu",
            "say or press",
            "select from the following",
            "menu options",
            "operator",
        )
        return any(marker in normalized for marker in ivr_markers)

    def _resolve_company(self, request: CallRequest) -> str:
        explicit = request.company.strip() or request.user_info.get("company", "").strip()
        if explicit:
            return explicit

        digits = re.sub(r"\D", "", request.phone_number)
        if digits:
            return f"number_{digits}"
        return "unknown_company"

    def _drain_user_commands(
        self,
        request: CallRequest,
        runtime_guidance: list[str],
        pending_override: str | None,
    ) -> tuple[str | None, bool]:
        cli = request.cli
        if not cli or not request.interactive:
            return pending_override, False

        while True:
            command = cli.poll_user_command()
            if command is None:
                break
            if command.kind == "say" and command.text:
                pending_override = command.text
                cli.show_info("Queued manual reply for the next turn.")
            elif command.kind == "inject" and command.text:
                runtime_guidance.append(command.text)
                cli.show_info(f"Injected guidance: {command.text}")
            elif command.kind == "script" and request.call_script is not None:
                cli.show_script(request.call_script.to_display())
            elif command.kind == "stop":
                cli.show_info("Stopping the call on user request.")
                return pending_override, True
        return pending_override, False

    @staticmethod
    def _apply_runtime_guidance(system_prompt: str, runtime_guidance: list[str]) -> str:
        if not runtime_guidance:
            return system_prompt
        guidance = "\n".join(f"- {item}" for item in runtime_guidance[-5:])
        return f"{system_prompt}\n\nLIVE USER GUIDANCE:\n{guidance}"

    @staticmethod
    def _augment_for_script(system_prompt: str, call_script: CallScript | None) -> str:
        if call_script is None:
            return system_prompt
        return (
            f"{system_prompt}\n\nPLANNED CALL STYLE:\n"
            f"- Option: {call_script.name or 'selected script'}\n"
            f"- Description: {call_script.description or call_script.plan.tone}\n"
            f"- Fallback: {call_script.fallback_strategy}"
        )

    def _precache_responses(self, request: CallRequest) -> dict[str, str]:
        """Pre-generate TTS for common first-turn responses before dialing."""
        name = request.user_info.get("name", "")
        if name:
            responses = [
                f"Hey, this is {name}. How's it going?",
                f"Hi there, this is {name} calling. How are you doing today?",
                f"Hi, {name} here. Hope I'm not catching you at a bad time.",
            ]
        else:
            responses = [
                "Hey, how's it going?",
                "Hi there, how are you doing today?",
                "Hello, hope I'm not catching you at a bad time.",
            ]
        cached: dict[str, str] = {}
        for text in responses:
            wav_path = self.tts.synthesize(text)
            cached[text] = wav_path
            self.logger.info("Cached: %s", text)
        return cached

    @staticmethod
    def _pick_cached_response(heard_text: str, cached: dict[str, str]) -> tuple[str, str | None]:
        if not cached:
            return "", None
        text = next(iter(cached))
        return text, cached[text]

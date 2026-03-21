from __future__ import annotations

import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field

from call4me.audio import PulseAudioManager, PulseAudioPlayback
from call4me.browser import GoogleVoiceController
from call4me.config import Call4MeConfig
from call4me.llm import Chat2APIClient
from call4me.memory import CallMemoryService, PostCallExtractor
from call4me.prompts import TaskPrompt, build_system_prompt
from call4me.stt import TranscriptEvent, WhisperStreamingTranscriber
from call4me.tts import PiperTTS


@dataclass(slots=True)
class CallRequest:
    phone_number: str
    task_prompt: TaskPrompt
    user_info: dict[str, str] = field(default_factory=dict)
    company: str = ""
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
        self.llm = Chat2APIClient(config.llm)
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
        completed = False
        summary = ""
        hold_active = False
        company = self._resolve_company(request)
        last_activity = time.monotonic()
        last_hold_log = time.monotonic()
        max_duration = request.max_duration_sec or self.config.agent.max_duration_sec
        start_time = time.monotonic()
        deadline = start_time + max_duration
        memory_context = self.memory.get_context_for_call(company, request.task_prompt.task)
        system_prompt = build_system_prompt(
            request.task_prompt,
            request.user_info,
            memory_context=memory_context,
        )

        self.pulse.ensure_devices()
        self.browser.connect()
        if not self.browser.dial(request.phone_number):
            self.browser.close()
            raise RuntimeError("Failed to dial number in Google Voice")

        time.sleep(3.0)
        moved = self.pulse.move_sink_inputs()
        self.logger.info("Moved %s browser sink inputs to %s", moved, self.config.audio.capture_sink)

        thread = threading.Thread(
            target=self.stt.run_loop,
            args=(stop_event, transcript_queue),
            daemon=True,
        )
        thread.start()

        try:
            while time.monotonic() < deadline:
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

                action = self.llm.next_action(system_prompt, history)
                self.logger.info("Assistant action: %s", action.raw)
                history.append({"role": "assistant", "content": action.raw})
                history = history[-self.config.agent.transcript_history_limit :]

                if action.kind == "dtmf":
                    self.browser.press_key(action.digit)
                    ivr_steps.append(action.digit)
                    continue
                if action.kind == "hold_wait":
                    hold_active = True
                    continue
                if action.kind == "call_done":
                    completed = True
                    summary = action.summary or "Call completed."
                    if self.config.agent.auto_hangup_on_complete:
                        self.browser.hangup()
                    break
                if action.kind == "speak":
                    hold_active = False
                    self.tts.speak(action.text)

            if not summary:
                summary = "Call finished without a final summary."
        finally:
            stop_event.set()
            thread.join(timeout=5)
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

    def _resolve_company(self, request: CallRequest) -> str:
        explicit = request.company.strip() or request.user_info.get("company", "").strip()
        if explicit:
            return explicit

        digits = re.sub(r"\D", "", request.phone_number)
        if digits:
            return f"number_{digits}"
        return "unknown_company"

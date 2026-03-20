from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

from call4me.audio import PulseAudioManager, PulseAudioPlayback
from call4me.browser import GoogleVoiceController
from call4me.config import Call4MeConfig
from call4me.llm import Chat2APIClient
from call4me.prompts import TaskPrompt, build_system_prompt
from call4me.stt import TranscriptEvent, WhisperStreamingTranscriber
from call4me.tts import PiperTTS


@dataclass(slots=True)
class CallRequest:
    phone_number: str
    task_prompt: TaskPrompt
    user_info: dict[str, str] = field(default_factory=dict)
    interactive: bool = False
    max_duration_sec: int | None = None


@dataclass(slots=True)
class CallResult:
    completed: bool
    summary: str
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

    def run(self, request: CallRequest) -> CallResult:
        transcripts: list[TranscriptEvent] = []
        history: list[dict[str, str]] = []
        transcript_queue: "queue.Queue[TranscriptEvent]" = queue.Queue()
        stop_event = threading.Event()
        completed = False
        summary = ""
        hold_active = False
        last_activity = time.monotonic()
        last_hold_log = time.monotonic()
        max_duration = request.max_duration_sec or self.config.agent.max_duration_sec
        deadline = time.monotonic() + max_duration
        system_prompt = build_system_prompt(request.task_prompt, request.user_info)

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

        return CallResult(completed=completed, summary=summary, transcripts=transcripts)

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

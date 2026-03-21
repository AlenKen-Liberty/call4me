from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from threading import Event

from call4me.audio.capture import PulseAudioCapture
from call4me.config import AudioConfig, STTConfig


@dataclass(slots=True)
class TranscriptEvent:
    text: str
    timestamp: str
    audio_duration: float
    stt_duration: float


class WhisperStreamingTranscriber:
    def __init__(self, audio_config: AudioConfig, stt_config: STTConfig):
        self.audio_config = audio_config
        self.stt_config = stt_config
        self._models = None

    def warmup(self) -> None:
        """Pre-load models and run multiple warmup transcriptions to fully heat CPU caches."""
        import logging
        logger = logging.getLogger("call4me")
        logger.info("Warming up STT models...")
        t0 = time.time()
        np, torch, whisper_model, vad_model, get_speech_timestamps = self._load_models()
        self._models = (np, torch, whisper_model, vad_model, get_speech_timestamps)

        # Generate synthetic speech-like audio (sine sweeps) instead of silence
        # This exercises the same code paths as real speech
        sr = self.audio_config.sample_rate
        for i in range(3):
            t = np.linspace(0, 1.5, int(sr * 1.5), dtype=np.float32)
            # Mix of frequencies that mimic speech formants
            dummy = (
                0.3 * np.sin(2 * np.pi * (200 + i * 100) * t) +
                0.2 * np.sin(2 * np.pi * (800 + i * 200) * t) +
                0.1 * np.sin(2 * np.pi * (2000 + i * 300) * t) +
                np.random.randn(len(t)).astype(np.float32) * 0.05
            ).astype(np.float32)
            segments, _ = whisper_model.transcribe(
                dummy,
                beam_size=self.stt_config.beam_size,
                language=self.stt_config.language,
                vad_filter=False,
            )
            list(segments)  # consume the generator

        logger.info("STT warmup done in %.1fs (%d warmup runs)", time.time() - t0, 3)

    def run_loop(self, stop_event: Event, output_queue: "queue.Queue[TranscriptEvent]") -> None:
        if self._models is not None:
            np, torch, whisper_model, vad_model, get_speech_timestamps = self._models
        else:
            np, torch, whisper_model, vad_model, get_speech_timestamps = self._load_models()

        chunk_bytes = self.audio_config.sample_rate * 2 // 10
        max_buffer_samples = int(self.audio_config.max_buffer_sec * self.audio_config.sample_rate)
        overlap_samples = int(0.5 * self.audio_config.sample_rate)

        audio_buffer = np.array([], dtype=np.float32)
        last_transcript = ""
        last_process_time = time.monotonic()

        with PulseAudioCapture(self.audio_config) as capture:
            while not stop_event.is_set():
                raw = capture.read(chunk_bytes)
                if not raw:
                    break

                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                audio_buffer = np.concatenate([audio_buffer, samples])

                now = time.monotonic()
                buffer_duration = len(audio_buffer) / self.audio_config.sample_rate
                if (
                    buffer_duration < self.audio_config.process_interval_sec
                    or (now - last_process_time) < self.audio_config.process_interval_sec
                ):
                    continue

                last_process_time = now
                if len(audio_buffer) > max_buffer_samples:
                    audio_buffer = audio_buffer[-max_buffer_samples:]

                rms = float(np.sqrt(np.mean(audio_buffer ** 2)))
                if rms < self.audio_config.rms_silence_threshold:
                    audio_buffer = audio_buffer[-overlap_samples:] if len(audio_buffer) > overlap_samples else audio_buffer
                    continue

                timestamps = get_speech_timestamps(
                    torch.from_numpy(audio_buffer),
                    vad_model,
                    sampling_rate=self.audio_config.sample_rate,
                    min_speech_duration_ms=int(self.audio_config.min_speech_duration_sec * 1000),
                    threshold=self.stt_config.vad_threshold,
                )
                if not timestamps:
                    audio_buffer = audio_buffer[-overlap_samples:] if len(audio_buffer) > overlap_samples else audio_buffer
                    continue

                start_sample = timestamps[0]["start"]
                end_sample = timestamps[-1]["end"]
                speech_duration = (end_sample - start_sample) / self.audio_config.sample_rate
                if speech_duration < self.audio_config.min_speech_duration_sec:
                    continue

                gap_samples = len(audio_buffer) - end_sample
                still_talking = gap_samples < int(self.audio_config.end_of_speech_silence_sec * self.audio_config.sample_rate)
                if still_talking and len(audio_buffer) < max_buffer_samples:
                    continue

                speech_audio = audio_buffer[start_sample:end_sample]
                t0 = time.monotonic()
                segments, _ = whisper_model.transcribe(
                    speech_audio,
                    beam_size=self.stt_config.beam_size,
                    language=self.stt_config.language,
                    vad_filter=False,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
                stt_duration = time.monotonic() - t0

                normalized = text.casefold()
                if text and normalized != last_transcript:
                    output_queue.put(
                        TranscriptEvent(
                            text=text,
                            timestamp=time.strftime("%H:%M:%S"),
                            audio_duration=speech_duration,
                            stt_duration=stt_duration,
                        )
                    )
                    last_transcript = normalized

                audio_buffer = audio_buffer[-overlap_samples:] if len(audio_buffer) > overlap_samples else audio_buffer

    def _load_models(self):
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("numpy is required for the STT pipeline") from exc
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("torch is required for silero-vad") from exc
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is required for STT") from exc
        try:
            from silero_vad import get_speech_timestamps, load_silero_vad
        except ImportError as exc:
            raise RuntimeError("silero-vad is required for VAD") from exc

        whisper_model = WhisperModel(
            self.stt_config.model_size,
            device="cpu",
            compute_type=self.stt_config.compute_type,
        )
        vad_model = load_silero_vad()
        return np, torch, whisper_model, vad_model, get_speech_timestamps

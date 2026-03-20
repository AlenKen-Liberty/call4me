from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from call4me.audio.playback import PulseAudioPlayback
from call4me.config import TTSConfig


@dataclass(slots=True)
class PiperTTS:
    config: TTSConfig
    playback: PulseAudioPlayback

    def synthesize(self, text: str, output_path: str | Path | None = None) -> Path:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("TTS text cannot be empty")

        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        wav_path = Path(output_path) if output_path else output_dir / f"tts_{int(time.time() * 1000)}.wav"

        proc = subprocess.run(
            ["piper", "--model", self.config.model_path, "--output_file", str(wav_path)],
            input=cleaned,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "piper synthesis failed")

        return wav_path

    def speak(self, text: str) -> Path:
        wav_path = self.synthesize(text)
        self.playback.play_file(wav_path)
        return wav_path

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from call4me.config import AudioConfig


@dataclass(slots=True)
class PulseAudioPlayback:
    config: AudioConfig

    def play_file(self, path: str | Path) -> None:
        subprocess.run(
            ["paplay", "--device", self.config.tts_sink, str(path)],
            check=True,
            capture_output=True,
            text=True,
        )

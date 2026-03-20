from __future__ import annotations

import subprocess
from dataclasses import dataclass

from call4me.config import AudioConfig


@dataclass
class PulseAudioCapture:
    config: AudioConfig
    proc: subprocess.Popen[bytes] | None = None

    def open(self) -> None:
        if self.proc is not None:
            return
        self.proc = subprocess.Popen(
            [
                "parec",
                "--device",
                self.config.capture_device,
                "--format=s16le",
                "--channels=1",
                "--rate",
                str(self.config.sample_rate),
                "--latency-msec",
                str(self.config.parec_latency_ms),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def read(self, chunk_size: int) -> bytes:
        if self.proc is None or self.proc.stdout is None:
            raise RuntimeError("PulseAudio capture is not open")
        return self.proc.stdout.read(chunk_size)

    def close(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.proc = None

    def __enter__(self) -> "PulseAudioCapture":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from call4me.config import AudioConfig


@dataclass(slots=True)
class PulseAudioManager:
    config: AudioConfig

    def ensure_running(self) -> None:
        if subprocess.run(["pulseaudio", "--check"], capture_output=True).returncode != 0:
            subprocess.run(["pulseaudio", "--start"], check=True, capture_output=True)

    def ensure_devices(self, set_defaults: bool = True) -> None:
        self.ensure_running()

        sinks = self._list_short("sinks")
        if self.config.capture_sink not in sinks:
            self._run(
                [
                    "pactl",
                    "load-module",
                    "module-null-sink",
                    f"sink_name={self.config.capture_sink}",
                    "sink_properties=device.description=Call4Me_Capture",
                ]
            )
        if self.config.tts_sink not in sinks:
            self._run(
                [
                    "pactl",
                    "load-module",
                    "module-null-sink",
                    f"sink_name={self.config.tts_sink}",
                    "sink_properties=device.description=Call4Me_TTS",
                ]
            )

        sources = self._list_short("sources")
        if self.config.microphone_source not in sources:
            self._run(
                [
                    "pactl",
                    "load-module",
                    "module-remap-source",
                    f"master={self.config.tts_sink}.monitor",
                    f"source_name={self.config.microphone_source}",
                    "source_properties=device.description=Call4Me_Microphone",
                ]
            )

        if set_defaults:
            self._run(["pactl", "set-default-sink", self.config.capture_sink])
            self._run(["pactl", "set-default-source", self.config.microphone_source])

    def move_sink_inputs(self, sink_name: str | None = None) -> int:
        target_sink = sink_name or self.config.capture_sink
        result = subprocess.run(
            ["pactl", "list", "short", "sink-inputs"],
            capture_output=True,
            text=True,
            check=True,
        )
        moved = 0
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            sink_input_id = line.split("\t", 1)[0]
            try:
                self._run(["pactl", "move-sink-input", sink_input_id, target_sink])
                moved += 1
            except subprocess.CalledProcessError:
                continue
        return moved

    def _list_short(self, entity: str) -> set[str]:
        result = subprocess.run(
            ["pactl", "list", "short", entity],
            capture_output=True,
            text=True,
            check=True,
        )
        names: set[str] = set()
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                names.add(parts[1])
        return names

    @staticmethod
    def _run(cmd: list[str]) -> None:
        subprocess.run(cmd, check=True, capture_output=True, text=True)

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AudioConfig:
    sample_rate: int = 16000
    capture_sink: str = "call4me_capture"
    tts_sink: str = "call4me_tts"
    microphone_source: str = "call4me_mic"
    process_interval_sec: float = 1.5
    min_speech_duration_sec: float = 0.3
    end_of_speech_silence_sec: float = 0.8
    max_buffer_sec: float = 15.0
    rms_silence_threshold: float = 0.002
    parec_latency_ms: int = 50

    @property
    def capture_device(self) -> str:
        return f"{self.capture_sink}.monitor"


@dataclass(slots=True)
class STTConfig:
    model_size: str = "base"
    compute_type: str = "int8"
    language: str = "en"
    beam_size: int = 3
    vad_threshold: float = 0.3


@dataclass(slots=True)
class TTSConfig:
    model_path: str = "models/en_US-amy-medium.onnx"
    output_dir: str = "/tmp/call4me"


@dataclass(slots=True)
class LLMConfig:
    base_url: str = field(default_factory=lambda: os.environ.get("CALL4ME_LLM_BASE_URL", "http://127.0.0.1:8000/v1"))
    api_key: str = field(default_factory=lambda: os.environ.get("CALL4ME_LLM_API_KEY", "call4me"))
    model: str = field(default_factory=lambda: os.environ.get("CALL4ME_LLM_MODEL", "gpt-4.1-mini"))
    temperature: float = 0.2
    max_output_tokens: int = 180
    stream: bool = True


@dataclass(slots=True)
class BrowserConfig:
    cdp_url: str = "http://127.0.0.1:9222"
    voice_url: str = "https://voice.google.com/u/0/calls"
    timeout_ms: int = 30000
    openclaw_tool_path: str = "/home/ubuntu/scripts/openclaw-tool"


@dataclass(slots=True)
class AgentConfig:
    max_duration_sec: int = 1800
    idle_timeout_sec: int = 120
    transcript_history_limit: int = 20
    on_hold_message_interval_sec: int = 300
    auto_hangup_on_complete: bool = True


@dataclass(slots=True)
class MemoryConfig:
    db_path: str = "data/memory.sqlite"
    embed_model: str = "BAAI/bge-small-en-v1.5"


@dataclass(slots=True)
class Call4MeConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Call4MeConfig":
        return cls(
            audio=_merge_dataclass(AudioConfig, data.get("audio", {})),
            stt=_merge_dataclass(STTConfig, data.get("stt", {})),
            tts=_merge_dataclass(TTSConfig, data.get("tts", {})),
            llm=_merge_dataclass(LLMConfig, data.get("llm", {})),
            browser=_merge_dataclass(BrowserConfig, data.get("browser", {})),
            agent=_merge_dataclass(AgentConfig, data.get("agent", {})),
            memory=_merge_dataclass(MemoryConfig, data.get("memory", {})),
        )


def _merge_dataclass(cls_: type[Any], values: dict[str, Any]) -> Any:
    instance = cls_()
    for key, value in values.items():
        if hasattr(instance, key):
            setattr(instance, key, value)
    return instance


def load_config(path: str | os.PathLike[str] | None = None) -> Call4MeConfig:
    config_path = Path(path or "config.yaml")
    if not config_path.exists():
        return Call4MeConfig()

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load config.yaml") from exc

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping at top level of {config_path}")
    return Call4MeConfig.from_dict(data)

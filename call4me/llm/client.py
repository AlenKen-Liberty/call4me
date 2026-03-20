from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from call4me.config import LLMConfig


@dataclass(slots=True)
class LLMAction:
    kind: str
    raw: str
    text: str = ""
    digit: str = ""
    summary: str = ""


def parse_action(content: str) -> LLMAction:
    raw = content.strip()
    upper = raw.upper()

    if upper.startswith("DTMF:"):
        digit = raw.split(":", 1)[1].strip()
        return LLMAction(kind="dtmf", raw=raw, digit=digit)
    if upper == "HOLD_WAIT":
        return LLMAction(kind="hold_wait", raw=raw)
    if upper.startswith("CALL_DONE:"):
        summary = raw.split(":", 1)[1].strip()
        return LLMAction(kind="call_done", raw=raw, summary=summary)
    return LLMAction(kind="speak", raw=raw, text=raw)


class Chat2APIClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def next_action(self, system_prompt: str, history: list[dict[str, str]]) -> LLMAction:
        messages = [{"role": "system", "content": system_prompt}, *history]
        response = self._complete(messages)
        return parse_action(response)

    def _complete(self, messages: list[dict[str, str]]) -> str:
        client = self._create_client()
        if self.config.stream:
            return self._stream_completion(client, messages)
        completion = client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_output_tokens,
        )
        return (completion.choices[0].message.content or "").strip()

    def _stream_completion(self, client: Any, messages: list[dict[str, str]]) -> str:
        stream = client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_output_tokens,
            stream=True,
        )
        parts: list[str] = []
        for chunk in stream:
            for choice in chunk.choices:
                delta = choice.delta.content or ""
                if delta:
                    parts.append(delta)
        return "".join(parts).strip()

    def _create_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required for chat2api integration") from exc
        return OpenAI(base_url=self.config.base_url, api_key=self.config.api_key)

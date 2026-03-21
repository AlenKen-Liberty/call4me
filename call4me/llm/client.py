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
        digit_str = raw.split(":", 1)[1].strip()
        digit = digit_str[0] if digit_str else ""
        return LLMAction(kind="dtmf", raw=raw, digit=digit)
    if upper == "HOLD_WAIT" or upper.startswith("HOLD_WAIT"):
        return LLMAction(kind="hold_wait", raw=raw)
    if upper.startswith("CALL_DONE:"):
        summary = raw.split(":", 1)[1].strip()
        return LLMAction(kind="call_done", raw=raw, summary=summary)

    # Handle mixed response: LLM sometimes combines speech + action marker
    # e.g. "Got it, thanks.\nCALL_DONE:summary here"
    # Extract only the speech part before any action marker.
    speech = raw
    for marker in ("CALL_DONE:", "DTMF:", "HOLD_WAIT"):
        idx = raw.upper().find(marker)
        if idx > 0:
            speech = raw[:idx].strip()
            break

    # Strip any internal reasoning / meta-commentary that leaks through
    # e.g. "(I should say goodbye)" or "[action: hang up]"
    import re
    speech = re.sub(r"\(.*?\)", "", speech)
    speech = re.sub(r"\[.*?\]", "", speech)
    speech = speech.strip()

    if not speech:
        return LLMAction(kind="hold_wait", raw=raw)
    return LLMAction(kind="speak", raw=raw, text=speech)


class Chat2APIClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def next_action(self, system_prompt: str, history: list[dict[str, str]]) -> LLMAction:
        messages = [{"role": "system", "content": system_prompt}, *history]
        response = self._complete_messages(messages)
        return parse_action(response)

    def complete_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self._complete_messages(
            messages,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )

    def complete_messages(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        full_messages = list(messages)
        if system_prompt:
            full_messages = [{"role": "system", "content": system_prompt}, *full_messages]
        return self._complete_messages(
            full_messages,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )

    def _complete_messages(
        self,
        messages: list[dict[str, str]],
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        client = self._create_client()
        if self.config.stream:
            return self._stream_completion(
                client,
                messages,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            )
        completion = client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature if temperature is None else temperature,
            max_tokens=self.config.max_output_tokens if max_output_tokens is None else max_output_tokens,
        )
        return (completion.choices[0].message.content or "").strip()

    def _stream_completion(
        self,
        client: Any,
        messages: list[dict[str, str]],
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        stream = client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature if temperature is None else temperature,
            max_tokens=self.config.max_output_tokens if max_output_tokens is None else max_output_tokens,
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

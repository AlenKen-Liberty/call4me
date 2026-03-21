"""Pre-call interviewer: LLM analyses what's known, asks ONLY what's missing."""

from __future__ import annotations

import json
import logging
from typing import Callable

from call4me.llm import Chat2APIClient
from call4me.memory import CallMemoryService
from .script import CallPlan

logger = logging.getLogger("call4me.planner")

INTERVIEW_SYSTEM = """\
You are a call-preparation assistant.  The user wants to make a phone call.
They have already provided some information — possibly everything you need.

Your ONLY job: analyse what's given and decide whether anything critical is
still missing or ambiguous.

What counts as "critical":
  - phone number (required)
  - who we are calling (name or company)
  - what we want to achieve on this call
  - caller's own name (so the bot can introduce itself)

If ALL of these are clear from the user's input, skip questions entirely and
output the plan JSON immediately.

If something is genuinely missing or ambiguous, ask ONE concise follow-up
question that covers all gaps.  Never ask something the user already told you.

When ready, output EXACTLY this JSON (no other text):

```json
{
  "ready": true,
  "phone_number": "digits only",
  "contact_name": "who picks up",
  "company": "company or relationship label",
  "user_name": "caller name",
  "purpose": "one-line goal",
  "tone": "warm and friendly / professional / casual",
  "key_info": {"address": "...", "plan": "...", ...},
  "special_instructions": "any extra strategy notes"
}
```

- Extract ALL factual details (addresses, account numbers, plan types, dates)
  into key_info.
- SECURITY: NEVER put the user's real personal phone number, email, SSN, or
  date of birth into key_info unless the user explicitly says to share it
  during the call. The phone_number field is the TARGET number to dial, not
  the user's own number. If the call plan doesn't include a callback number,
  don't invent one here — the bot will handle it at runtime.
- Respond in the same language the user uses for the conversation.
- BUT: the "purpose", "key_info" values, and "special_instructions" in the
  JSON MUST be in English — they will be used during an English phone call.
- If the user says "skip", "go", "ok", or "够了", produce the JSON immediately.
"""


class Interviewer:
    """Analyses user input, asks only what's genuinely missing."""

    def __init__(self, llm: Chat2APIClient, memory: CallMemoryService | None = None):
        self.llm = llm
        self.memory = memory

    def interview(
        self,
        raw_input: str,
        cli_hints: dict[str, str] | None = None,
        ask_fn: Callable[[str], str] | None = None,
        max_rounds: int = 2,
    ) -> CallPlan:
        """Analyse raw_input + CLI hints, ask follow-ups only if needed.

        ``cli_hints`` are pre-filled values from command-line flags.
        ``ask_fn`` displays a question and returns the user's answer.
        """
        first_msg = self._build_message(raw_input, cli_hints or {})

        history: list[dict[str, str]] = [
            {"role": "user", "content": first_msg},
        ]

        # First LLM call — might already produce the plan
        response = self.llm.complete_messages(
            history,
            system_prompt=INTERVIEW_SYSTEM,
            max_output_tokens=600,
            temperature=0.2,
        )

        plan = self._try_parse_plan(response)
        if plan:
            return plan

        # LLM wants to ask a question — only if we have ask_fn
        if ask_fn is None:
            return self._force_plan(history, response)

        for _ in range(max_rounds):
            history.append({"role": "assistant", "content": response})
            answer = ask_fn(response)
            if not answer or answer.strip().lower() in ("skip", "go", "ok", "够了"):
                break
            history.append({"role": "user", "content": answer})

            response = self.llm.complete_messages(
                history,
                system_prompt=INTERVIEW_SYSTEM,
                max_output_tokens=600,
                temperature=0.2,
            )
            plan = self._try_parse_plan(response)
            if plan:
                return plan

        return self._force_plan(history, response)

    def _force_plan(
        self, history: list[dict[str, str]], last_response: str
    ) -> CallPlan:
        """Force LLM to produce the plan JSON from what it has."""
        history.append({"role": "assistant", "content": last_response})
        history.append({
            "role": "user",
            "content": "That's all I have. Produce the plan JSON now.",
        })
        response = self.llm.complete_messages(
            history,
            system_prompt=INTERVIEW_SYSTEM,
            max_output_tokens=600,
            temperature=0.1,
        )
        plan = self._try_parse_plan(response)
        if plan:
            return plan

        # Last resort: extract whatever we can
        return CallPlan(
            phone_number="",
            contact_name="customer service",
            user_name="",
            company="",
            purpose="General call",
            tone="friendly",
        )

    def _build_message(self, raw_input: str, cli_hints: dict[str, str]) -> str:
        parts = [raw_input.strip()]

        hint_lines: list[str] = []
        for key, val in cli_hints.items():
            if val and val.strip():
                hint_lines.append(f"  {key}: {val}")
        if hint_lines:
            parts.append("\nAdditional info from command line:")
            parts.extend(hint_lines)

        if self.memory:
            # Try to find company from the input for memory lookup
            company = cli_hints.get("company", "")
            if company:
                ctx = self.memory.get_context_for_call(company, raw_input)
                if ctx.strip():
                    parts.append(f"\nPast experience:\n{ctx}")

        return "\n".join(parts)

    @staticmethod
    def _try_parse_plan(response: str) -> CallPlan | None:
        try:
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "{" in response and "}" in response:
                start = response.index("{")
                end = response.rindex("}") + 1
                json_str = response[start:end]
            else:
                return None

            data = json.loads(json_str)
            if not data.get("ready", False):
                return None

            return CallPlan(
                phone_number=data.get("phone_number", ""),
                contact_name=data.get("contact_name", "customer service"),
                user_name=data.get("user_name", ""),
                company=data.get("company", ""),
                purpose=data.get("purpose", "General call"),
                tone=data.get("tone", "friendly"),
                key_info=data.get("key_info", {}),
                special_instructions=data.get("special_instructions", ""),
            )
        except (json.JSONDecodeError, ValueError, IndexError):
            return None

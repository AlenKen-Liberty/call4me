"""Pre-call interviewer: LLM asks clarifying questions, builds a CallPlan."""

from __future__ import annotations

import json
import logging
from typing import Callable

from call4me.llm import Chat2APIClient
from call4me.memory import CallMemoryService
from .script import CallPlan

logger = logging.getLogger("call4me.planner")

INTERVIEW_SYSTEM = """\
You are a call-preparation assistant. The user wants to make a phone call and has
given you some basic information. Your job is to ask SHORT, targeted follow-up
questions to make sure the call goes smoothly.

Rules:
- Ask at most 3 questions total (fewer if the info is already sufficient).
- Each question should be ONE line, direct and practical.
- When you have enough info, output EXACTLY the JSON block below (no extra text):

```json
{
  "ready": true,
  "purpose": "one-line purpose of the call",
  "tone": "warm and friendly / professional / casual / etc.",
  "key_info": {"key": "value", ...},
  "special_instructions": "any special notes"
}
```

- If the user says "skip" or "go", stop asking and output the JSON with what you have.
- Always respond in the same language the user uses.
"""


class Interviewer:
    """Conducts a short Q&A with the user to build a complete CallPlan."""

    def __init__(self, llm: Chat2APIClient, memory: CallMemoryService | None = None):
        self.llm = llm
        self.memory = memory

    def interview(
        self,
        phone_number: str,
        contact_name: str,
        user_name: str,
        company: str,
        initial_purpose: str,
        ask_fn: Callable[[str], str] | None = None,
        max_rounds: int = 3,
    ) -> CallPlan:
        """Run the interview loop and return a CallPlan.

        ``ask_fn`` is a callback that displays a question and returns the
        user's answer.  If *None*, the interviewer skips Q&A and builds the
        plan from whatever was provided.
        """
        # Seed memory context if available
        memory_hint = ""
        if self.memory:
            memory_hint = self.memory.get_context_for_call(company, initial_purpose)

        first_msg = self._build_initial_message(
            phone_number, contact_name, user_name, company,
            initial_purpose, memory_hint,
        )

        history: list[dict[str, str]] = [
            {"role": "user", "content": first_msg},
        ]

        # If no ask_fn, skip interactive loop
        if ask_fn is None:
            return self._quick_plan(
                phone_number, contact_name, user_name, company,
                initial_purpose,
            )

        for _ in range(max_rounds):
            response = self.llm.complete_messages(
                history,
                system_prompt=INTERVIEW_SYSTEM,
                max_output_tokens=500,
                temperature=0.3,
            )

            # Check if LLM is ready (JSON output)
            plan = self._try_parse_plan(
                response, phone_number, contact_name, user_name, company
            )
            if plan:
                return plan

            # Show question to user, get answer
            history.append({"role": "assistant", "content": response})
            answer = ask_fn(response)
            if not answer or answer.strip().lower() in ("skip", "go", "ok", "够了"):
                break

            history.append({"role": "user", "content": answer})

        # Final attempt: force LLM to produce the JSON
        history.append({
            "role": "user",
            "content": "That's all the info I have. Please produce the plan JSON now.",
        })
        response = self.llm.complete_messages(
            history,
            system_prompt=INTERVIEW_SYSTEM,
            max_output_tokens=500,
            temperature=0.2,
        )
        plan = self._try_parse_plan(
            response, phone_number, contact_name, user_name, company
        )
        if plan:
            return plan

        # Fallback: build from what we have
        return self._quick_plan(
            phone_number, contact_name, user_name, company, initial_purpose
        )

    def _build_initial_message(
        self, phone_number: str, contact_name: str, user_name: str,
        company: str, purpose: str, memory_hint: str,
    ) -> str:
        parts = [
            f"I want to call {contact_name} at {phone_number}.",
            f"My name is {user_name}.",
            f"Purpose: {purpose}",
        ]
        if company:
            parts.append(f"Company/Relationship: {company}")
        if memory_hint:
            parts.append(f"\nPast experience:\n{memory_hint}")
        return "\n".join(parts)

    @staticmethod
    def _try_parse_plan(
        response: str, phone_number: str, contact_name: str,
        user_name: str, company: str,
    ) -> CallPlan | None:
        # Try to extract JSON from the response
        try:
            # Look for ```json ... ``` block
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "{" in response and "}" in response:
                # Find the outermost JSON object
                start = response.index("{")
                end = response.rindex("}") + 1
                json_str = response[start:end]
            else:
                return None

            data = json.loads(json_str)
            if not data.get("ready", False):
                return None

            return CallPlan(
                phone_number=phone_number,
                contact_name=contact_name,
                user_name=user_name,
                company=company,
                purpose=data.get("purpose", "General call"),
                tone=data.get("tone", "friendly"),
                key_info=data.get("key_info", {}),
                special_instructions=data.get("special_instructions", ""),
            )
        except (json.JSONDecodeError, ValueError, IndexError):
            return None

    @staticmethod
    def _quick_plan(
        phone_number: str, contact_name: str, user_name: str,
        company: str, purpose: str,
    ) -> CallPlan:
        """Build a plan directly without LLM Q&A."""
        return CallPlan(
            phone_number=phone_number,
            contact_name=contact_name,
            user_name=user_name,
            company=company,
            purpose=purpose,
            tone="warm and friendly",
        )

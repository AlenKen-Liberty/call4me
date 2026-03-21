"""Generate ONE CallScript, then surface key decision points for the user."""

from __future__ import annotations

import json
import logging
from typing import Callable

from call4me.llm import Chat2APIClient
from call4me.memory import CallMemoryService
from .script import CallPlan, CallScript, ScriptNode

logger = logging.getLogger("call4me.planner")

SCRIPT_GEN_PROMPT = """\
You are a conversation strategist. Given a phone-call plan, generate a
practical conversation script as a JSON tree.

Call plan:
{plan_summary}

{memory_hint}

Generate a JSON object with this structure:
{{
  "opening": [
    {{
      "id": "open_1",
      "trigger": "how they might answer",
      "response": "what we say back",
      "notes": "",
      "priority": 10,
      "children": [...]
    }}
  ],
  "scenarios": [...],
  "closing": [...],
  "fallback_strategy": "what to do if nothing matches"
}}

SECURITY (mandatory):
- NEVER include real phone numbers, emails, SSNs, dates of birth, or credit
  card numbers in any response. If the script needs a callback number, use
  the local area code plus made-up digits (e.g. 919-555-XXXX for NC).
- Only use information explicitly provided in the call plan above.
- If a scenario requires info not in the plan, the response should say
  "I don't have that with me right now" or similar.

Rules:
- Generate 2-3 opening scenarios
- Generate 3-5 mid-call scenarios (likely obstacles, questions, objections)
- Generate 1-2 closing scenarios
- Each response: EXACT spoken words, SHORT (1-2 sentences)
- Children = follow-up exchanges, max depth 3
- Triggers: use "/" to separate alternatives
- INFORMATION MANAGEMENT: Collect required information (address, account number,
  name, confirmation codes) in the OPENING phase only. Never ask for the same
  information twice. Don't pre-emptively volunteer information already confirmed.
- NEVER repeat the same information in multiple responses. If the caller's
  address, name, or request needs to be stated, write it ONCE in the most
  likely scenario. Other nodes that might also need it should say something
  like "Sure, let me repeat that — " and reference the same core fact, but
  do NOT generate multiple near-identical sentences just with different
  phrasing.  Each response in the script must be meaningfully different.
- ALL responses MUST be in English. These will be spoken aloud via TTS on
  an English-language phone call. Never generate responses in any other
  language, regardless of what language the plan description is written in.
- NUMBER PRONUNCIATION: Write numbers as humans say them on the phone.
  Street numbers: '1031' → 'ten thirty-one'. Phone numbers: group as
  three-three-four with commas: '786, 874, 4562'. Zip codes: each digit
  separately: '2 7 5 1 1'. Never write raw digit strings like '1031'.
- NAME: Introduce yourself by a single first name. Never say "I am
  [someone]'s assistant". Just use the caller's name directly.
- Ask ONE question per response. Never stack 3-4 questions together.
- Avoid generic filler responses like "Okay, thank you for checking" as the
  response for multiple nodes. Each scenario should have a SPECIFIC next
  question or acknowledgment that advances the conversation goal.
- Output ONLY the JSON, no markdown fences
"""

DECISIONS_PROMPT = """\
You are reviewing a phone-call script for a user before they dial.

Call purpose: {purpose}

Here is the generated script:
{script_json}

Identify 1-3 KEY DECISION POINTS where a reasonable caller might want to
choose between genuinely different approaches.  Only flag decisions where the
two options would lead to meaningfully different conversations — do NOT flag
routine exchanges (greetings, spelling addresses, saying goodbye).

Good examples of real decisions:
- "If they ask for account info: A) Say you're a new customer  B) Give a reference number"
- "If they push an upsell: A) Decline firmly  B) Ask for details to compare"
- "Opening strategy: A) State your request immediately  B) Ask about availability first"

Bad examples (don't include these):
- Different phrasings of the same information ("Hi it's David" vs "Hey this is David")
- Whether to be polite (always be polite)

Output a JSON array (no extra text):
[
  {{
    "id": "decision_1",
    "situation": "short description of the moment",
    "option_a": "first approach (1 sentence)",
    "option_b": "second approach (1 sentence)",
    "default": "a"
  }}
]

If the script is straightforward and has no real decision points, output: []
"""


class ScriptGenerator:
    """Generates ONE script, surfaces key decisions for user choice."""

    def __init__(self, llm: Chat2APIClient, memory: CallMemoryService | None = None):
        self.llm = llm
        self.memory = memory

    def generate(self, plan: CallPlan) -> CallScript:
        """Generate a single script from the plan."""
        memory_hint = ""
        if self.memory:
            ctx = self.memory.get_context_for_call(plan.company, plan.purpose)
            if ctx.strip():
                memory_hint = f"Past experience with this contact:\n{ctx}"

        prompt = SCRIPT_GEN_PROMPT.format(
            plan_summary=plan.summary(),
            memory_hint=memory_hint,
        )
        raw = self.llm.complete_text(prompt, max_output_tokens=2000, temperature=0.3)
        return self._parse_script(raw, plan)

    def get_decisions(
        self,
        script: CallScript,
        ask_fn: Callable[[str], str] | None = None,
    ) -> CallScript:
        """Identify key decision points in the script and ask the user.

        Modifies script nodes in-place based on user choices.
        If ask_fn is None, uses defaults.
        """
        script_json = json.dumps(
            {
                "opening": [n.to_dict() for n in script.opening],
                "scenarios": [n.to_dict() for n in script.scenarios],
                "closing": [n.to_dict() for n in script.closing],
            },
            ensure_ascii=False,
        )

        prompt = DECISIONS_PROMPT.format(
            purpose=script.plan.purpose,
            script_json=script_json[:3000],  # truncate if huge
        )

        raw = self.llm.complete_text(prompt, max_output_tokens=800, temperature=0.2)
        decisions = self._parse_decisions(raw)

        if not decisions:
            logger.info("No key decisions found — script is straightforward")
            return script

        if ask_fn is None:
            return script

        # Present each decision to the user
        for d in decisions:
            question = (
                f"Decision: {d['situation']}\n"
                f"  A) {d['option_a']}\n"
                f"  B) {d['option_b']}\n"
                f"  (default: {d['default'].upper()})"
            )
            answer = ask_fn(question)
            choice = answer.strip().lower() if answer else d["default"]
            if choice not in ("a", "b"):
                choice = d["default"]

            # Apply the choice: ask LLM to adjust the relevant script node
            chosen_text = d["option_a"] if choice == "a" else d["option_b"]
            d["chosen"] = chosen_text
            logger.info("Decision %s: user chose %s — %s", d["id"], choice, chosen_text)

        # Regenerate affected nodes with the decisions applied
        return self._apply_decisions(script, decisions)

    def _apply_decisions(
        self, script: CallScript, decisions: list[dict]
    ) -> CallScript:
        """Update script nodes based on user decisions."""
        if not decisions:
            return script

        # Build a guidance string for system prompt augmentation
        guidance_parts = []
        for d in decisions:
            if "chosen" in d:
                guidance_parts.append(
                    f"- When {d['situation']}: {d['chosen']}"
                )
        if guidance_parts:
            extra = "\n".join(guidance_parts)
            if script.fallback_strategy:
                script.fallback_strategy += f"\nUser preferences:\n{extra}"
            else:
                script.fallback_strategy = f"User preferences:\n{extra}"

        return script

    def _parse_script(self, raw: str, plan: CallPlan) -> CallScript:
        try:
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            data = json.loads(raw)
        except (json.JSONDecodeError, IndexError) as exc:
            logger.warning("Failed to parse script JSON: %s", exc)
            return self._fallback_script(plan)

        try:
            opening = [ScriptNode.from_dict(n) for n in data.get("opening", [])]
            scenarios = [ScriptNode.from_dict(n) for n in data.get("scenarios", [])]
            closing = [ScriptNode.from_dict(n) for n in data.get("closing", [])]
            fallback = data.get("fallback_strategy", "")
        except (KeyError, TypeError) as exc:
            logger.warning("Script structure error: %s", exc)
            return self._fallback_script(plan)

        script = CallScript(
            plan=plan,
            opening=opening,
            scenarios=scenarios,
            closing=closing,
            fallback_strategy=fallback,
        )
        logger.info(
            "Generated script: %d opening, %d scenarios, %d closing, %d total nodes",
            len(opening), len(scenarios), len(closing), len(script.all_nodes()),
        )
        return script

    @staticmethod
    def _parse_decisions(raw: str) -> list[dict]:
        try:
            if "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return [
                d for d in data
                if all(k in d for k in ("id", "situation", "option_a", "option_b"))
            ]
        except (json.JSONDecodeError, KeyError):
            return []

    @staticmethod
    def _fallback_script(plan: CallPlan) -> CallScript:
        caller = plan.user_name or "the caller"
        opening = [
            ScriptNode(
                id="open_1",
                trigger="Hello / Hi / automated system",
                response=f"Hi, this is {caller}. I'm calling about {plan.purpose}.",
                priority=10,
            ),
        ]
        closing = [
            ScriptNode(
                id="close_1",
                trigger="Bye / Talk later",
                response="Thanks for your help. Have a good day.",
                priority=5,
            ),
        ]
        return CallScript(
            plan=plan,
            opening=opening,
            closing=closing,
            fallback_strategy=f"Be {plan.tone}. Goal: {plan.purpose}",
        )

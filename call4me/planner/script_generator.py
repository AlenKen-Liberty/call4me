"""Generate CallScript options from a CallPlan using LLM."""

from __future__ import annotations

import json
import logging

from call4me.llm import Chat2APIClient
from call4me.memory import CallMemoryService
from .script import CallPlan, CallScript, ScriptNode

logger = logging.getLogger("call4me.planner")

SCRIPT_GEN_PROMPT = """\
You are a conversation strategist. Given a phone-call plan, generate a
practical conversation script as a JSON tree. The script should help the
caller react quickly in realistic branches.

Call plan:
{plan_summary}

Approach style:
{approach_name}: {approach_description}

{memory_hint}

Generate a JSON object with this structure:
{{
  "name": "short option name",
  "description": "one-line summary of the approach",
  "opening": [
    {{
      "id": "open_1",
      "trigger": "how they might open the call",
      "response": "what we should say back",
      "notes": "strategy note",
      "priority": 10,
      "children": [
        {{
          "id": "open_1_a",
          "trigger": "possible follow-up",
          "response": "next reply",
          "notes": "",
          "priority": 10,
          "children": []
        }}
      ]
    }}
  ],
  "scenarios": [
    {{
      "id": "scenario_1",
      "trigger": "description of what they might say",
      "response": "what to say back",
      "notes": "strategy note",
      "priority": 5,
      "children": []
    }}
  ],
  "closing": [
    {{
      "id": "close_1",
      "trigger": "Alright, bye / Talk to you later",
      "response": "Thanks again. Have a good day.",
      "notes": "",
      "priority": 5,
      "children": []
    }}
  ],
  "fallback_strategy": "what to do if nothing matches"
}}

Rules:
- Generate 2-3 opening scenarios
- Generate 3-5 mid-call scenarios that cover likely obstacles, questions, and objections
- Generate 1-2 closing scenarios
- Each response must be EXACTLY what would be spoken aloud
- Keep responses SHORT (1-2 sentences max, like real phone talk)
- Use the tone specified in the plan
- Children represent follow-up exchanges within that branch
- Max depth: 3 levels
- Triggers should cover common variations (use "/" to separate alternatives)
- Avoid hardcoding personal contexts unless they are explicitly in the plan
- Output ONLY the JSON, no markdown fences, no extra text
"""

SCRIPT_APPROACHES = [
    ("Safe", "Polite, low-risk, concise, optimized for clarity and cooperation."),
    ("Warm", "Friendly and human, with more rapport-building and empathy."),
    ("Assertive", "Still polite, but more direct about the goal and next steps."),
]


class ScriptGenerator:
    """Uses LLM to generate a CallScript from a CallPlan."""

    def __init__(self, llm: Chat2APIClient, memory: CallMemoryService | None = None):
        self.llm = llm
        self.memory = memory

    def generate(self, plan: CallPlan) -> CallScript:
        options = self.generate_options(plan, count=1)
        return options[0]

    def generate_options(self, plan: CallPlan, count: int = 3) -> list[CallScript]:
        """Generate multiple script options for the user to choose from."""
        memory_hint = ""
        if self.memory:
            ctx = self.memory.get_context_for_call(plan.company, plan.purpose)
            if ctx.strip():
                memory_hint = f"Past experience with this contact:\n{ctx}"

        options: list[CallScript] = []
        for idx, (name, description) in enumerate(SCRIPT_APPROACHES[: max(count, 1)]):
            prompt = SCRIPT_GEN_PROMPT.format(
                plan_summary=plan.summary(),
                memory_hint=memory_hint,
                approach_name=name,
                approach_description=description,
            )
            raw = self.llm.complete_text(
                prompt,
                max_output_tokens=2000,
                temperature=0.4,
            )
            script = self._parse_script(raw, plan, default_name=name, default_description=description)
            if not script.name:
                script.name = f"Option {idx + 1}: {name}"
            if not script.description:
                script.description = description
            options.append(script)
        return options

    def _parse_script(
        self,
        raw: str,
        plan: CallPlan,
        default_name: str = "",
        default_description: str = "",
    ) -> CallScript:
        """Parse the LLM output into a CallScript."""
        try:
            # Strip markdown fences if present
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            data = json.loads(raw)
        except (json.JSONDecodeError, IndexError) as exc:
            logger.warning("Failed to parse script JSON: %s", exc)
            logger.debug("Raw LLM output: %s", raw[:500])
            return self._fallback_script(plan, default_name, default_description)

        try:
            name = data.get("name", default_name)
            description = data.get("description", default_description)
            opening = [ScriptNode.from_dict(n) for n in data.get("opening", [])]
            scenarios = [ScriptNode.from_dict(n) for n in data.get("scenarios", [])]
            closing = [ScriptNode.from_dict(n) for n in data.get("closing", [])]
            fallback = data.get("fallback_strategy", "")
        except (KeyError, TypeError) as exc:
            logger.warning("Script structure error: %s", exc)
            return self._fallback_script(plan, default_name, default_description)

        script = CallScript(
            plan=plan,
            name=name,
            description=description,
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
    def _fallback_script(
        plan: CallPlan,
        name: str = "Fallback",
        description: str = "Minimal practical script.",
    ) -> CallScript:
        """Minimal fallback script if LLM generation fails."""
        caller = plan.user_name or "the caller"
        contact = plan.contact_name or plan.company or "the other party"

        opening = [
            ScriptNode(
                id="open_1",
                trigger="Hello / Hi / This is customer service / This is the person answering",
                response=f"Hi, this is {caller}. I'm calling about {plan.purpose}.",
                priority=10,
            ),
            ScriptNode(
                id="open_2",
                trigger="Who is this?",
                response=f"Hi, this is {caller}. I'm calling about {plan.purpose}.",
                priority=5,
            ),
        ]
        scenarios = [
            ScriptNode(
                id="scenario_1",
                trigger="Can you explain what you need? / How can I help?",
                response=f"Sure. I'm calling because {plan.purpose}.",
                notes="State the goal clearly.",
                priority=10,
            ),
            ScriptNode(
                id="scenario_2",
                trigger="I need to verify your identity / account / booking",
                response="Of course. Let me provide the details you need.",
                notes="Stay cooperative during verification.",
                priority=8,
            ),
        ]
        closing = [
            ScriptNode(
                id="close_1",
                trigger="Bye / Talk later / Gotta go",
                response="Thanks for your help. Have a good day.",
                priority=5,
            ),
        ]

        return CallScript(
            plan=plan,
            name=name,
            description=description,
            opening=opening,
            scenarios=scenarios,
            closing=closing,
            fallback_strategy=f"Be {plan.tone}. If unsure, restate the goal: {plan.purpose}",
        )

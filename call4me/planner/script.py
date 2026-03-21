"""Conversation script data model — a tree of anticipated dialogue turns."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScriptNode:
    """One anticipated exchange in the conversation tree.

    ``trigger`` describes what the other party might say (a pattern or
    description) and ``response`` is our planned reply.  Children represent
    possible follow-ups after this exchange.
    """

    id: str
    trigger: str  # what the other party might say (keyword/description)
    response: str  # our planned reply
    cached_wav: str | None = None  # pre-generated TTS audio path
    children: list[ScriptNode] = field(default_factory=list)
    notes: str = ""  # strategy notes (not spoken)
    priority: int = 0  # higher = tried first when matching

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "response": self.response,
            "notes": self.notes,
            "priority": self.priority,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, d: dict) -> ScriptNode:
        children = [cls.from_dict(c) for c in d.get("children", [])]
        return cls(
            id=d["id"],
            trigger=d["trigger"],
            response=d["response"],
            notes=d.get("notes", ""),
            priority=d.get("priority", 0),
            children=children,
        )


@dataclass
class CallPlan:
    """Structured plan produced by the Interviewer after Q&A with the user."""

    phone_number: str
    contact_name: str  # who we're calling
    user_name: str  # caller's name
    company: str  # company name or relationship label
    purpose: str  # one-line purpose
    tone: str  # e.g. "warm and friendly", "professional"
    key_info: dict[str, str] = field(default_factory=dict)  # collected facts
    special_instructions: str = ""  # user's extra notes

    def summary(self) -> str:
        lines = [
            f"Calling: {self.contact_name} at {self.phone_number}",
            f"Purpose: {self.purpose}",
            f"Tone: {self.tone}",
        ]
        if self.key_info:
            lines.append("Key info:")
            for k, v in self.key_info.items():
                lines.append(f"  {k}: {v}")
        if self.special_instructions:
            lines.append(f"Special: {self.special_instructions}")
        return "\n".join(lines)


@dataclass
class CallScript:
    """Full conversation script: a forest of scenario trees + a fallback."""

    plan: CallPlan
    name: str = ""
    description: str = ""
    opening: list[ScriptNode] = field(default_factory=list)
    scenarios: list[ScriptNode] = field(default_factory=list)
    closing: list[ScriptNode] = field(default_factory=list)
    fallback_strategy: str = ""  # what to do when nothing matches

    # ── helpers ────────────────────────────────────────────────────────

    def all_nodes(self) -> list[ScriptNode]:
        """Flatten every node in the script tree (BFS)."""
        result: list[ScriptNode] = []
        queue = [*self.opening, *self.scenarios, *self.closing]
        while queue:
            node = queue.pop(0)
            result.append(node)
            queue.extend(node.children)
        return result

    def all_responses(self) -> list[str]:
        """Every unique response string in the script."""
        seen: set[str] = set()
        out: list[str] = []
        for node in self.all_nodes():
            if node.response not in seen:
                seen.add(node.response)
                out.append(node.response)
        return out

    def to_display(self) -> str:
        """Human-readable script for user review."""
        parts: list[str] = []
        parts.append("=" * 60)
        parts.append("CALL SCRIPT")
        parts.append("=" * 60)
        if self.name:
            parts.append(f"Option: {self.name}")
        if self.description:
            parts.append(f"Approach: {self.description}")
        parts.append(self.plan.summary())
        parts.append("")

        def _render_tree(nodes: list[ScriptNode], indent: int = 0) -> None:
            pad = "  " * indent
            for node in sorted(nodes, key=lambda n: -n.priority):
                parts.append(f"{pad}[{node.id}] IF they say: \"{node.trigger}\"")
                parts.append(f"{pad}    YOU say: \"{node.response}\"")
                if node.notes:
                    parts.append(f"{pad}    (note: {node.notes})")
                if node.children:
                    _render_tree(node.children, indent + 1)
                parts.append("")

        if self.opening:
            parts.append("--- OPENING ---")
            _render_tree(self.opening)

        if self.scenarios:
            parts.append("--- MID-CALL SCENARIOS ---")
            _render_tree(self.scenarios)

        if self.closing:
            parts.append("--- CLOSING ---")
            _render_tree(self.closing)

        if self.fallback_strategy:
            parts.append(f"--- FALLBACK: {self.fallback_strategy} ---")

        parts.append("=" * 60)
        return "\n".join(parts)

    def save(self, path: str | Path) -> None:
        data = {
            "plan": {
                "phone_number": self.plan.phone_number,
                "contact_name": self.plan.contact_name,
                "user_name": self.plan.user_name,
                "company": self.plan.company,
                "purpose": self.plan.purpose,
                "tone": self.plan.tone,
                "key_info": self.plan.key_info,
                "special_instructions": self.plan.special_instructions,
            },
            "name": self.name,
            "description": self.description,
            "opening": [n.to_dict() for n in self.opening],
            "scenarios": [n.to_dict() for n in self.scenarios],
            "closing": [n.to_dict() for n in self.closing],
            "fallback_strategy": self.fallback_strategy,
        }
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: str | Path) -> CallScript:
        data = json.loads(Path(path).read_text())
        plan = CallPlan(**data["plan"])
        return cls(
            plan=plan,
            name=data.get("name", ""),
            description=data.get("description", ""),
            opening=[ScriptNode.from_dict(n) for n in data.get("opening", [])],
            scenarios=[ScriptNode.from_dict(n) for n in data.get("scenarios", [])],
            closing=[ScriptNode.from_dict(n) for n in data.get("closing", [])],
            fallback_strategy=data.get("fallback_strategy", ""),
        )

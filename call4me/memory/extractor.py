from __future__ import annotations

import json
import logging
from dataclasses import dataclass


@dataclass(slots=True)
class PostCallExtractor:
    llm_client: object
    memory_service: object
    logger: logging.Logger | None = None

    def extract_and_save(
        self,
        company: str,
        phone: str,
        task: str,
        transcripts: list,
        result: object,
        ivr_steps: list[str] | None = None,
    ) -> None:
        transcript_text = "\n".join(f"[{item.timestamp}] {item.text}" for item in transcripts)
        payload: dict[str, object] = {}

        if transcript_text.strip():
            prompt = self._build_prompt(company, phone, task, result, transcript_text, ivr_steps or [])
            try:
                response = self.llm_client.complete_text(
                    prompt,
                    system_prompt=(
                        "You extract structured learnings from customer service transcripts. "
                        "Return valid JSON only."
                    ),
                )
                payload = self._parse_json(response)
            except Exception as exc:
                self._log(logging.WARNING, "Post-call extraction failed: %s", exc)

        ivr_path = str(payload.get("ivr_path") or self._format_ivr_path(ivr_steps or [])).strip()
        ivr_shortcut = str(payload.get("ivr_shortcut") or "").strip()
        avg_hold_minutes = payload.get("avg_hold_minutes")
        notes = str(payload.get("company_specific_notes") or "").strip()
        learnings = self._summarize_learnings(payload)

        if ivr_path or ivr_shortcut or notes:
            self.memory_service.save_ivr_map(
                company=company,
                phone=phone,
                path=ivr_path or "unknown",
                ivr_shortcut=ivr_shortcut,
                avg_hold_minutes=avg_hold_minutes,
                last_updated=self._today(),
                notes=notes,
                trust=1.0 if getattr(result, "completed", False) else 0.7,
            )

        for strategy in self._as_list(payload.get("strategies_that_worked")):
            self.memory_service.save_strategy(company, strategy, trust=0.9)
        for strategy in self._as_list(payload.get("strategies_that_failed")):
            self.memory_service.save_strategy(company, f"Avoid: {strategy}", trust=0.5)
        for tip in self._as_list(payload.get("general_tips")):
            self.memory_service.save_general_tip(tip, trust=0.8)
        if notes:
            self.memory_service.save_strategy(company, f"Company-specific note: {notes}", trust=0.85)

        self.memory_service.save_outcome(
            company=company,
            phone=phone,
            task=task,
            result="SUCCESS" if getattr(result, "completed", False) else "INCOMPLETE",
            summary=getattr(result, "summary", ""),
            duration_sec=int(getattr(result, "duration_sec", 0)),
            learnings=learnings,
            ivr_path=ivr_path,
        )

    def _build_prompt(
        self,
        company: str,
        phone: str,
        task: str,
        result: object,
        transcript_text: str,
        ivr_steps: list[str],
    ) -> str:
        observed_path = self._format_ivr_path(ivr_steps)
        outcome = "SUCCESS" if getattr(result, "completed", False) else "INCOMPLETE"
        summary = getattr(result, "summary", "")
        return f"""Analyze this customer service call transcript and extract learnings.

Company: {company}
Phone: {phone}
Task: {task}
Outcome: {outcome}
Summary: {summary}
Observed IVR steps: {observed_path or "unknown"}

TRANSCRIPT:
{transcript_text}

Return strict JSON with this shape:
{{
  "ivr_path": "sequence of keys pressed to navigate IVR",
  "ivr_shortcut": "fastest way to reach a human, if discovered",
  "avg_hold_minutes": 0,
  "strategies_that_worked": ["..."],
  "strategies_that_failed": ["..."],
  "general_tips": ["..."],
  "company_specific_notes": "..."
}}"""

    def _parse_json(self, response: str) -> dict[str, object]:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("LLM response did not contain JSON")
        return json.loads(cleaned[start : end + 1])

    def _summarize_learnings(self, payload: dict[str, object]) -> str:
        parts: list[str] = []
        if payload.get("ivr_shortcut"):
            parts.append(f"IVR shortcut: {payload['ivr_shortcut']}")
        if payload.get("company_specific_notes"):
            parts.append(f"Notes: {payload['company_specific_notes']}")
        worked = self._as_list(payload.get("strategies_that_worked"))
        if worked:
            parts.append("Worked: " + "; ".join(worked))
        failed = self._as_list(payload.get("strategies_that_failed"))
        if failed:
            parts.append("Failed: " + "; ".join(failed))
        return " | ".join(parts)

    def _as_list(self, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _log(self, level: int, message: str, *args: object) -> None:
        if self.logger is not None:
            self.logger.log(level, message, *args)

    @staticmethod
    def _format_ivr_path(ivr_steps: list[str]) -> str:
        return " -> ".join(ivr_steps)

    @staticmethod
    def _today() -> str:
        from datetime import date

        return date.today().isoformat()

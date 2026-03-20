from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TaskPrompt:
    task: str
    goal: str
    context: str


TEMPLATES: dict[str, dict[str, str]] = {
    "flight_change": {
        "task": "Change flight reservation",
        "goal": "Change flight {flight_number} from {current_date} to {new_date}",
        "context": "Passenger: {name}, Confirmation: {code}, Max fee: ${max_fee}",
    },
    "price_inquiry": {
        "task": "Get pricing information",
        "goal": "Ask about pricing for {product_or_service}",
        "context": "Questions: {questions}",
    },
    "general": {
        "task": "{task}",
        "goal": "{goal}",
        "context": "{context}",
    },
}


def render_task_prompt(template: str = "general", **values: str) -> TaskPrompt:
    if template not in TEMPLATES:
        raise KeyError(f"Unknown task template: {template}")

    raw_template = TEMPLATES[template]
    try:
        task = raw_template["task"].format(**values)
        goal = raw_template["goal"].format(**values)
        context = raw_template["context"].format(**values)
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(f"Missing template field: {missing}") from exc

    return TaskPrompt(task=task.strip(), goal=goal.strip(), context=context.strip())

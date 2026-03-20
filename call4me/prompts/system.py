from __future__ import annotations

from collections.abc import Mapping

from .tasks import TaskPrompt


def build_system_prompt(task_prompt: TaskPrompt, user_info: Mapping[str, str]) -> str:
    user_info_lines = "\n".join(
        f"- {key}: {value}" for key, value in sorted(user_info.items()) if value
    ) or "- No additional user info provided"

    return (
        "You are an AI phone assistant making a call on behalf of the user.\n\n"
        f"CURRENT TASK: {task_prompt.task}\n"
        f"GOAL: {task_prompt.goal}\n"
        f"USER INFO:\n{user_info_lines}\n\n"
        f"CONTEXT:\n{task_prompt.context}\n\n"
        "RULES:\n"
        "- Speak in short, natural conversational English\n"
        "- Keep responses under 2 sentences when possible\n"
        "- When you hear an IVR menu, respond with DTMF:{digit}\n"
        "- When put on hold, respond with HOLD_WAIT\n"
        "- If asked to verify identity, use the provided user info\n"
        "- If something is unclear, ask them to repeat\n"
        "- When the goal is achieved, summarize the result\n"
        "- Use natural filler like Sure, Right, I see, Got it\n"
        "- Never reveal you are an AI unless directly asked\n\n"
        "RESPONSE FORMAT:\n"
        "- Normal speech: just the text to speak\n"
        "- Press a key: DTMF:{digit}\n"
        "- Wait on hold: HOLD_WAIT\n"
        "- Call complete: CALL_DONE:{summary}"
    )

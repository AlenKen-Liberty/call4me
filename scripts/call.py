#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from call4me import Call4MeAgent, CallRequest, load_config
from call4me.cli import InteractiveCLI
from call4me.planner import Interviewer, ScriptGenerator
from call4me.prompts import TaskPrompt, render_task_prompt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call4Me phone automation CLI")
    parser.add_argument("--number", help="Destination phone number")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.yaml"), help="Path to config.yaml")
    parser.add_argument("--template", default="general", choices=["general", "flight_change", "price_inquiry"])
    parser.add_argument("--company", help="Company name for memory lookup and post-call learning")
    parser.add_argument("--contact-name", help="Who is expected to answer the phone")
    parser.add_argument("--task", help="Task description")
    parser.add_argument("--goal", help="Goal description")
    parser.add_argument("--context", default="", help="Extra context for the agent")
    parser.add_argument("--name", help="User name")
    parser.add_argument("--confirmation", help="Confirmation code or reference number")
    parser.add_argument("--user-info", action="append", default=[], help="Extra user info in key=value format")
    parser.add_argument("--flight-number", help="Flight number for the flight_change template")
    parser.add_argument("--current-date", help="Current flight date")
    parser.add_argument("--new-date", help="Requested new flight date")
    parser.add_argument("--max-fee", help="Maximum acceptable change fee")
    parser.add_argument("--product-or-service", help="Target product or service for price inquiry")
    parser.add_argument("--questions", help="Questions to ask during a price inquiry")
    parser.add_argument("--max-duration", type=int, help="Override max call duration in seconds")
    parser.add_argument("--interactive", action="store_true", help="Run the pre-call interview and live interactive CLI")
    return parser


def build_task_prompt(args: argparse.Namespace) -> TaskPrompt:
    if args.template == "general":
        task = args.task or args.goal
        if not task:
            raise ValueError("--task is required for the general template")
        return render_task_prompt(
            "general",
            task=task,
            goal=args.goal or task,
            context=args.context or "Handle the call politely and keep it concise.",
        )

    if args.template == "flight_change":
        return render_task_prompt(
            "flight_change",
            flight_number=_required(args.flight_number, "--flight-number"),
            current_date=_required(args.current_date, "--current-date"),
            new_date=_required(args.new_date, "--new-date"),
            name=_required(args.name, "--name"),
            code=_required(args.confirmation, "--confirmation"),
            max_fee=args.max_fee or "0",
        )

    return render_task_prompt(
        "price_inquiry",
        product_or_service=_required(args.product_or_service, "--product-or-service"),
        questions=args.questions or args.context or "Please explain the pricing options.",
    )


def build_user_info(args: argparse.Namespace) -> dict[str, str]:
    user_info: dict[str, str] = {}
    if args.name:
        user_info["name"] = args.name
    if args.confirmation:
        user_info["confirmation"] = args.confirmation

    for item in args.user_info:
        if "=" not in item:
            raise ValueError(f"Expected key=value for --user-info, got: {item}")
        key, value = item.split("=", 1)
        user_info[key.strip()] = value.strip()
    return user_info


def build_interactive_request(args: argparse.Namespace, agent: Call4MeAgent) -> CallRequest:
    cli = InteractiveCLI()
    cli.show_banner("Call4Me Interactive Planner")

    # Collect CLI hints (anything the user already provided via flags)
    cli_hints: dict[str, str] = {}
    if args.number:
        cli_hints["phone_number"] = args.number
    if args.company:
        cli_hints["company"] = args.company
    if args.contact_name:
        cli_hints["contact_name"] = args.contact_name
    if args.name:
        cli_hints["user_name"] = args.name
    if args.task:
        cli_hints["task"] = args.task
    if args.goal:
        cli_hints["goal"] = args.goal
    if args.context:
        cli_hints["context"] = args.context

    # ONE free-form input — user tells us everything in natural language
    raw_input = cli.ask_question(
        "请描述这通电话（号码、对象、目的等，说多少都行）："
    )

    # LLM analyses what's given, asks only what's genuinely missing
    # Use the smarter planner LLM for pre-call work (no time pressure)
    interviewer = Interviewer(agent.planner_llm, agent.memory)
    plan = interviewer.interview(
        raw_input=raw_input,
        cli_hints=cli_hints,
        ask_fn=cli.ask_question,
    )
    cli.show_plan(plan.summary())

    # Generate ONE script, then surface key decision points
    generator = ScriptGenerator(agent.planner_llm, agent.memory)
    cli.show_status("Generating call script...")
    script = generator.generate(plan)
    script = generator.get_decisions(script, ask_fn=cli.ask_question)

    cli.show_script(script.to_display())
    confirm = cli.ask_confirmation("确认开始拨号？[Y/n]")
    if confirm.strip().lower() in {"n", "no"}:
        raise ValueError("Call cancelled by user")

    # Build the request
    phone_number = plan.phone_number or args.number or ""
    if not phone_number:
        raise ValueError("No phone number provided")

    task_prompt = task_prompt_from_plan(plan)
    user_info = build_user_info(args)
    user_info.setdefault("name", plan.user_name)
    user_info.setdefault("company", plan.company)
    for key, value in plan.key_info.items():
        if value:
            user_info[key] = value
    if plan.special_instructions:
        user_info["special_instructions"] = plan.special_instructions

    return CallRequest(
        phone_number=phone_number,
        task_prompt=task_prompt,
        user_info=user_info,
        company=plan.company,
        call_script=script,
        cli=cli,
        interactive=True,
        max_duration_sec=args.max_duration,
    )


def task_prompt_from_plan(plan) -> TaskPrompt:
    context_lines = [f"Tone: {plan.tone}"]
    for key, value in plan.key_info.items():
        context_lines.append(f"{key}: {value}")
    if plan.special_instructions:
        context_lines.append(f"Special instructions: {plan.special_instructions}")

    return render_task_prompt(
        "general",
        task=plan.purpose,
        goal=plan.purpose,
        context="\n".join(context_lines),
    )


def build_standard_request(args: argparse.Namespace) -> CallRequest:
    if not args.number:
        raise ValueError("--number is required unless you use --interactive and answer it there")
    return CallRequest(
        phone_number=args.number,
        task_prompt=build_task_prompt(args),
        user_info=build_user_info(args),
        company=args.company or "",
        interactive=args.interactive,
        max_duration_sec=args.max_duration,
    )


def _required(value: str | None, flag: str) -> str:
    if not value:
        raise ValueError(f"{flag} is required for this template")
    return value


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.interactive:
        # In interactive mode, filter out noisy logs so the user only sees
        # the conversation transcript shown by InteractiveCLI.
        logging.basicConfig(
            level=logging.WARNING,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )
        # Keep call4me logger at INFO but add a filter for noise
        call4me_logger = logging.getLogger("call4me")
        call4me_logger.setLevel(logging.INFO)

        class _QuietFilter(logging.Filter):
            # Pre-call INFO patterns to suppress (e.g. HTTP traffic, dedup details).
            # During the actual call, agent.py raises the level to WARNING so
            # no INFO reaches this filter at all.
            _noise = (
                "HTTP Request:", "HTTP/", "Dedup [",
                "DeprecationWarning",
            )
            def filter(self, record: logging.LogRecord) -> bool:
                if record.levelno == logging.INFO:
                    msg = record.getMessage()
                    return not any(n in msg for n in self._noise)
                return True

        for handler in logging.root.handlers:
            handler.addFilter(_QuietFilter())
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )

    try:
        config = load_config(args.config)
        if args.max_duration:
            config.agent.max_duration_sec = args.max_duration

        agent = Call4MeAgent(config)
        request = build_interactive_request(args, agent) if args.interactive else build_standard_request(args)

        result = agent.run(request)
        try:
            agent.learn_from_result(request, result)
        except Exception as exc:
            logging.warning("Post-call memory extraction failed: %s", exc)
    except (RuntimeError, ValueError) as exc:
        logging.error(str(exc))
        return 2

    # Clear end-of-call status
    cli = request.cli if hasattr(request, 'cli') and request.cli else None
    if cli:
        if result.completed:
            cli.show_banner("CALL COMPLETED")
        else:
            cli.show_banner("CALL ENDED (goal not marked complete)")
        print(f"  Summary: {result.summary}")
        print(f"  Duration: {result.duration_sec}s")
        if result.ivr_steps:
            print(f"  IVR keys pressed: {' → '.join(result.ivr_steps)}")
    else:
        print(result.summary)
    return 0 if result.completed else 1


if __name__ == "__main__":
    raise SystemExit(main())

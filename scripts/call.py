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
from call4me.prompts import render_task_prompt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call4Me phone automation CLI")
    parser.add_argument("--number", required=True, help="Destination phone number")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.yaml"), help="Path to config.yaml")
    parser.add_argument("--template", default="general", choices=["general", "flight_change", "price_inquiry"])
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
    parser.add_argument("--interactive", action="store_true", help="Reserved flag for future live guidance support")
    return parser


def build_task_prompt(args: argparse.Namespace):
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


def _required(value: str | None, flag: str) -> str:
    if not value:
        raise ValueError(f"{flag} is required for this template")
    return value


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = load_config(args.config)
        if args.max_duration:
            config.agent.max_duration_sec = args.max_duration

        request = CallRequest(
            phone_number=args.number,
            task_prompt=build_task_prompt(args),
            user_info=build_user_info(args),
            interactive=args.interactive,
            max_duration_sec=args.max_duration,
        )

        result = Call4MeAgent(config).run(request)
    except (RuntimeError, ValueError) as exc:
        logging.error(str(exc))
        return 2

    print(result.summary)
    return 0 if result.completed else 1


if __name__ == "__main__":
    raise SystemExit(main())

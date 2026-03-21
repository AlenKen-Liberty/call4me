"""Interactive CLI: real-time transcript display + user input during calls.

Layout (simple ANSI, no curses dependency):

  ┌──────────────────────────────────────┐
  │  [00:05] Them: Hello?               │  ← live transcript
  │  [00:06] You:  Hey Jennifer!         │
  │  [00:08] Them: Oh hi David!          │
  │  ...                                 │
  ├──────────────────────────────────────┤
  │  You> _                              │  ← user input area
  └──────────────────────────────────────┘

User commands:
  /say <text>    Override bot's next response with this text
  /inject <text> Add this instruction to the bot's context
  /stop          End the call now
  /script        Show the current script
  <Enter>        (empty) No override, let bot handle it
"""

from __future__ import annotations

import queue
import sys
import threading
from datetime import datetime

# ANSI color codes
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


class UserCommand:
    """A command from the user during an active call."""

    def __init__(self, kind: str, text: str = ""):
        self.kind = kind  # "say", "inject", "stop", "script", "none"
        self.text = text


class InteractiveCLI:
    """Thread-safe CLI for real-time call monitoring and intervention."""

    def __init__(self):
        self._cmd_queue: queue.Queue[UserCommand] = queue.Queue()
        self._input_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._call_active = False
        self._start_time: float = 0

    # ── Display methods (called from agent thread) ────────────────────

    def show_banner(self, text: str) -> None:
        """Show a prominent banner message."""
        print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}")
        print(f"{BOLD}{CYAN}{text}{RESET}")
        print(f"{BOLD}{CYAN}{'=' * 60}{RESET}\n")

    def show_plan(self, plan_text: str) -> None:
        """Display the call plan for user review."""
        print(f"\n{DIM}{plan_text}{RESET}\n")

    def show_script(self, script_display: str) -> None:
        """Display the conversation script."""
        for line in script_display.split("\n"):
            if line.startswith("="):
                print(f"{BOLD}{CYAN}{line}{RESET}")
            elif "IF they say:" in line:
                print(f"  {YELLOW}{line.strip()}{RESET}")
            elif "YOU say:" in line:
                print(f"  {GREEN}{line.strip()}{RESET}")
            elif line.startswith("---"):
                print(f"{DIM}{line}{RESET}")
            else:
                print(line)

    def show_script_options(self, script_displays: list[tuple[int, str, str]]) -> None:
        """Display available script options for user selection."""
        self.show_banner("Script Options")
        for index, title, description in script_displays:
            print(f"{BOLD}{index}. {title}{RESET}")
            if description:
                print(f"   {DIM}{description}{RESET}")
            print("")

    def ask_confirmation(self, prompt: str) -> str:
        """Ask user a yes/no or open question. Blocking."""
        return input(f"{BOLD}{prompt}{RESET} ").strip()

    def ask_question(self, question: str) -> str:
        """Display an LLM question and get user's answer."""
        print(f"\n{CYAN}🤖 {question}{RESET}")
        return input(f"{GREEN}You> {RESET}").strip()

    def show_status(self, text: str) -> None:
        """Show a status message (e.g., 'Dialing...', 'Pre-caching TTS...')."""
        print(f"  {DIM}⏳ {text}{RESET}")

    def show_them(self, text: str, timestamp: str = "") -> None:
        """Display what the other party said."""
        ts = timestamp or datetime.now().strftime("%H:%M:%S")
        print(f"  {DIM}[{ts}]{RESET} {YELLOW}Them:{RESET} {text}")

    def show_us(self, text: str, source: str = "bot") -> None:
        """Display what our side said."""
        ts = datetime.now().strftime("%H:%M:%S")
        tag = "🤖" if source == "bot" else "👤"
        color = GREEN if source == "bot" else BOLD + GREEN
        print(f"  {DIM}[{ts}]{RESET} {color}{tag} You:{RESET} {text}")

    def show_action(self, action: str) -> None:
        """Display a non-speech action (DTMF, HOLD, etc.)."""
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  {DIM}[{ts}] ⚡ {action}{RESET}")

    def show_cache_hit(self, text: str) -> None:
        """Highlight when a cached response was used."""
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  {DIM}[{ts}]{RESET} {GREEN}⚡ You (cached):{RESET} {text}")

    def show_error(self, text: str) -> None:
        print(f"  {RED}❌ {text}{RESET}")

    def show_info(self, text: str) -> None:
        print(f"  {DIM}ℹ️  {text}{RESET}")

    # ── User input during call ────────────────────────────────────────

    def start_input_listener(self) -> None:
        """Start background thread listening for user keyboard input."""
        self._call_active = True
        self._stop.clear()
        self._input_thread = threading.Thread(
            target=self._input_loop, daemon=True
        )
        self._input_thread.start()

    def stop_input_listener(self) -> None:
        self._call_active = False
        self._stop.set()

    def poll_user_command(self) -> UserCommand | None:
        """Non-blocking check for user commands. Called from agent loop."""
        try:
            return self._cmd_queue.get_nowait()
        except queue.Empty:
            return None

    def _input_loop(self) -> None:
        """Background loop reading user input."""
        while not self._stop.is_set():
            try:
                # Use a short timeout approach with select on stdin
                import select
                readable, _, _ = select.select([sys.stdin], [], [], 0.5)
                if not readable:
                    continue

                line = sys.stdin.readline()
                if not line:
                    continue

                line = line.strip()
                if not line:
                    continue

                cmd = self._parse_command(line)
                self._cmd_queue.put(cmd)

                if cmd.kind == "stop":
                    break

            except (EOFError, KeyboardInterrupt):
                self._cmd_queue.put(UserCommand("stop"))
                break
            except Exception:
                continue

    @staticmethod
    def _parse_command(line: str) -> UserCommand:
        """Parse user input into a UserCommand."""
        if line.startswith("/say "):
            return UserCommand("say", line[5:].strip())
        if line.startswith("/inject "):
            return UserCommand("inject", line[8:].strip())
        if line == "/stop":
            return UserCommand("stop")
        if line == "/script":
            return UserCommand("script")

        # Bare text = shorthand for /say
        return UserCommand("say", line)

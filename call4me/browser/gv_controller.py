from __future__ import annotations

import sys
import time
from builtins import input as builtin_input
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from call4me.config import BrowserConfig
from call4me.browser.shared_chromium import ensure_shared_chromium


@dataclass
class GoogleVoiceController:
    config: BrowserConfig
    _crystal: Any | None = None
    _browser_handle: Any | None = None
    _page: Any | None = None

    def connect(self) -> None:
        shared_browser = ensure_shared_chromium(self.config)
        Crystal = self._load_crystal()
        self._crystal = Crystal(
            proxy=self.config.proxy,
            mode="headed",
            auto_upgrade=False,
            timeout_ms=self.config.timeout_ms,
            use_persistent_profile=False,
            profile_root=self.config.chromium_profile_root,
            profile_name=self.config.chromium_profile_name,
            cdp_url=shared_browser.cdp_url,
        )
        self._browser_handle = self._crystal.connect(mode="headed", create_page=False)
        self._page = self._browser_handle.find_page("voice.google.com")
        if self._page is None:
            self._page = self._browser_handle.new_page()
        self._page.set_default_timeout(self.config.timeout_ms)
        self._ensure_ready_page()

    @property
    def page(self) -> Any:
        if self._page is None:
            raise RuntimeError("Google Voice page is not connected")
        return self._page

    def dial(self, phone_number: str) -> bool:
        self._dismiss_overlays()
        dialpad = self._find_dial_input()
        if dialpad is None:
            self._open_calls_view()
            dialpad = self._find_dial_input()
        if dialpad is None:
            return False

        dialpad.click()
        time.sleep(0.2)
        dialpad.fill(phone_number)
        time.sleep(1.0)
        dialpad.press("Enter")
        return True

    def press_key(self, digit: str) -> None:
        self.ensure_keypad_visible()
        key = self._query_first(
            [
                f'button[aria-label="{digit}"]',
                f'button[aria-label*="{digit}"]',
                f'button:has-text("{digit}")',
            ]
        )
        if key is not None:
            key.click()
        else:
            self.page.keyboard.press(digit)

    def hangup(self) -> bool:
        hangup_button = self._query_first(
            [
                '[gv-test-id="in-call-end-call"]',
                'button[aria-label*="End call"]',
                'button[aria-label*="Hang up"]',
            ]
        )
        if hangup_button is None:
            return False
        try:
            hangup_button.click()
        except Exception:
            return False
        return True

    def is_call_active(self) -> bool:
        return self._query_first(
            [
                '[gv-test-id="in-call-end-call"]',
                'button[aria-label*="End call"]',
                'button[aria-label*="Hang up"]',
            ]
        ) is not None

    def get_page_text(self) -> str:
        return self.page.evaluate("() => document.body.innerText")

    def ensure_keypad_visible(self) -> None:
        show_keypad = self._query_first(
            [
                '[gv-test-id="keypad-button"]',
                'button[aria-label*="Show keypad"]',
            ]
        )
        if show_keypad is not None:
            show_keypad.click()
            time.sleep(0.3)

    def close(self) -> None:
        if self._browser_handle is not None:
            try:
                self._browser_handle.close()
            except Exception:
                pass
        self._crystal = None
        self._browser_handle = None
        self._page = None

    def _dismiss_overlays(self) -> None:
        for _ in range(3):
            close_btn = self._query_first(
                [
                    '.cdk-overlay-container button[aria-label*="Close"]',
                    '.cdk-overlay-container button[aria-label*="关闭"]',
                    '.cdk-overlay-container button[aria-label*="Dismiss"]',
                ]
            )
            if close_btn is None:
                break
            try:
                close_btn.click()
                time.sleep(0.3)
            except Exception:
                break

    def _ensure_calls_page(self) -> None:
        if "/calls" in self.page.url:
            return
        self.page.goto(self.config.voice_url, wait_until="domcontentloaded")
        time.sleep(1.0)

    def _ensure_ready_page(self) -> None:
        self._ensure_calls_page()
        if self._find_dial_input() is not None:
            return
        self._open_calls_view()
        if self._find_dial_input() is not None:
            return
        self._wait_for_manual_login()

    def _wait_for_manual_login(self) -> None:
        if not self.config.prompt_for_manual_login:
            raise RuntimeError("Google Voice is open but not ready for calls; manual login is required")
        if not self._can_prompt_for_login():
            raise RuntimeError(
                "Google Voice is open but not ready for calls; "
                "run call4me from a tty so it can wait for manual login"
            )

        for _ in range(3):
            prompt = (
                "\nGoogle Voice browser is open but not ready for calls.\n"
                f"Current page: {self.page.url}\n"
                "Please finish login in the opened browser window, then press Enter here to continue..."
            )
            try:
                self._prompt_for_enter(prompt)
            except (EOFError, KeyboardInterrupt) as exc:
                raise RuntimeError("Cancelled while waiting for Google Voice login") from exc
            self._ensure_calls_page()
            self._open_calls_view()
            if self._find_dial_input() is not None:
                return

        raise RuntimeError("Google Voice is still not ready for calls after manual login")

    def _find_dial_input(self) -> Any | None:
        panel = self._query_first(
            [
                'gv-make-call-panel input[type="text"]',
                'gv-call-sidebar input[type="text"]',
            ]
        )
        if panel is not None:
            return panel
        return self._query_first(['input[placeholder="Enter a name or number"]'])

    def _open_calls_view(self) -> None:
        calls_button = self._query_first(
            [
                '[gv-test-id="sidenav-calls"]',
                'button[aria-label="Calls"]',
                'a[aria-label="Calls"]',
            ]
        )
        if calls_button is not None:
            calls_button.click()
            time.sleep(0.6)

    def _query_first(self, selectors: list[str]) -> Any | None:
        for selector in selectors:
            try:
                node = self.page.query_selector(selector)
            except Exception:
                node = None
            if node is not None:
                return node
        return None

    def _can_prompt_for_login(self) -> bool:
        try:
            return bool(sys.stdin.isatty())
        except Exception:
            return False

    def _prompt_for_enter(self, prompt: str) -> str:
        return builtin_input(prompt)

    def _load_crystal(self):
        crystal_path = Path(self.config.crystal_cdp_path)
        if crystal_path.exists():
            path_value = str(crystal_path)
            if path_value not in sys.path:
                sys.path.insert(0, path_value)
        from crystal_cdp import Crystal  # type: ignore

        return Crystal

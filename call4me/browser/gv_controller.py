from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from call4me.config import BrowserConfig


@dataclass
class GoogleVoiceController:
    config: BrowserConfig
    _playwright: Any | None = None
    _browser: Any | None = None
    _page: Any | None = None

    def connect(self) -> None:
        sync_playwright = self._load_playwright()
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(
            self.config.cdp_url,
            timeout=self.config.timeout_ms,
        )
        self._page = self._find_or_open_voice_page()
        self._page.set_default_timeout(self.config.timeout_ms)

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

        # Press Enter to dial the number we typed — avoids clicking
        # on suggestion buttons like "Call Air Canada" from call history.
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
            # Fallback to pure keyboard press
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
            # The other side may have already hung up
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
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = None
        self._browser = None
        self._page = None

    def _dismiss_overlays(self) -> None:
        """Close any notification overlays that might block interaction."""
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

    def _find_dial_input(self) -> Any | None:
        # Language-agnostic: find the input inside the dial panel custom element
        panel = self._query_first(
            [
                'gv-make-call-panel input[type="text"]',
                'gv-call-sidebar input[type="text"]',
            ]
        )
        if panel is not None:
            return panel
        # Fallback: match by placeholder (English)
        return self._query_first(
            ['input[placeholder="Enter a name or number"]']
        )

    def _find_or_open_voice_page(self) -> Any:
        assert self._browser is not None
        for context in self._browser.contexts:
            for page in context.pages:
                if "voice.google.com" in page.url:
                    if "/calls" not in page.url:
                        page.goto(self.config.voice_url, wait_until="domcontentloaded")
                    return page

        context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(self.config.voice_url, wait_until="domcontentloaded")
        time.sleep(2.0)
        return page

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

    def _load_playwright(self):
        openclaw_path = Path(self.config.openclaw_tool_path)
        if openclaw_path.exists():
            sys.path.insert(0, str(openclaw_path))

        try:
            from patchright.sync_api import sync_playwright  # type: ignore
        except ImportError:
            from playwright.sync_api import sync_playwright  # type: ignore
        return sync_playwright

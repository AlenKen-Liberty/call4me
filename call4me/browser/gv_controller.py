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
        dialpad = self._query_first(['input[placeholder="Enter a name or number"]'])
        if dialpad is None:
            self._open_calls_view()
            dialpad = self._query_first(['input[placeholder="Enter a name or number"]'])
        if dialpad is None:
            return False

        dialpad.click()
        time.sleep(0.2)
        dialpad.fill(phone_number)
        time.sleep(1.0)

        call_button = self._query_first(
            [
                'button[aria-label="Call"]',
                'button[aria-label*="Call"]',
            ]
        )
        if call_button is not None:
            call_button.click()
        else:
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
                'button[aria-label*="End call"]',
                'button[aria-label*="Hang up"]',
                'button[aria-label*="End"]',
            ]
        )
        if hangup_button is None:
            return False
        hangup_button.click()
        return True

    def is_call_active(self) -> bool:
        return self._query_first(
            [
                'button[aria-label*="End call"]',
                'button[aria-label*="Hang up"]',
            ]
        ) is not None

    def get_page_text(self) -> str:
        return self.page.evaluate("() => document.body.innerText")

    def ensure_keypad_visible(self) -> None:
        show_keypad = self._query_first(
            [
                'button[aria-label*="Show keypad"]',
                'button:has-text("Show keypad")',
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
                'button[aria-label="Calls"]',
                '[gv-icon-button="call"]',
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

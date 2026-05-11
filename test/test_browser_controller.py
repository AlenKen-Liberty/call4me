import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from call4me.browser.gv_controller import GoogleVoiceController
from call4me.config import BrowserConfig


def test_google_voice_controller_uses_crystal(monkeypatch):
    config = BrowserConfig(
        crystal_cdp_path="/tmp/fake-crystal",
        proxy="direct",
        use_persistent_profile=True,
        chromium_profile_root="~/.config/chromium",
        chromium_profile_name="Default",
        shared_browser_cdp_url="http://127.0.0.1:9222",
    )
    controller = GoogleVoiceController(config)
    crystal_init = {}

    page = SimpleNamespace(
        url="https://voice.google.com/u/0/calls",
        set_default_timeout=lambda timeout: None,
        goto=lambda url, wait_until=None: None,
        query_selector=lambda selector: object() if "input" in selector else None,
    )
    browser_handle = SimpleNamespace(
        close=lambda: None,
        find_page=lambda pattern: page if pattern == "voice.google.com" else None,
        new_page=lambda: None,
    )

    class FakeCrystal:
        def __init__(self, **kwargs):
            crystal_init.update(kwargs)

        def connect(self, **kwargs):
            assert kwargs == {"mode": "headed", "create_page": False}
            return browser_handle

    monkeypatch.setattr(
        "call4me.browser.gv_controller.ensure_shared_chromium",
        lambda cfg: SimpleNamespace(cdp_url=cfg.shared_browser_cdp_url, reused=True, relaunched=False),
    )
    monkeypatch.setattr(controller, "_load_crystal", lambda: FakeCrystal)

    controller.connect()

    assert crystal_init["use_persistent_profile"] is False
    assert crystal_init["profile_root"] == "~/.config/chromium"
    assert crystal_init["profile_name"] == "Default"
    assert crystal_init["cdp_url"] == "http://127.0.0.1:9222"
    assert controller.page is page
    controller.close()


def test_google_voice_controller_waits_for_manual_login(monkeypatch):
    config = BrowserConfig(
        crystal_cdp_path="/tmp/fake-crystal",
        proxy="direct",
        shared_browser_cdp_url="http://127.0.0.1:9222",
    )
    controller = GoogleVoiceController(config)
    state = {"logged_in": False}

    class FakePage:
        def __init__(self):
            self.url = "https://workspace.google.com/products/voice/"

        def set_default_timeout(self, timeout):
            return None

        def goto(self, url, wait_until=None):
            self.url = url

        def query_selector(self, selector):
            if "input" in selector and state["logged_in"]:
                return object()
            return None

    page = FakePage()
    browser_handle = SimpleNamespace(
        close=lambda: None,
        find_page=lambda pattern: None,
        new_page=lambda: page,
    )

    class FakeCrystal:
        def __init__(self, **kwargs):
            return None

        def connect(self, **kwargs):
            assert kwargs == {"mode": "headed", "create_page": False}
            return browser_handle

    monkeypatch.setattr(
        "call4me.browser.gv_controller.ensure_shared_chromium",
        lambda cfg: SimpleNamespace(cdp_url=cfg.shared_browser_cdp_url, reused=False, relaunched=True),
    )
    monkeypatch.setattr(controller, "_load_crystal", lambda: FakeCrystal)
    monkeypatch.setattr(controller, "_can_prompt_for_login", lambda: True)

    prompts = []

    def fake_prompt(prompt):
        prompts.append(prompt)
        state["logged_in"] = True
        return ""

    monkeypatch.setattr(controller, "_prompt_for_enter", fake_prompt)

    controller.connect()

    assert len(prompts) == 1
    assert "not ready for calls" in prompts[0]
    assert controller.page is page
    controller.close()

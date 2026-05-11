import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from call4me.browser.shared_chromium import _ProcessInfo, ensure_shared_chromium
from call4me.config import BrowserConfig


def test_ensure_shared_chromium_reuses_ready_browser(monkeypatch):
    config = BrowserConfig(shared_browser_cdp_url="http://127.0.0.1:9222")

    monkeypatch.setattr(
        "call4me.browser.shared_chromium._list_chromium_processes",
        lambda profile_root: [
            _ProcessInfo(
                pid=123,
                args=f"chromium --user-data-dir={profile_root} --remote-debugging-port=9222",
            )
        ],
    )
    monkeypatch.setattr(
        "call4me.browser.shared_chromium._find_ready_cdp_url",
        lambda cdp_url: "http://127.0.0.1:9222",
    )

    session = ensure_shared_chromium(config)

    assert session.cdp_url == "http://127.0.0.1:9222"
    assert session.reused is True
    assert session.relaunched is False


def test_ensure_shared_chromium_refuses_forwarded_browser(monkeypatch):
    config = BrowserConfig(shared_browser_cdp_url="http://127.0.0.1:9222")

    monkeypatch.setattr("call4me.browser.shared_chromium._list_chromium_processes", lambda profile_root: [])
    monkeypatch.setattr(
        "call4me.browser.shared_chromium._find_ready_cdp_url",
        lambda cdp_url: "http://[::1]:9222",
    )

    with pytest.raises(RuntimeError, match="refusing to attach"):
        ensure_shared_chromium(config)


def test_ensure_shared_chromium_relaunches_when_debug_port_missing(monkeypatch):
    config = BrowserConfig(shared_browser_cdp_url="127.0.0.1:9222")
    calls: list[str] = []

    monkeypatch.setattr(
        "call4me.browser.shared_chromium._list_chromium_processes",
        lambda profile_root: [_ProcessInfo(pid=321, args="chromium --user-data-dir=/tmp/profile")],
    )
    monkeypatch.setattr("call4me.browser.shared_chromium._debug_browser_ready", lambda cdp_url: False)
    monkeypatch.setattr(
        "call4me.browser.shared_chromium._terminate_processes",
        lambda processes: calls.append("terminate"),
    )
    monkeypatch.setattr(
        "call4me.browser.shared_chromium._launch_chromium",
        lambda cfg, profile_root, port: calls.append(f"launch:{profile_root}:{port}"),
    )
    monkeypatch.setattr(
        "call4me.browser.shared_chromium._wait_for_local_debug_process",
        lambda profile_root, port, timeout_sec: calls.append(f"wait_local:{profile_root}:{port}"),
    )
    monkeypatch.setattr(
        "call4me.browser.shared_chromium._wait_for_debug_browser",
        lambda cdp_url, timeout_sec: calls.append(f"wait:{cdp_url}") or "http://127.0.0.1:9222",
    )

    session = ensure_shared_chromium(config)

    assert session.cdp_url == "http://127.0.0.1:9222"
    assert session.reused is False
    assert session.relaunched is True
    assert calls[0] == "terminate"
    assert calls[1].endswith(":9222")
    assert calls[2].endswith(":9222")
    assert calls[3] == "wait:http://127.0.0.1:9222"

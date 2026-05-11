from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from call4me.config import BrowserConfig


CHROMIUM_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)


@dataclass(slots=True, frozen=True)
class SharedChromiumSession:
    cdp_url: str
    reused: bool
    relaunched: bool


@dataclass(slots=True, frozen=True)
class _ProcessInfo:
    pid: int
    args: str


def ensure_shared_chromium(config: BrowserConfig) -> SharedChromiumSession:
    requested_cdp_url = _normalize_cdp_url(config.shared_browser_cdp_url)
    _, port = _parse_cdp_url(requested_cdp_url)
    profile_root = str(Path(config.chromium_profile_root).expanduser())
    processes = _list_chromium_processes(profile_root)
    local_debug_process = _find_local_debug_process(processes, port)
    ready_cdp_url = _find_ready_cdp_url(requested_cdp_url)
    if ready_cdp_url and local_debug_process is not None:
        return SharedChromiumSession(cdp_url=ready_cdp_url, reused=True, relaunched=False)
    if ready_cdp_url and local_debug_process is None:
        raise RuntimeError(
            f"CDP port {port} is active but no local Chromium process owns it; "
            "refusing to attach to a forwarded or foreign browser session."
        )

    if processes:
        _terminate_processes(processes)

    _launch_chromium(config, profile_root, port)
    _wait_for_local_debug_process(profile_root, port, timeout_sec=config.chromium_startup_timeout_sec)
    ready_cdp_url = _wait_for_debug_browser(requested_cdp_url, timeout_sec=config.chromium_startup_timeout_sec)
    return SharedChromiumSession(cdp_url=ready_cdp_url, reused=False, relaunched=True)


def _normalize_cdp_url(cdp_url: str) -> str:
    value = (cdp_url or "http://127.0.0.1:9222").strip().rstrip("/")
    if "://" not in value:
        value = f"http://{value}"
    return value


def _parse_cdp_url(cdp_url: str) -> tuple[str, int]:
    parsed = urlparse(cdp_url)
    return parsed.hostname or "127.0.0.1", parsed.port or 9222


def _debug_browser_ready(cdp_url: str) -> bool:
    try:
        with urlopen(f"{cdp_url}/json/version", timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return bool(payload.get("webSocketDebuggerUrl"))


def _find_ready_cdp_url(cdp_url: str) -> str | None:
    for candidate in _cdp_candidates(cdp_url):
        if _debug_browser_ready(candidate):
            return candidate
    return None


def _list_chromium_processes(profile_root: str) -> list[_ProcessInfo]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,args="],
        capture_output=True,
        text=True,
        check=True,
    )
    processes: list[_ProcessInfo] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pid_text, _, args = line.partition(" ")
        if not pid_text.isdigit():
            continue
        lowered = args.lower()
        if profile_root not in args:
            continue
        if not any(candidate in lowered for candidate in ("chromium", "chrome")):
            continue
        processes.append(_ProcessInfo(pid=int(pid_text), args=args))
    return processes


def _find_local_debug_process(processes: list[_ProcessInfo], port: int) -> _ProcessInfo | None:
    token = f"--remote-debugging-port={port}"
    for process in processes:
        if "--type=" in process.args:
            continue
        if token in process.args:
            return process
    return None


def _terminate_processes(processes: list[_ProcessInfo], timeout_sec: float = 5.0) -> None:
    pids = sorted({process.pid for process in processes}, reverse=True)
    if not pids:
        return

    for pid in pids:
        _signal_pid(pid, signal.SIGTERM)

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        alive = [pid for pid in pids if _pid_alive(pid)]
        if not alive:
            return
        time.sleep(0.2)

    for pid in pids:
        _signal_pid(pid, signal.SIGKILL)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        alive = [pid for pid in pids if _pid_alive(pid)]
        if not alive:
            return
        time.sleep(0.1)


def _signal_pid(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _launch_chromium(config: BrowserConfig, profile_root: str, port: int) -> None:
    executable = _resolve_chromium_executable(config.chromium_executable)
    env = os.environ.copy()
    if not env.get("DISPLAY"):
        env["DISPLAY"] = config.chromium_display

    command = [
        executable,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile_root}",
        f"--profile-directory={config.chromium_profile_name}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        config.voice_url,
    ]
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )


def _resolve_chromium_executable(override: str) -> str:
    if override:
        return override
    for candidate in CHROMIUM_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("Chromium executable not found")


def _wait_for_debug_browser(cdp_url: str, timeout_sec: float) -> str:
    deadline = time.monotonic() + max(1.0, float(timeout_sec))
    while time.monotonic() < deadline:
        ready = _find_ready_cdp_url(cdp_url)
        if ready:
            return ready
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for Chromium CDP at {cdp_url}")


def _wait_for_local_debug_process(profile_root: str, port: int, timeout_sec: float) -> _ProcessInfo:
    deadline = time.monotonic() + max(1.0, float(timeout_sec))
    while time.monotonic() < deadline:
        process = _find_local_debug_process(_list_chromium_processes(profile_root), port)
        if process is not None:
            return process
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for local Chromium debug process on port {port}")


def _cdp_candidates(cdp_url: str) -> list[str]:
    normalized = _normalize_cdp_url(cdp_url)
    host, port = _parse_cdp_url(normalized)
    candidates = [normalized]
    if host in {"127.0.0.1", "localhost", "::1"}:
        candidates.extend(
            [
                f"http://127.0.0.1:{port}",
                f"http://localhost:{port}",
                f"http://[::1]:{port}",
            ]
        )
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result

"""HID/keyboard-wedge barcode scanner listener (keystroke burst detector).

USB barcode scanners that emulate a keyboard typically type a burst of
characters (often ~5–20 ms apart) and finish with Enter. Slow human typing
is ignored.

On Linux the `keyboard` library usually needs elevated permissions for a
global hook. If that fails, the dashboard's always-focused input field
posts to POST /api/scans/manual instead.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

from events import scan_handler

BURST_GAP_SECONDS = 0.08
COMMIT_IDLE_SECONDS = 0.12
MIN_LENGTH = 3


class HidScannerListener:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hook = None
        self._buffer: list[str] = []
        self._last_key_at = 0.0
        self._timer: threading.Timer | None = None
        self._running = False
        self._error: str | None = None
        self._status = "stopped"
        self._mode = "none"

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "status": self._status,
                "mode": self._mode,
                "error": self._error,
            }

    def start(self) -> dict[str, Any]:
        self.stop()
        try:
            import keyboard  # type: ignore
        except Exception as exc:
            with self._lock:
                self._running = False
                self._status = "fallback"
                self._mode = "dashboard_input"
                self._error = (
                    f"Global keyboard hook unavailable ({exc}). "
                    "Use the dashboard scanner input field, or run with permissions."
                )
            return self.status()

        try:
            self._hook = keyboard.hook(self._on_event)
            with self._lock:
                self._running = True
                self._status = "running"
                self._mode = "global_hook"
                self._error = None
                if sys.platform.startswith("linux"):
                    self._error = (
                        "Linux global hook is active. If scans are missed, "
                        "grant input permissions or use the dashboard input field."
                    )
        except Exception as exc:
            with self._lock:
                self._running = False
                self._status = "fallback"
                self._mode = "dashboard_input"
                self._error = (
                    f"Could not attach a global keyboard hook ({exc}). "
                    "Falling back to the dashboard's focused scanner input."
                )
        return self.status()

    def stop(self) -> dict[str, Any]:
        try:
            import keyboard  # type: ignore

            if self._hook is not None:
                keyboard.unhook(self._hook)
        except Exception:
            pass
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._hook = None
            self._buffer.clear()
            self._running = False
            self._status = "stopped"
            self._mode = "none"
        return self.status()

    def _on_event(self, event: Any) -> None:
        if getattr(event, "event_type", None) != "down":
            return
        name = str(getattr(event, "name", "") or "")
        if not name:
            return

        now = time.monotonic()
        with self._lock:
            if self._buffer and (now - self._last_key_at) > BURST_GAP_SECONDS:
                self._buffer.clear()
            self._last_key_at = now

            if name in {"enter", "return"}:
                payload = "".join(self._buffer)
                self._buffer.clear()
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
                commit = payload
            else:
                char = _key_to_char(name)
                if char is None:
                    return
                self._buffer.append(char)
                if self._timer is not None:
                    self._timer.cancel()
                self._timer = threading.Timer(COMMIT_IDLE_SECONDS, self._commit_idle)
                self._timer.daemon = True
                self._timer.start()
                return

        if len(commit) >= MIN_LENGTH:
            scan_handler.handle_scan(commit, "external_scanner", "HID")

    def _commit_idle(self) -> None:
        with self._lock:
            payload = "".join(self._buffer)
            self._buffer.clear()
            self._timer = None
        if len(payload) >= MIN_LENGTH:
            scan_handler.handle_scan(payload, "external_scanner", "HID")


def _key_to_char(name: str) -> str | None:
    if len(name) == 1 and name.isprintable():
        return name
    if name == "space":
        return " "
    if name.startswith("space"):
        return None
    return None

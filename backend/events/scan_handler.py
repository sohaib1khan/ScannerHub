"""Single place that turns a raw detection into a logged, de-duplicated scan."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from audio import player
from settings import config
from storage import json_log

Listener = Callable[[dict[str, Any]], None]

_lock = threading.Lock()
_last_seen: dict[tuple[str, str], datetime] = {}
_listeners: list[Listener] = []


def add_listener(callback: Listener) -> None:
    with _lock:
        if callback not in _listeners:
            _listeners.append(callback)


def remove_listener(callback: Listener) -> None:
    with _lock:
        if callback in _listeners:
            _listeners.remove(callback)


def handle_scan(
    value: str,
    source: str,
    barcode_format: str = "UNKNOWN",
    *,
    play_sound: bool = True,
) -> dict[str, Any] | None:
    """Record a scan if it is not a duplicate of a recent identical read.

    Returns the stored event, or None if it was suppressed by the dedupe window.
    """
    cleaned = (value or "").strip()
    if not cleaned:
        return None

    now = datetime.now(timezone.utc)
    key = (cleaned, source)
    settings = config.load()
    window = float(settings.get("dedupe_window_seconds", 2.0))

    with _lock:
        previous = _last_seen.get(key)
        if previous is not None and (now - previous).total_seconds() < window:
            return None
        _last_seen[key] = now
        listeners = list(_listeners)

    event = {
        "id": str(uuid.uuid4()),
        "value": cleaned,
        "format": barcode_format,
        "source": source,
        "timestamp": now.isoformat(),
    }
    json_log.append(event)

    if play_sound:
        custom = (settings.get("sounds") or {}).get(source)
        try:
            player.play(player.resolve_sound(source, custom))
        except Exception:
            pass

    for callback in listeners:
        try:
            callback(event)
        except Exception:
            pass

    return event


def reset_dedupe() -> None:
    with _lock:
        _last_seen.clear()

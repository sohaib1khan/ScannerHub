"""Read/write application settings from data/settings.json."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from typing import Any

from paths import settings_path

DEFAULTS: dict[str, Any] = {
    "camera_index": 0,
    "camera_enabled": False,
    "hid_listener_enabled": True,
    "dedupe_window_seconds": 2.0,
    "api_host": "127.0.0.1",
    "api_port": 8765,
    "sounds": {
        "camera": None,
        "external_scanner": None,
    },
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is not None:
            return deepcopy(_cache)

        path = settings_path()
        if not path.exists():
            _cache = deepcopy(DEFAULTS)
            _write_unlocked(_cache)
            return deepcopy(_cache)

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings file is not an object")
            _cache = _merge(DEFAULTS, raw)
        except (OSError, json.JSONDecodeError, ValueError):
            _cache = deepcopy(DEFAULTS)
            _write_unlocked(_cache)
        return deepcopy(_cache)


def save(updates: dict[str, Any]) -> dict[str, Any]:
    global _cache
    with _lock:
        current = deepcopy(_cache) if _cache is not None else deepcopy(load_unlocked())
        current = _merge(current, updates)
        _cache = current
        _write_unlocked(current)
        return deepcopy(current)


def load_unlocked() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return deepcopy(DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return deepcopy(DEFAULTS)
        return _merge(DEFAULTS, raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return deepcopy(DEFAULTS)


def _write_unlocked(data: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None

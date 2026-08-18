"""Read/write application settings from data/settings.json."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from typing import Any

from paths import project_root, settings_path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

DEFAULTS: dict[str, Any] = {
    "camera_index": 0,
    "camera_enabled": False,
    "hid_listener_enabled": True,
    "dedupe_window_seconds": 2.0,
    "api_host": DEFAULT_HOST,
    "api_port": DEFAULT_PORT,
    "sounds": {
        "camera": None,
        "external_scanner": None,
    },
}


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(project_root() / ".env")


_load_dotenv()

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


def bind_host(cli_host: str | None = None) -> str:
    """CLI flag, then SCANNERHUB_HOST, then settings.json, then default."""
    if cli_host:
        return str(cli_host)
    env = os.environ.get("SCANNERHUB_HOST", "").strip()
    if env:
        return env
    return str(load().get("api_host", DEFAULT_HOST))


def bind_port(cli_port: int | None = None) -> int:
    """CLI flag, then SCANNERHUB_PORT, then settings.json, then default."""
    if cli_port is not None:
        return int(cli_port)
    env = os.environ.get("SCANNERHUB_PORT", "").strip()
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return int(load().get("api_port", DEFAULT_PORT))

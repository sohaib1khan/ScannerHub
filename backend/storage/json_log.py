"""Append-only JSON scan history stored in data/scan_history.json."""

from __future__ import annotations

import json
import threading
from typing import Any

from paths import scan_history_path

_lock = threading.Lock()

EMPTY: dict[str, Any] = {"scans": []}


def _read_unlocked() -> dict[str, Any]:
    path = scan_history_path()
    if not path.exists():
        return {"scans": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("scans"), list):
            return {"scans": []}
        return raw
    except (OSError, json.JSONDecodeError, ValueError):
        return {"scans": []}


def _write_unlocked(data: dict[str, Any]) -> None:
    path = scan_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_all() -> list[dict[str, Any]]:
    with _lock:
        return list(_read_unlocked()["scans"])


def append(entry: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        data = _read_unlocked()
        data["scans"].append(entry)
        _write_unlocked(data)
        return entry


def clear() -> None:
    with _lock:
        _write_unlocked({"scans": []})


def stats() -> dict[str, Any]:
    scans = read_all()
    by_source: dict[str, int] = {}
    for item in scans:
        source = str(item.get("source", "unknown"))
        by_source[source] = by_source.get(source, 0) + 1
    return {
        "total": len(scans),
        "by_source": by_source,
        "latest": scans[-1] if scans else None,
    }

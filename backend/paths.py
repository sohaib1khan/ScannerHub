"""Resolve project, data, and bundled-asset paths for dev and PyInstaller."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Writable project/install root (next to the exe when packaged)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_root() -> Path:
    """Read-only asset root (PyInstaller extract dir, or project root in dev)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return project_root()


def backend_dir() -> Path:
    if is_frozen():
        return bundle_root()
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    override = os.environ.get("SCANNERHUB_DATA_DIR")
    path = Path(override) if override else project_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sounds_dir() -> Path:
    path = data_dir() / "sounds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def frontend_dir() -> Path:
    bundled = bundle_root() / "frontend"
    if bundled.exists():
        return bundled
    return project_root() / "frontend"


def scan_history_path() -> Path:
    return data_dir() / "scan_history.json"


def settings_path() -> Path:
    return data_dir() / "settings.json"

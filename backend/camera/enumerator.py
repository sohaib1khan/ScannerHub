"""OS-agnostic camera listing with friendly device names when available."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    import cv2
except ImportError:  # pragma: no cover - exercised in environments without OpenCV
    cv2 = None


def list_cameras(max_index: int = 10) -> list[dict[str, Any]]:
    """Return cameras that can actually be opened, with a friendly name per OS."""
    names = _friendly_names()
    devices: list[dict[str, Any]] = []
    indices = list(names.keys()) if names else list(range(max_index))

    for index in indices:
        if not _can_open(index):
            continue
        name = names.get(index) or f"Camera {index}"
        devices.append(
            {
                "index": index,
                "name": name,
                "label": f"{name} ({index})",
            }
        )
    return devices


def _can_open(index: int) -> bool:
    if cv2 is None:
        return False
    backend = _opencv_backend()
    cap = cv2.VideoCapture(index, backend) if backend is not None else cv2.VideoCapture(index)
    try:
        if not cap.isOpened():
            return False
        ok, frame = cap.read()
        return bool(ok and frame is not None)
    except Exception:
        return False
    finally:
        cap.release()


def _opencv_backend() -> int | None:
    if cv2 is None:
        return None
    if sys.platform.startswith("win"):
        return int(getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY))
    if sys.platform == "darwin":
        return int(getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY))
    return int(getattr(cv2, "CAP_V4L2", cv2.CAP_ANY))


def _friendly_names() -> dict[int, str]:
    if sys.platform.startswith("win"):
        return _windows_names()
    if sys.platform.startswith("linux"):
        return _linux_names()
    return {}


def _windows_names() -> dict[int, str]:
    try:
        from pygrabber.dshow_graph import FilterGraph  # type: ignore

        devices = FilterGraph().get_input_devices()
        return {index: str(name) for index, name in enumerate(devices)}
    except Exception:
        return {}


def _linux_names() -> dict[int, str]:
    names: dict[int, str] = {}
    base = Path("/sys/class/video4linux")
    if not base.exists():
        return names
    for node in sorted(base.glob("video*")):
        try:
            index = int(node.name.replace("video", ""))
        except ValueError:
            continue
        name_file = node / "name"
        if name_file.exists():
            label = name_file.read_text(encoding="utf-8", errors="replace").strip()
            if label:
                names[index] = label
    return names

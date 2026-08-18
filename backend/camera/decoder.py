"""Thin wrapper around pyzbar barcode/QR decoding."""

from __future__ import annotations

from typing import Any

import numpy as np

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
except Exception:  # pragma: no cover - missing libzbar or pyzbar
    pyzbar_decode = None


def decode_jpeg(data: bytes) -> list[dict[str, Any]]:
    """Decode barcodes from a JPEG/PNG byte buffer uploaded by the dashboard."""
    if not data:
        return []
    try:
        import cv2
    except Exception:
        return []
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return []
    return decode_frame(frame)


def decode_frame(frame: np.ndarray) -> list[dict[str, Any]]:
    """Return unique barcode payloads found in a BGR or grayscale frame."""
    if pyzbar_decode is None or frame is None:
        return []

    try:
        results = pyzbar_decode(frame)
    except Exception:
        return []

    seen: set[tuple[str, str]] = set()
    decoded: list[dict[str, Any]] = []
    for item in results:
        try:
            value = item.data.decode("utf-8", errors="replace").strip()
        except Exception:
            continue
        if not value:
            continue
        fmt = getattr(item.type, "name", None) or str(item.type)
        key = (value, fmt)
        if key in seen:
            continue
        seen.add(key)
        decoded.append({"value": value, "format": fmt})
    return decoded

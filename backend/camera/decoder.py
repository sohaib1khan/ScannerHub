"""Decode barcodes from camera frames.

Uses native zxing-cpp (same engine as da1loks/barcode-scanner) with crops and
OpenCV variants so printed labels are more likely to read than a single raw
frame. pyzbar remains an optional fallback.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

try:
    import zxingcpp
except Exception:  # pragma: no cover - optional native decoder
    zxingcpp = None

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
except Exception:  # pragma: no cover - missing libzbar or pyzbar
    pyzbar_decode = None

_log = logging.getLogger("uvicorn.error")
_last_save = 0.0
_frame_count = 0


def engine_status() -> dict[str, Any]:
    return {
        "zxingcpp": zxingcpp is not None,
        "pyzbar": pyzbar_decode is not None,
    }


def decode_jpeg(data: bytes) -> list[dict[str, Any]]:
    """Decode barcodes from a JPEG/PNG byte buffer uploaded by the dashboard."""
    found, _info = decode_jpeg_info(data)
    return found


def decode_jpeg_info(data: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    global _frame_count
    info: dict[str, Any] = {
        **engine_status(),
        "bytes": len(data or b""),
        "width": 0,
        "height": 0,
        "mean": 0.0,
        "std": 0.0,
        "hits": 0,
        "dead": False,
    }
    if not data:
        info["error"] = "empty"
        return [], info
    try:
        import cv2
    except Exception:
        info["error"] = "opencv-missing"
        return [], info
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        info["error"] = "not-an-image"
        return [], info
    info["width"] = int(frame.shape[1])
    info["height"] = int(frame.shape[0])
    info["mean"] = float(round(float(frame.mean()), 1))
    h, w = frame.shape[:2]
    core = frame[int(h * 0.2) : int(h * 0.8), int(w * 0.1) : int(w * 0.9)]
    sample = core if core.size else frame
    info["std"] = float(round(float(sample.std()), 1))
    gray = _as_gray(sample)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var()) if gray.size else 0.0
    hist = np.histogram(gray, bins=16, range=(0, 256))[0].astype(np.float64)
    total = float(hist.sum()) or 1.0
    parts = np.sort(hist / total)
    two_tone = bool(parts[-1] + parts[-2] > 0.92)
    info["dead"] = bool(info["std"] < 8.0 or (two_tone and sharpness < 40.0))
    _maybe_save_last_frame(data, info)
    _frame_count += 1
    if info["dead"]:
        if _frame_count == 1 or _frame_count % 25 == 0:
            _log.warning(
                "dead camera still %s (%sx%s mean=%s std=%s bytes=%s) — not a real picture",
                _frame_count,
                info["width"],
                info["height"],
                info["mean"],
                info["std"],
                info["bytes"],
            )
        return [], info
    found = decode_frame(frame)
    info["hits"] = len(found)
    if found:
        _log.info(
            "decoded %s from %sx%s mean=%s",
            found[0]["value"],
            info["width"],
            info["height"],
            info["mean"],
        )
    elif _frame_count == 1 or _frame_count % 25 == 0:
        _log.info(
            "no barcode in frame %s (%sx%s mean=%s std=%s zxing=%s bytes=%s)",
            _frame_count,
            info["width"],
            info["height"],
            info["mean"],
            info["std"],
            info["zxingcpp"],
            info["bytes"],
        )
    return found, info


def decode_frame(frame: np.ndarray) -> list[dict[str, Any]]:
    """Return unique barcode payloads found in a BGR or grayscale frame."""
    if frame is None:
        return []

    found = _decode_with_zxing(frame)
    if found:
        return found
    return _decode_with_pyzbar(frame)


def _maybe_save_last_frame(data: bytes, info: dict[str, Any]) -> None:
    global _last_save
    now = time.monotonic()
    if now - _last_save < 2.0:
        return
    _last_save = now
    try:
        from paths import data_dir

        path = data_dir() / "last_camera_frame.jpg"
        path.write_bytes(data)
        info["saved"] = str(path)
    except Exception:
        pass


def _as_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame
    try:
        import cv2

        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    except Exception:
        return frame[:, :, 0]


def _candidate_images(frame: np.ndarray) -> list[np.ndarray]:
    """Color, gray, and print-oriented variants: brighten, CLAHE, crops, upscale."""
    try:
        import cv2
    except Exception:
        return [frame]

    gray = _as_gray(frame)
    h, w = gray.shape[:2]
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8)).apply(gray)
    bright = cv2.convertScaleAbs(gray, alpha=2.2, beta=36)
    gamma = cv2.LUT(gray, np.array([((i / 255.0) ** 0.55) * 255 for i in range(256)]).astype("uint8"))
    y0, y1 = int(h * 0.12), int(h * 0.88)
    x0, x1 = int(w * 0.08), int(w * 0.92)
    center = gray[y0:y1, x0:x1]
    center_bright = bright[y0:y1, x0:x1]
    band = bright[int(h * 0.30) : int(h * 0.70), int(w * 0.04) : int(w * 0.96)]
    sharp = cv2.filter2D(bright, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32))
    variants = [
        frame,
        gray,
        clahe,
        bright,
        gamma,
        sharp,
        center,
        cv2.resize(center_bright, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC),
        cv2.resize(center_bright, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC),
        cv2.resize(band, None, fx=2.4, fy=2.4, interpolation=cv2.INTER_CUBIC),
        cv2.resize(gray, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC),
        cv2.bitwise_not(bright),
    ]
    up_center = cv2.resize(center_bright, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    variants.append(
        cv2.adaptiveThreshold(
            up_center,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            5,
        )
    )
    _, otsu = cv2.threshold(bright, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(otsu)
    return variants


def _format_name(result: Any) -> str:
    fmt = getattr(result, "format", None)
    if fmt is None:
        return "UNKNOWN"
    name = getattr(fmt, "name", None)
    if name:
        return str(name)
    text = str(fmt)
    if "." in text:
        return text.rsplit(".", 1)[-1]
    return text or "UNKNOWN"


def _collect(results: Any, seen: set[tuple[str, str]], decoded: list[dict[str, Any]]) -> bool:
    for item in results or []:
        value = str(getattr(item, "text", "") or getattr(item, "data", "") or "").strip()
        if not value and hasattr(item, "data"):
            try:
                value = item.data.decode("utf-8", errors="replace").strip()
            except Exception:
                value = ""
        if not value:
            continue
        fmt = _format_name(item)
        if hasattr(item, "type") and (fmt == "UNKNOWN" or fmt == str(item)):
            fmt = getattr(item.type, "name", None) or str(item.type)
        key = (value, fmt)
        if key in seen:
            continue
        seen.add(key)
        decoded.append({"value": value, "format": fmt})
    return bool(decoded)


def _decode_with_zxing(frame: np.ndarray) -> list[dict[str, Any]]:
    if zxingcpp is None:
        return []
    seen: set[tuple[str, str]] = set()
    decoded: list[dict[str, Any]] = []
    binarizers = (
        zxingcpp.Binarizer.LocalAverage,
        zxingcpp.Binarizer.GlobalHistogram,
    )
    for image in _candidate_images(frame):
        if image is None or getattr(image, "size", 0) < 64:
            continue
        if min(image.shape[:2]) < 12:
            continue
        contiguous = np.ascontiguousarray(image)
        for binarizer in binarizers:
            try:
                results = zxingcpp.read_barcodes(contiguous, binarizer=binarizer)
            except Exception:
                continue
            if _collect(results, seen, decoded):
                return decoded
    return decoded


def _decode_with_pyzbar(frame: np.ndarray) -> list[dict[str, Any]]:
    if pyzbar_decode is None:
        return []
    seen: set[tuple[str, str]] = set()
    decoded: list[dict[str, Any]] = []
    for image in _candidate_images(frame):
        try:
            results = pyzbar_decode(image)
        except Exception:
            continue
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
        if decoded:
            break
    return decoded

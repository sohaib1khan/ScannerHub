"""Decode barcodes from camera frames.

Uses native zxing-cpp (same engine as da1loks/barcode-scanner) with crops and
OpenCV variants so printed labels are more likely to read than a single raw
frame. pyzbar remains an optional fallback.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
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


def _format_key(fmt: str) -> str:
    return str(fmt or "").upper().replace(" ", "").replace("_", "").replace("-", "")


def _is_matrix(fmt: str) -> bool:
    key = _format_key(fmt)
    return any(token in key for token in ("QR", "DATAMATRIX", "PDF417", "AZTEC"))


def _is_checksummed(fmt: str) -> bool:
    key = _format_key(fmt)
    if _is_matrix(fmt):
        return True
    return any(token in key for token in ("CODE128", "128", "EAN", "UPC", "CODE93", "93"))


def _trusted_formats() -> Any:
    if zxingcpp is None:
        return None
    names = [
        "QRCode",
        "DataMatrix",
        "PDF417",
        "Aztec",
        "Code128",
        "Code39",
        "Code93",
        "EAN13",
        "EAN8",
        "UPCA",
        "UPCE",
        "ITF14",
    ]
    formats = [getattr(zxingcpp.BarcodeFormat, name) for name in names if hasattr(zxingcpp.BarcodeFormat, name)]
    return zxingcpp.BarcodeFormats(formats)


def _item_is_valid(item: Any) -> bool:
    if getattr(item, "valid", True) is False:
        return False
    err = getattr(item, "error", None)
    if err is None or err == "":
        return True
    name = str(getattr(err, "name", err) or "").upper()
    return name in {"", "NONE", "0"}


def _plausible_value(value: str, fmt: str) -> bool:
    if not value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return False
    if value.count(":") == 5:
        parts = value.split(":")
        if all(len(part) == 2 for part in parts):
            return bool(re.fullmatch(r"[0-9A-Fa-f]{12}", "".join(parts)))
    compact_hex = re.sub(r"[\s:-]", "", value)
    if "-" in value and re.fullmatch(r"[0-9A-Fa-f-]+", value) and len(compact_hex) == 12:
        return bool(re.fullmatch(r"[0-9A-Fa-f]{12}", compact_hex))
    key = _format_key(fmt)
    if _is_matrix(fmt):
        return len(value) >= 1
    if "EAN13" in key:
        return value.isdigit() and len(value) == 13
    if "EAN8" in key:
        return value.isdigit() and len(value) == 8
    if "UPCA" in key:
        return value.isdigit() and len(value) in {11, 12}
    if "UPCE" in key:
        return value.isdigit() and len(value) in {6, 7, 8}
    if "128" in key:
        return 4 <= len(value) <= 80
    if "39" in key or "93" in key:
        return 6 <= len(value) <= 64
    if "ITF" in key:
        return value.isdigit() and len(value) in {8, 12, 14, 16}
    return len(value) >= 6


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 2:
        return 99
    prev = list(range(len(right) + 1))
    for i, a in enumerate(left, start=1):
        curr = [i]
        for j, b in enumerate(right, start=1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = curr
    return prev[-1]


def _pick_consensus(votes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for value, rec in votes.items():
        fmt = str(rec["format"])
        conservative = int(rec["conservative"])
        count = int(rec["count"])
        if _is_matrix(fmt) or (_is_checksummed(fmt) and conservative >= 1) or conservative >= 2:
            confidence = "high"
        elif count >= 2 or conservative >= 1:
            confidence = "confirm"
        else:
            continue
        ranked.append(
            {
                "value": value,
                "format": fmt,
                "confidence": confidence,
                "votes": count,
            }
        )
    if not ranked:
        return []
    ranked.sort(
        key=lambda item: (
            item["confidence"] == "high",
            _is_matrix(item["format"]),
            _is_checksummed(item["format"]),
            item["votes"],
            len(item["value"]),
        ),
        reverse=True,
    )
    highs = [item for item in ranked if item["confidence"] == "high"]
    unique_high = []
    for item in highs:
        if all(item["value"] != other["value"] for other in unique_high):
            unique_high.append(item)
    if len(unique_high) >= 2:
        first, second = unique_high[0], unique_high[1]
        if first["value"] in second["value"] or second["value"] in first["value"]:
            return [first if len(first["value"]) >= len(second["value"]) else second]
        if _edit_distance(first["value"], second["value"]) <= 2:
            return []
        return unique_high[:2]
    return ranked[:1]


def _decode_with_zxing(frame: np.ndarray) -> list[dict[str, Any]]:
    if zxingcpp is None:
        return []
    votes: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "conservative": 0, "format": "UNKNOWN"}
    )
    formats = _trusted_formats()
    binarizers = (
        zxingcpp.Binarizer.LocalAverage,
        zxingcpp.Binarizer.GlobalHistogram,
    )
    for index, image in enumerate(_candidate_images(frame)):
        if image is None or getattr(image, "size", 0) < 64:
            continue
        if min(image.shape[:2]) < 12:
            continue
        contiguous = np.ascontiguousarray(image)
        conservative = index < 7
        for binarizer in binarizers:
            try:
                results = zxingcpp.read_barcodes(
                    contiguous,
                    formats=formats,
                    binarizer=binarizer,
                    return_errors=False,
                )
            except Exception:
                continue
            for item in results or []:
                if not _item_is_valid(item):
                    continue
                value = str(getattr(item, "text", "") or "").strip()
                fmt = _format_name(item)
                if not value or not _plausible_value(value, fmt):
                    continue
                rec = votes[value]
                rec["count"] += 1
                rec["format"] = fmt
                if conservative:
                    rec["conservative"] += 1
    return _pick_consensus(votes)


def _decode_with_pyzbar(frame: np.ndarray) -> list[dict[str, Any]]:
    if pyzbar_decode is None:
        return []
    seen: set[tuple[str, str]] = set()
    decoded: list[dict[str, Any]] = []
    for image in _candidate_images(frame)[:7]:
        try:
            results = pyzbar_decode(image)
        except Exception:
            continue
        for item in results:
            try:
                value = item.data.decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            fmt = getattr(item.type, "name", None) or str(item.type)
            if not value or not _plausible_value(value, fmt):
                continue
            key = (value, fmt)
            if key in seen:
                continue
            seen.add(key)
            decoded.append({"value": value, "format": fmt, "confidence": "high", "votes": 1})
        if decoded:
            break
    return decoded

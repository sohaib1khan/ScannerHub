from __future__ import annotations

import cv2
import numpy as np
import pytest

zxingcpp = pytest.importorskip("zxingcpp")

from camera.decoder import decode_frame, decode_jpeg


def _code128_bgr(text: str = "1234567890") -> np.ndarray:
    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.Code128)
    image = zxingcpp.write_barcode_to_image(barcode, scale=3)
    gray = np.array(image)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def test_zxingcpp_reads_generated_code128():
    frame = _code128_bgr()
    found = decode_frame(frame)
    assert found
    assert found[0]["value"] == "1234567890"
    assert "128" in found[0]["format"]


def test_zxingcpp_reads_jpeg_roundtrip():
    frame = _code128_bgr("SCANNERHUB")
    ok, jpeg = cv2.imencode(".jpg", frame)
    assert ok
    found = decode_jpeg(jpeg.tobytes())
    assert found
    assert found[0]["value"] == "SCANNERHUB"


def test_zxingcpp_reads_small_code128_in_scene():
    code = _code128_bgr("PKG12345")
    small = cv2.resize(code, (160, 60), interpolation=cv2.INTER_AREA)
    scene = np.full((720, 1280, 3), 170, dtype=np.uint8)
    y, x = 330, 560
    scene[y : y + 60, x : x + 160] = small
    found = decode_frame(scene)
    assert found
    assert found[0]["value"] == "PKG12345"


def test_zxingcpp_reads_dark_code128():
    frame = _code128_bgr("DARKCODE")
    dark = (frame.astype(np.float32) * 0.28).astype(np.uint8)
    found = decode_frame(dark)
    assert found
    assert found[0]["value"] == "DARKCODE"

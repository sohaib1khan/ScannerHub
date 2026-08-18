"""Background OpenCV capture loop that feeds decoded barcodes to the scan handler."""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from camera import decoder, enumerator
from events import scan_handler

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


class CameraService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._index: int | None = None
        self._running = False
        self._last_jpeg: bytes | None = None
        self._last_error: str | None = None
        self._status = "stopped"
        self._preview_window = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "index": self._index,
                "status": self._status,
                "error": self._last_error,
                "has_preview": self._last_jpeg is not None,
            }

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._last_jpeg

    def start(self, index: int, preview_window: bool = False) -> dict[str, Any]:
        self.stop()
        with self._lock:
            self._index = index
            self._preview_window = preview_window
            self._last_error = None
            self._status = "starting"
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="camera-capture", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.5)
        with self._lock:
            self._running = False
            self._thread = None
            self._status = "stopped"
            self._last_jpeg = None
        if self._preview_window and cv2 is not None:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        return self.status()

    def _run(self) -> None:
        if cv2 is None:
            with self._lock:
                self._running = False
                self._status = "error"
                self._last_error = "OpenCV is not installed"
            return

        index = self._index
        if index is None:
            with self._lock:
                self._status = "error"
                self._last_error = "No camera selected"
            return

        backend = enumerator._opencv_backend()
        cap = cv2.VideoCapture(index, backend) if backend is not None else cv2.VideoCapture(index)
        if not cap.isOpened():
            with self._lock:
                self._running = False
                self._status = "error"
                self._last_error = f"Could not open camera {index}"
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        with self._lock:
            self._running = True
            self._status = "running"
            self._last_error = None

        consecutive_failures = 0
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures >= 15:
                        with self._lock:
                            self._status = "disconnected"
                            self._last_error = "Camera disconnected mid-session"
                        time.sleep(0.4)
                    else:
                        time.sleep(0.05)
                    continue

                consecutive_failures = 0
                with self._lock:
                    if self._status != "running":
                        self._status = "running"
                        self._last_error = None

                self._store_jpeg(frame)
                for item in decoder.decode_frame(frame):
                    scan_handler.handle_scan(item["value"], "camera", item["format"])

                if self._preview_window:
                    cv2.imshow("ScannerHub camera", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                else:
                    time.sleep(0.02)
        finally:
            cap.release()
            if self._preview_window:
                try:
                    cv2.destroyAllWindows()
                except Exception:
                    pass
            with self._lock:
                self._running = False
                if self._status not in {"error", "disconnected"}:
                    self._status = "stopped"

    def _store_jpeg(self, frame: np.ndarray) -> None:
        if cv2 is None:
            return
        height, width = frame.shape[:2]
        max_width = 960
        if width > max_width:
            scale = max_width / float(width)
            frame = cv2.resize(frame, (max_width, int(height * scale)))
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        if not ok:
            return
        with self._lock:
            self._last_jpeg = encoded.tobytes()

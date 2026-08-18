"""REST endpoints and a WebSocket feed for live scans."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from audio import player
from camera import decoder, enumerator
from events import scan_handler
from paths import sounds_dir
from settings import config
from storage import json_log

ALLOWED_SOUND_TYPES = {".wav", ".mp3", ".ogg"}


class CameraSelectBody(BaseModel):
    index: int = Field(..., ge=0)
    start: bool = True


class SettingsBody(BaseModel):
    camera_index: int | None = None
    camera_enabled: bool | None = None
    hid_listener_enabled: bool | None = None
    dedupe_window_seconds: float | None = Field(default=None, ge=0.2, le=30)
    sounds: dict[str, str | None] | None = None


class ManualScanBody(BaseModel):
    value: str
    source: str = "external_scanner"
    format: str = "MANUAL"


class ScanHub:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[WebSocket] = set()

    def publish(self, event: dict[str, Any]) -> None:
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(event), self.loop)

    async def register(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    async def unregister(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, event: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        payload = json.dumps(event)
        for client in list(self.clients):
            try:
                await client.send_text(payload)
            except Exception:
                dead.append(client)
        for client in dead:
            self.clients.discard(client)


def attach(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "scannerhub",
            "version": getattr(app.state, "version", "0.1.0"),
            "decoder": decoder.engine_status(),
        }

    @router.get("/status")
    def status() -> dict[str, Any]:
        return {
            "health": "ok",
            "camera": app.state.camera.status(),
            "scanner": app.state.hid.status(),
            "stats": json_log.stats(),
            "decoder": decoder.engine_status(),
        }

    @router.get("/cameras")
    def cameras() -> dict[str, Any]:
        return {"cameras": enumerator.list_cameras()}

    @router.post("/camera/select")
    def camera_select(body: CameraSelectBody) -> dict[str, Any]:
        config.save({"camera_index": body.index, "camera_enabled": body.start})
        if body.start:
            result = app.state.camera.start(body.index)
        else:
            result = app.state.camera.stop()
        return {"camera": result, "settings": config.load()}

    @router.post("/camera/start")
    def camera_start() -> dict[str, Any]:
        settings = config.load()
        result = app.state.camera.start(int(settings.get("camera_index", 0)))
        config.save({"camera_enabled": True})
        return {"camera": result}

    @router.post("/camera/stop")
    def camera_stop() -> dict[str, Any]:
        result = app.state.camera.stop()
        config.save({"camera_enabled": False})
        return {"camera": result}

    @router.post("/camera/frame")
    async def camera_frame(file: UploadFile = File(...)) -> dict[str, Any]:
        """Decode a JPEG frame from the browser camera and log any barcodes."""
        payload = await file.read()
        found, debug = decoder.decode_jpeg_info(payload)
        scans = []
        for item in found:
            if item.get("confidence") == "confirm":
                continue
            event = scan_handler.handle_scan(item["value"], "camera", item["format"])
            if event is not None:
                scans.append(event)
        return {"ok": True, "scans": scans, "hits": found, "debug": debug}

    @router.get("/camera/preview")
    async def camera_preview() -> StreamingResponse:
        async def frames() -> AsyncIterator[bytes]:
            while True:
                jpeg = app.state.camera.latest_jpeg()
                if jpeg:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                    )
                await asyncio.sleep(0.05)

        return StreamingResponse(
            frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @router.get("/scans")
    def scans(limit: int = 200) -> dict[str, Any]:
        items = json_log.read_all()
        if limit > 0:
            items = items[-limit:]
        items.reverse()
        return {"scans": items, "stats": json_log.stats()}

    @router.delete("/scans")
    def clear_scans() -> dict[str, Any]:
        json_log.clear()
        scan_handler.reset_dedupe()
        return {"ok": True, "stats": json_log.stats()}

    @router.post("/scans/manual")
    def manual_scan(body: ManualScanBody) -> JSONResponse:
        source = body.source if body.source in {"camera", "external_scanner"} else "external_scanner"
        event = scan_handler.handle_scan(body.value, source, body.format)
        if event is None:
            return JSONResponse({"ok": False, "suppressed": True}, status_code=200)
        return JSONResponse({"ok": True, "scan": event})

    @router.get("/settings")
    def get_settings() -> dict[str, Any]:
        return config.load()

    @router.post("/settings")
    def post_settings(body: SettingsBody) -> dict[str, Any]:
        payload = body.model_dump(exclude_none=True)
        updated = config.save(payload)
        if "hid_listener_enabled" in payload:
            if updated["hid_listener_enabled"]:
                app.state.hid.start()
            else:
                app.state.hid.stop()
        if payload.get("camera_enabled") is False:
            app.state.camera.stop()
        return {"settings": updated, "camera": app.state.camera.status(), "scanner": app.state.hid.status()}

    @router.get("/settings/sounds")
    def list_sounds() -> dict[str, Any]:
        settings = config.load()
        selected = settings.get("sounds") or {}
        return {
            "sounds": player.list_sounds(),
            "selected": {
                "camera": selected.get("camera") or player.default_id("camera"),
                "external_scanner": selected.get("external_scanner") or player.default_id("external_scanner"),
            },
            "folder": str(sounds_dir()),
        }

    @router.get("/sounds/{filename}")
    def get_sound_file(filename: str) -> FileResponse:
        name = Path(filename).name
        if not player.is_safe_sound_name(name) or Path(name).suffix.lower() not in ALLOWED_SOUND_TYPES:
            raise HTTPException(status_code=404, detail="Sound not found")
        path = (sounds_dir() / name).resolve()
        if path.parent != sounds_dir().resolve() or not path.is_file():
            raise HTTPException(status_code=404, detail="Sound not found")
        media = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg"}[path.suffix.lower()]
        return FileResponse(path, media_type=media, filename=name)

    @router.post("/settings/sound")
    async def upload_sound(source: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
        if source not in {"camera", "external_scanner"}:
            raise HTTPException(status_code=400, detail="source must be camera or external_scanner")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_SOUND_TYPES:
            raise HTTPException(status_code=400, detail="Sound file must be .wav, .mp3, or .ogg")
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(file.filename or "sound").stem).strip("-") or "sound"
        dest = sounds_dir() / f"user_{source}_{stem}{suffix}"
        dest.write_bytes(await file.read())
        return {"ok": True, "id": dest.stem, "path": str(dest), "sounds": player.list_sounds()}

    @router.post("/settings/sound/test")
    def test_sound(source: str = "camera", sound: str | None = None) -> dict[str, Any]:
        if source not in {"camera", "external_scanner"}:
            raise HTTPException(status_code=400, detail="source must be camera or external_scanner")
        settings = config.load()
        selected = sound or (settings.get("sounds") or {}).get(source)
        player.play(player.resolve_sound(source, selected))
        return {"ok": True, "source": source, "sound": selected}

    @router.websocket("/ws/scans")
    async def ws_scans(ws: WebSocket) -> None:
        await app.state.hub.register(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await app.state.hub.unregister(ws)

    app.include_router(router, prefix="/api")
    app.include_router(router)

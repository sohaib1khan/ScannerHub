"""ScannerHub entry point — starts the API and wires hardware services."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles as StarletteStaticFiles


class NoCacheStaticFiles(StarletteStaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

from api.routes import ScanHub, attach
from audio import player
from camera import decoder
from camera.capture import CameraService
from events import scan_handler
from paths import frontend_dir, is_frozen
from scanner_input.listener import HidScannerListener
from settings import config

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    player.ensure_default_sounds()
    app.state.hub.loop = asyncio.get_running_loop()
    scan_handler.add_listener(app.state.hub.publish)
    settings = config.load()
    if settings.get("hid_listener_enabled", True):
        app.state.hid.start()
    # Dashboard uses the browser camera. Only grab the device in OpenCV
    # when someone asked for a native preview window (--preview).
    if app.state.preview_window and settings.get("camera_enabled"):
        app.state.camera.start(
            int(settings.get("camera_index", 0)),
            preview_window=True,
        )
    yield
    scan_handler.remove_listener(app.state.hub.publish)
    app.state.camera.stop()
    app.state.hid.stop()


def create_app(preview_window: bool = False) -> FastAPI:
    app = FastAPI(title="ScannerHub", version=VERSION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.version = VERSION
    app.state.camera = CameraService()
    app.state.hid = HidScannerListener()
    app.state.hub = ScanHub()
    app.state.preview_window = preview_window

    attach(app)

    static_root = frontend_dir()
    if static_root.exists():
        app.mount("/styles", NoCacheStaticFiles(directory=static_root / "styles"), name="styles")
        app.mount("/scripts", NoCacheStaticFiles(directory=static_root / "scripts"), name="scripts")

        @app.get("/")
        def index() -> HTMLResponse:
            html_path = static_root / "index.html"
            html = html_path.read_text(encoding="utf-8")
            stamp = 0
            for rel in (
                "scripts/camera_picker.js",
                "scripts/dashboard.js",
                "scripts/settings.js",
                "styles/main.css",
            ):
                path = static_root / rel
                if path.exists():
                    stamp = max(stamp, path.stat().st_mtime_ns)
            html = re.sub(r"\?v=[^\"']+", f"?v={stamp}", html)
            return HTMLResponse(html, headers={"Cache-Control": "no-store, max-age=0"})

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="ScannerHub backend")
    parser.add_argument("--host", default=None, help="Bind host (overrides SCANNERHUB_HOST / settings)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (overrides SCANNERHUB_PORT / settings)")
    parser.add_argument("--preview", action="store_true", help="Show a local OpenCV preview window")
    parser.add_argument("--open", action="store_true", help="Open the dashboard in a browser")
    args = parser.parse_args()

    host = config.bind_host(args.host)
    port = config.bind_port(args.port)
    player.ensure_default_sounds()

    if is_frozen() or args.open:
        def _open_browser() -> None:
            time.sleep(0.9)
            browse_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
            webbrowser.open(f"http://{browse_host}:{port}/")

        threading.Thread(target=_open_browser, daemon=True).start()

    engines = decoder.engine_status()
    print(f"ScannerHub dashboard: http://{host}:{port}/", flush=True)
    print(
        "Decoder: zxing-cpp={} pyzbar={}".format(
            "yes" if engines["zxingcpp"] else "NO",
            "yes" if engines["pyzbar"] else "no",
        ),
        flush=True,
    )
    if not engines["zxingcpp"] and not engines["pyzbar"]:
        print(
            "WARNING: no barcode decoder loaded. Install zxing-cpp in this venv and restart.",
            flush=True,
        )
    uvicorn.run(
        create_app(preview_window=args.preview),
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Windows. Run from the repo root:

    pyinstaller packaging/pyinstaller_windows.spec
"""

from pathlib import Path

from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

ROOT = Path(SPECPATH).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

datas = [
    (str(FRONTEND / "index.html"), "frontend"),
    (str(FRONTEND / "styles"), "frontend/styles"),
    (str(FRONTEND / "scripts"), "frontend/scripts"),
]

a = Analysis(
    [str(BACKEND / "app.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan.on",
        "pyzbar",
        "pyzbar.pyzbar",
        "cv2",
        "pygrabber",
        "pygrabber.dshow_graph",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ScannerHub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "icons" / "scannerhub.ico")
    if (ROOT / "packaging" / "icons" / "scannerhub.ico").exists()
    else None,
)

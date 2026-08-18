from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    target = tmp_path / "data"
    target.mkdir()
    monkeypatch.setenv("SCANNERHUB_DATA_DIR", str(target))
    monkeypatch.delenv("SCANNERHUB_PORT", raising=False)
    monkeypatch.delenv("SCANNERHUB_HOST", raising=False)
    from settings import config
    from events import scan_handler

    config.reset_cache()
    scan_handler.reset_dedupe()
    yield target
    config.reset_cache()
    scan_handler.reset_dedupe()

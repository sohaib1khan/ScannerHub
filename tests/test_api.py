from fastapi.testclient import TestClient
import pytest

from app import create_app


def _client(data_dir):
    from settings import config

    config.save({"camera_enabled": False, "hid_listener_enabled": False})
    return TestClient(create_app())


def test_health(data_dir):
    with _client(data_dir) as client:
        for path in ("/health", "/api/health"):
            response = client.get(path)
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "ok"
            assert body["service"] == "scannerhub"


def test_settings_roundtrip(data_dir):
    with _client(data_dir) as client:
        response = client.post("/api/settings", json={"dedupe_window_seconds": 3.5})
        assert response.status_code == 200
        assert response.json()["settings"]["dedupe_window_seconds"] == 3.5
        loaded = client.get("/api/settings").json()
        assert loaded["dedupe_window_seconds"] == 3.5


def test_manual_scan_and_list(data_dir, monkeypatch):
    monkeypatch.setattr("audio.player.play", lambda path: None)
    with _client(data_dir) as client:
        created = client.post("/api/scans/manual", json={"value": "QR-123", "source": "camera"})
        assert created.status_code == 200
        assert created.json()["ok"] is True
        listed = client.get("/api/scans").json()
        assert listed["stats"]["total"] == 1
        assert listed["scans"][0]["value"] == "QR-123"


def test_camera_frame_rejects_junk(data_dir):
    with _client(data_dir) as client:
        response = client.post(
            "/api/camera/frame",
            files={"file": ("frame.jpg", b"not-a-jpeg", "image/jpeg")},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert response.json()["scans"] == []


def test_status_reports_decoder(data_dir):
    with _client(data_dir) as client:
        body = client.get("/api/status").json()
        assert "decoder" in body
        assert "zxingcpp" in body["decoder"]


def test_camera_frame_decodes_code128(data_dir, monkeypatch):
    zxingcpp = pytest.importorskip("zxingcpp")
    import cv2
    import numpy as np

    monkeypatch.setattr("audio.player.play", lambda path: None)
    barcode = zxingcpp.create_barcode("HELLO-SCAN", zxingcpp.BarcodeFormat.Code128)
    image = zxingcpp.write_barcode_to_image(barcode, scale=3)
    frame = cv2.cvtColor(np.array(image), cv2.COLOR_GRAY2BGR)
    ok, jpeg = cv2.imencode(".jpg", frame)
    assert ok
    with _client(data_dir) as client:
        response = client.post(
            "/api/camera/frame",
            files={"file": ("frame.jpg", jpeg.tobytes(), "image/jpeg")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["hits"]
        assert body["hits"][0]["value"] == "HELLO-SCAN"
        assert body["hits"][0]["confidence"] == "high"
        assert body["scans"]
        assert body["scans"][0]["value"] == "HELLO-SCAN"


def test_sound_catalog_and_file(data_dir):
    from audio import player

    player.ensure_default_sounds()
    with _client(data_dir) as client:
        catalog = client.get("/api/settings/sounds")
        assert catalog.status_code == 200
        body = catalog.json()
        ids = {item["id"] for item in body["sounds"]}
        assert "beep-high" in ids
        assert "double-beep" in ids
        assert "success" in ids
        assert "chirp" in ids
        wav = client.get("/api/sounds/beep-high.wav")
        assert wav.status_code == 200
        assert wav.content[:4] == b"RIFF"


def test_sound_file_with_spaces(data_dir):
    from audio import player
    from paths import sounds_dir

    player.ensure_default_sounds()
    named = sounds_dir() / "Quagmire Giggity - QuickSounds.com.mp3"
    named.write_bytes(b"ID3fake-mp3")
    with _client(data_dir) as client:
        catalog = client.get("/api/settings/sounds").json()
        match = next(item for item in catalog["sounds"] if "Quagmire" in item["label"])
        assert "%20" in match["url"]
        response = client.get(match["url"])
        assert response.status_code == 200
        assert response.content.startswith(b"ID3")


def test_select_sound_in_settings(data_dir):
    with _client(data_dir) as client:
        response = client.post("/api/settings", json={"sounds": {"camera": "double-beep"}})
        assert response.status_code == 200
        loaded = client.get("/api/settings").json()
        assert loaded["sounds"]["camera"] == "double-beep"


def test_cameras_endpoint_uses_enumerator(data_dir, monkeypatch):
    monkeypatch.setattr(
        "camera.enumerator.list_cameras",
        lambda: [{"index": 0, "name": "Fake Cam", "label": "Fake Cam (0)"}],
    )
    with _client(data_dir) as client:
        response = client.get("/api/cameras")
        assert response.status_code == 200
        assert response.json()["cameras"][0]["name"] == "Fake Cam"

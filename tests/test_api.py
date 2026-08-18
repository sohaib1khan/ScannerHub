from fastapi.testclient import TestClient

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


def test_cameras_endpoint_uses_enumerator(data_dir, monkeypatch):
    monkeypatch.setattr(
        "camera.enumerator.list_cameras",
        lambda: [{"index": 0, "name": "Fake Cam", "label": "Fake Cam (0)"}],
    )
    with _client(data_dir) as client:
        response = client.get("/api/cameras")
        assert response.status_code == 200
        assert response.json()["cameras"][0]["name"] == "Fake Cam"

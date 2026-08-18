from camera import enumerator


def test_linux_names_from_sysfs(tmp_path, monkeypatch):
    (tmp_path / "video0").mkdir()
    (tmp_path / "video0" / "name").write_text("Logitech C920\n", encoding="utf-8")
    (tmp_path / "video2").mkdir()
    (tmp_path / "video2" / "name").write_text("Integrated Webcam\n", encoding="utf-8")

    original = enumerator.Path

    def path_factory(value=".", *args, **kwargs):
        if str(value) == "/sys/class/video4linux":
            return tmp_path
        return original(value, *args, **kwargs)

    monkeypatch.setattr(enumerator, "Path", path_factory)
    names = enumerator._linux_names()
    assert names[0] == "Logitech C920"
    assert names[2] == "Integrated Webcam"


def test_list_cameras_skips_unopenable(monkeypatch):
    monkeypatch.setattr(enumerator, "_friendly_names", lambda: {0: "Logitech C920", 1: "Dummy"})
    monkeypatch.setattr(enumerator, "_can_open", lambda index: index == 0)
    devices = enumerator.list_cameras()
    assert devices == [
        {"index": 0, "name": "Logitech C920", "label": "Logitech C920 (0)"},
    ]


def test_generic_label_when_no_friendly_name(monkeypatch):
    monkeypatch.setattr(enumerator, "_friendly_names", lambda: {})
    monkeypatch.setattr(enumerator, "_can_open", lambda index: index == 0)
    devices = enumerator.list_cameras(max_index=2)
    assert devices[0]["name"] == "Camera 0"
    assert devices[0]["label"] == "Camera 0 (0)"

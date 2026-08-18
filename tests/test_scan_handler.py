from events import scan_handler
from settings import config
from storage import json_log


def test_records_scan_and_notifies_listener(data_dir, monkeypatch):
    seen = []
    monkeypatch.setattr("audio.player.play", lambda path: None)
    scan_handler.add_listener(seen.append)
    try:
        event = scan_handler.handle_scan("  hello  ", "camera", "QRCODE")
    finally:
        scan_handler.remove_listener(seen.append)

    assert event is not None
    assert event["value"] == "hello"
    assert event["source"] == "camera"
    assert event["format"] == "QRCODE"
    assert json_log.read_all()[0]["id"] == event["id"]
    assert seen == [event]


def test_dedupe_window_suppresses_repeats(data_dir, monkeypatch):
    monkeypatch.setattr("audio.player.play", lambda path: None)
    config.save({"dedupe_window_seconds": 5})
    first = scan_handler.handle_scan("SAME", "camera", "QRCODE")
    second = scan_handler.handle_scan("SAME", "camera", "QRCODE")
    other_source = scan_handler.handle_scan("SAME", "external_scanner", "HID")

    assert first is not None
    assert second is None
    assert other_source is not None
    assert len(json_log.read_all()) == 2


def test_blank_value_ignored(data_dir):
    assert scan_handler.handle_scan("   ", "camera") is None
    assert json_log.read_all() == []

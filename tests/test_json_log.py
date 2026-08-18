from storage import json_log


def test_append_and_read(data_dir):
    first = json_log.append({"id": "1", "value": "ABC", "source": "camera"})
    second = json_log.append({"id": "2", "value": "DEF", "source": "external_scanner"})
    assert first["value"] == "ABC"
    items = json_log.read_all()
    assert [item["id"] for item in items] == ["1", "2"]
    stats = json_log.stats()
    assert stats["total"] == 2
    assert stats["by_source"]["camera"] == 1
    assert stats["by_source"]["external_scanner"] == 1
    assert stats["latest"]["id"] == "2"


def test_corrupt_file_is_reset_to_empty(data_dir):
    path = data_dir / "scan_history.json"
    path.write_text("{not json", encoding="utf-8")
    assert json_log.read_all() == []
    json_log.append({"id": "ok", "value": "X"})
    assert json_log.read_all()[0]["id"] == "ok"


def test_clear(data_dir):
    json_log.append({"id": "1"})
    json_log.clear()
    assert json_log.read_all() == []
    assert json_log.stats()["total"] == 0

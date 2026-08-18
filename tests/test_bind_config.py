from settings import config


def test_bind_port_cli_wins(data_dir, monkeypatch):
    monkeypatch.setenv("SCANNERHUB_PORT", "9000")
    config.save({"api_port": 8000})
    assert config.bind_port(7777) == 7777


def test_bind_port_env_wins_over_settings(data_dir, monkeypatch):
    monkeypatch.setenv("SCANNERHUB_PORT", "9000")
    config.save({"api_port": 8000})
    assert config.bind_port() == 9000


def test_bind_port_falls_back_to_settings(data_dir):
    config.save({"api_port": 8000})
    assert config.bind_port() == 8000


def test_bind_host_env(data_dir, monkeypatch):
    monkeypatch.setenv("SCANNERHUB_HOST", "0.0.0.0")
    assert config.bind_host() == "0.0.0.0"

"""Play scan feedback sounds. Generates default WAV beeps if missing."""

from __future__ import annotations

import math
import struct
import subprocess
import sys
import threading
import wave
from pathlib import Path

from paths import sounds_dir

CAMERA_DEFAULT = "camera_default.wav"
SCANNER_DEFAULT = "scanner_default.wav"

_play_lock = threading.Lock()


def _write_tone(path: Path, frequency: float, duration: float = 0.16, volume: float = 0.35) -> None:
    sample_rate = 22050
    n_samples = int(sample_rate * duration)
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            fade = min(i / 80, 1.0, (n_samples - i) / 80)
            sample = volume * fade * math.sin(2 * math.pi * frequency * (i / sample_rate))
            frames.extend(struct.pack("<h", int(sample * 32767)))
        wav.writeframes(frames)


def ensure_default_sounds() -> None:
    target = sounds_dir()
    camera = target / CAMERA_DEFAULT
    scanner = target / SCANNER_DEFAULT
    if not camera.exists():
        _write_tone(camera, 880.0)
    if not scanner.exists():
        _write_tone(scanner, 660.0)


def default_path(source: str) -> Path:
    ensure_default_sounds()
    name = CAMERA_DEFAULT if source == "camera" else SCANNER_DEFAULT
    return sounds_dir() / name


def resolve_sound(source: str, custom_path: str | None) -> Path:
    if custom_path:
        path = Path(custom_path)
        if path.is_file():
            return path
    return default_path(source)


def play(path: Path) -> None:
    """Fire-and-forget playback so the scan path never blocks on audio."""
    threading.Thread(target=_play_blocking, args=(path,), daemon=True).start()


def _play_blocking(path: Path) -> None:
    with _play_lock:
        try:
            _play_simpleaudio(path)
            return
        except Exception:
            pass
        try:
            _play_platform(path)
        except Exception:
            pass


def _play_simpleaudio(path: Path) -> None:
    import simpleaudio  # type: ignore

    wave_obj = simpleaudio.WaveObject.from_wave_file(str(path))
    play_obj = wave_obj.play()
    play_obj.wait_done()


def _play_platform(path: Path) -> None:
    if sys.platform.startswith("win"):
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME)
        return

    for cmd in (
        ["paplay", str(path)],
        ["aplay", "-q", str(path)],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
    ):
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, timeout=5)
            if result.returncode == 0:
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError(f"No audio backend could play {path}")

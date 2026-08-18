"""Play scan feedback sounds. Generates bundled sample WAVs if missing."""

from __future__ import annotations

import math
import re
import struct
import subprocess
import sys
import threading
import wave
from pathlib import Path
from typing import Any
from urllib.parse import quote

from paths import sounds_dir

CAMERA_DEFAULT = "beep-high"
SCANNER_DEFAULT = "beep-low"

SAMPLE_LIBRARY: list[dict[str, Any]] = [
    {"id": "beep-high", "label": "High beep", "kind": "tone", "freq": 880.0, "duration": 0.16},
    {"id": "beep-mid", "label": "Mid beep", "kind": "tone", "freq": 740.0, "duration": 0.16},
    {"id": "beep-low", "label": "Low beep", "kind": "tone", "freq": 520.0, "duration": 0.18},
    {"id": "double-beep", "label": "Double beep", "kind": "double", "freq": 880.0},
    {"id": "success", "label": "Success chime", "kind": "two_tone", "freqs": (523.25, 783.99)},
    {"id": "chirp", "label": "Chirp", "kind": "chirp", "start": 620.0, "end": 1480.0, "duration": 0.22},
    {"id": "soft-ding", "label": "Soft ding", "kind": "ding", "freq": 988.0},
    {"id": "click", "label": "Click", "kind": "click"},
]

ALLOWED_SOUND_TYPES = {".wav", ".mp3", ".ogg"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .'_()\[\]&,+-]{0,200}$")
_play_lock = threading.Lock()
SAMPLE_RATE = 22050


def _pack_samples(samples: list[float], volume: float = 0.35) -> bytes:
    frames = bytearray()
    n = len(samples)
    for i, raw in enumerate(samples):
        fade = min(i / 80, 1.0, (n - i) / 80) if n > 160 else 1.0
        sample = max(-1.0, min(1.0, volume * fade * raw))
        frames.extend(struct.pack("<h", int(sample * 32767)))
    return bytes(frames)


def _write_wav(path: Path, samples: list[float], volume: float = 0.35) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(_pack_samples(samples, volume))


def _tone(frequency: float, duration: float) -> list[float]:
    n = int(SAMPLE_RATE * duration)
    return [math.sin(2 * math.pi * frequency * (i / SAMPLE_RATE)) for i in range(n)]


def _silence(duration: float) -> list[float]:
    return [0.0] * int(SAMPLE_RATE * duration)


def _build_sample(spec: dict[str, Any]) -> list[float]:
    kind = spec["kind"]
    if kind == "tone":
        return _tone(float(spec["freq"]), float(spec["duration"]))
    if kind == "double":
        beep = _tone(float(spec["freq"]), 0.09)
        return beep + _silence(0.06) + beep
    if kind == "two_tone":
        first, second = spec["freqs"]
        return _tone(float(first), 0.11) + _silence(0.03) + _tone(float(second), 0.16)
    if kind == "chirp":
        duration = float(spec["duration"])
        start = float(spec["start"])
        end = float(spec["end"])
        n = int(SAMPLE_RATE * duration)
        samples = []
        phase = 0.0
        for i in range(n):
            freq = start + (end - start) * (i / max(n - 1, 1))
            phase += 2 * math.pi * freq / SAMPLE_RATE
            samples.append(math.sin(phase))
        return samples
    if kind == "ding":
        freq = float(spec["freq"])
        n = int(SAMPLE_RATE * 0.32)
        samples = []
        for i in range(n):
            t = i / SAMPLE_RATE
            env = math.exp(-t * 9.0)
            samples.append(env * math.sin(2 * math.pi * freq * t))
        return samples
    n = int(SAMPLE_RATE * 0.05)
    return [math.sin(2 * math.pi * 180 * (i / SAMPLE_RATE)) * (1.0 - i / n) for i in range(n)]


def sample_path(sound_id: str) -> Path:
    return sounds_dir() / f"{sound_id}.wav"


def ensure_default_sounds() -> None:
    target = sounds_dir()
    for spec in SAMPLE_LIBRARY:
        path = target / f"{spec['id']}.wav"
        if not path.exists():
            _write_wav(path, _build_sample(spec))
    # Keep the original filenames working for older settings.
    camera_legacy = target / "camera_default.wav"
    scanner_legacy = target / "scanner_default.wav"
    if not camera_legacy.exists():
        camera_legacy.write_bytes((target / f"{CAMERA_DEFAULT}.wav").read_bytes())
    if not scanner_legacy.exists():
        scanner_legacy.write_bytes((target / f"{SCANNER_DEFAULT}.wav").read_bytes())


def default_id(source: str) -> str:
    return CAMERA_DEFAULT if source == "camera" else SCANNER_DEFAULT


def default_path(source: str) -> Path:
    ensure_default_sounds()
    return sample_path(default_id(source))


def is_safe_sound_name(name: str) -> bool:
    return bool(_SAFE_ID.match(name)) and Path(name).suffix.lower() in ALLOWED_SOUND_TYPES | {""}


def list_sounds() -> list[dict[str, Any]]:
    """Built-in samples plus any extra files the user dropped in data/sounds."""
    ensure_default_sounds()
    target = sounds_dir()
    items: list[dict[str, Any]] = [
        {"id": "none", "label": "Silent", "file": "", "builtin": True, "url": ""}
    ]
    seen: set[str] = {"none"}
    for spec in SAMPLE_LIBRARY:
        filename = f"{spec['id']}.wav"
        items.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "file": filename,
                "builtin": True,
                "url": f"/api/sounds/{quote(filename)}",
            }
        )
        seen.add(spec["id"])
        seen.add(filename)

    for path in sorted(target.iterdir()):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_SOUND_TYPES:
            continue
        if path.name in {"camera_default.wav", "scanner_default.wav"}:
            continue
        if path.stem in seen or path.name in seen:
            continue
        sound_id = path.stem
        items.append(
            {
                "id": sound_id,
                "label": path.name,
                "file": path.name,
                "builtin": False,
                "url": f"/api/sounds/{quote(path.name)}",
            }
        )
        seen.add(sound_id)
    return items


def resolve_sound(source: str, selected: str | None) -> Path | None:
    ensure_default_sounds()
    if selected in {"none", "silent"}:
        return None
    if not selected:
        return default_path(source)

    as_path = Path(selected)
    if as_path.is_file():
        return as_path

    name = as_path.name
    if name.endswith((".wav", ".mp3", ".ogg")):
        candidate = sounds_dir() / name
        if candidate.is_file():
            return candidate
        stem = as_path.stem
    else:
        stem = name

    for item in list_sounds():
        if item["id"] == selected or item["id"] == stem:
            if not item["file"]:
                return None
            path = sounds_dir() / item["file"]
            if path.is_file():
                return path
    wav = sample_path(stem)
    if wav.is_file():
        return wav
    return default_path(source)


def play(path: Path | None) -> None:
    """Fire-and-forget playback so the scan path never blocks on audio."""
    if path is None or not Path(path).is_file():
        return
    threading.Thread(target=_play_blocking, args=(Path(path),), daemon=True).start()


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

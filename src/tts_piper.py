import array
import os
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Callable, List, Optional

PIPER_BIN = Path(os.getenv("CHATTY_PIPER_BIN", "/home/pi/chatty/voices/piper/piper"))
PIPER_MODEL = Path(
    os.getenv("CHATTY_PIPER_MODEL", "/home/pi/chatty/voices/piper/voice.onnx")
)
PIPER_CONFIG = Path(
    os.getenv("CHATTY_PIPER_CONFIG", "/home/pi/chatty/voices/piper/voice.onnx.json")
)
ALSA_DEVICE = os.getenv("CHATTY_ALSA_OUT", "plughw:CARD=PowerConf,DEV=0")


def speak(text: str, on_level: Optional[Callable[[float], None]] = None) -> None:
    """Speak text with Piper. on_level, if given, gets mouth levels (0..1) during playback."""
    text = (text or "").strip()
    if not text:
        return

    if not PIPER_BIN.exists():
        raise FileNotFoundError(f"Piper binary not found: {PIPER_BIN}")
    if not PIPER_MODEL.exists():
        raise FileNotFoundError(f"Piper model not found: {PIPER_MODEL}")
    if not PIPER_CONFIG.exists():
        raise FileNotFoundError(f"Piper config not found: {PIPER_CONFIG}")

    with tempfile.NamedTemporaryFile(
        prefix="chatty_", suffix=".wav", delete=False
    ) as f:
        wav_path = f.name

    # Synthesize wav
    p1 = subprocess.run(
        [
            str(PIPER_BIN),
            "--model",
            str(PIPER_MODEL),
            "--config",
            str(PIPER_CONFIG),
            "--output_file",
            wav_path,
        ],
        input=(text + "\n").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if p1.returncode != 0:
        raise RuntimeError(
            "Piper failed: "
            + (p1.stderr.decode("utf-8", errors="ignore")[:500] or "(no stderr)")
        )

    try:
        envelope = loudness_envelope(wav_path) if on_level else []
        play(wav_path, envelope, on_level)
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


FRAME_SECONDS = 0.04  # mouth updates 25 times a second


def loudness_envelope(wav_path: str) -> List[float]:
    """Loudness (0..1) of each 40 ms slice of a 16-bit wav, for lip sync."""
    try:
        with wave.open(wav_path, "rb") as wf:
            if wf.getsampwidth() != 2:
                return []
            rate, channels = wf.getframerate(), wf.getnchannels()
            samples = array.array("h", wf.readframes(wf.getnframes()))
    except (wave.Error, OSError):
        return []
    step = max(1, int(rate * FRAME_SECONDS)) * channels
    levels = []
    for i in range(0, len(samples), step):
        chunk = samples[i:i + step]
        if chunk:
            levels.append((sum(x * x for x in chunk[::4]) / len(chunk[::4])) ** 0.5)
    if not levels:
        return []
    peak = sorted(levels)[int(len(levels) * 0.95) - 1 if len(levels) > 1 else 0] or 1.0
    return [min(1.0, v / peak) for v in levels]


def play(wav_path: str, envelope: List[float], on_level: Optional[Callable[[float], None]]) -> None:
    p = subprocess.Popen(["aplay", "-q", "-D", ALSA_DEVICE, wav_path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if on_level and envelope:
        start = time.time()
        while p.poll() is None:
            idx = int((time.time() - start) / FRAME_SECONDS)
            on_level(envelope[idx] if idx < len(envelope) else 0.0)
            time.sleep(FRAME_SECONDS)
        on_level(0.0)
    _, err = p.communicate()
    if p.returncode != 0:
        raise RuntimeError(
            "aplay failed: " + ((err or b"").decode("utf-8", errors="ignore")[:500] or "(no stderr)")
        )

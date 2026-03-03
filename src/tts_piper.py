import os
import subprocess
import tempfile
from pathlib import Path

PIPER_BIN = Path(os.getenv("CHATTY_PIPER_BIN", "/home/pi/chatty/voices/piper/piper"))
PIPER_MODEL = Path(os.getenv("CHATTY_PIPER_MODEL", "/home/pi/chatty/voices/piper/voice.onnx"))
PIPER_CONFIG = Path(os.getenv("CHATTY_PIPER_CONFIG", "/home/pi/chatty/voices/piper/voice.onnx.json"))
ALSA_DEVICE = os.getenv("CHATTY_ALSA_OUT", "plughw:0,0")

def speak(text: str) -> None:
    text = (text or "").strip()
    if not text:
        return

    if not PIPER_BIN.exists():
        raise FileNotFoundError(f"Piper binary not found: {PIPER_BIN}")
    if not PIPER_MODEL.exists():
        raise FileNotFoundError(f"Piper model not found: {PIPER_MODEL}")
    if not PIPER_CONFIG.exists():
        raise FileNotFoundError(f"Piper config not found: {PIPER_CONFIG}")

    with tempfile.NamedTemporaryFile(prefix="chatty_", suffix=".wav", delete=False) as f:
        wav_path = f.name

    # Synthesize wav
    p1 = subprocess.run(
        [str(PIPER_BIN), "--model", str(PIPER_MODEL), "--config", str(PIPER_CONFIG), "--output_file", wav_path],
        input=(text + "\n").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if p1.returncode != 0:
        raise RuntimeError("Piper failed: " + (p1.stderr.decode("utf-8", errors="ignore")[:500] or "(no stderr)"))

    # Play wav
    p2 = subprocess.run(
        ["aplay", "-q", "-D", ALSA_DEVICE, wav_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if p2.returncode != 0:
        raise RuntimeError("aplay failed: " + (p2.stderr.decode("utf-8", errors="ignore")[:500] or "(no stderr)"))

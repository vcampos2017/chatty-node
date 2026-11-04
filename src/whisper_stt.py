"""Sharper ears: local Whisper speech-to-text (whisper.cpp) for what you say after "Hey Chatty".

Vosk still does the quick jobs: it listens for the wake phrase, shows the live caption,
and decides when you've stopped talking. Then the audio of your question goes to
whisper.cpp, running right here on the Pi, for a much more accurate transcript.
Nothing leaves the Pi: the clip is written to RAM (/dev/shm), read once, and deleted.
If Whisper isn't installed, is turned off, or takes too long, Chatty uses Vosk's words.

Install once with `bash scripts/install_whisper.sh`.

Settings (in /etc/chatty/secrets.env):
  CHATTY_WHISPER=0           turn it off (Vosk only). On by default when installed.
  CHATTY_WHISPER_BIN         default /home/pi/whisper.cpp/build/bin/whisper-cli
  CHATTY_WHISPER_MODEL       default /home/pi/whisper.cpp/models/ggml-base.en.bin
                             (ggml-tiny.en.bin is about 3x faster, less accurate)
  CHATTY_WHISPER_THREADS     CPU threads, default 4
  CHATTY_WHISPER_BEAM        1 = fastest (default); 5 = a little more accurate, slower
  CHATTY_WHISPER_TIMEOUT     seconds before giving up and using Vosk, default 15
  CHATTY_WHISPER_FAST        1 = only look at the length of your clip, not a full
                             30 seconds (much faster on the Pi; default 1)
  CHATTY_WHISPER_PROMPT      words she should expect to hear (names, places)
"""
import os
import re
import subprocess
import tempfile
import time
import wave

import numpy as np

ENABLED = os.getenv("CHATTY_WHISPER", "1") != "0"
BIN = os.getenv("CHATTY_WHISPER_BIN", "/home/pi/whisper.cpp/build/bin/whisper-cli")
MODEL = os.getenv("CHATTY_WHISPER_MODEL", "/home/pi/whisper.cpp/models/ggml-base.en.bin")
THREADS = int(os.getenv("CHATTY_WHISPER_THREADS", "4"))
BEAM = int(os.getenv("CHATTY_WHISPER_BEAM", "1"))
TIMEOUT = float(os.getenv("CHATTY_WHISPER_TIMEOUT", "15"))
FAST = os.getenv("CHATTY_WHISPER_FAST", "1") != "0"
PROMPT = os.getenv(
    "CHATTY_WHISPER_PROMPT",
    "Hey Chatty. Greenhouse, rain gauge, soil, weather, Tiny the cat, tic-tac-toe.")
TMP_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None

# Whisper sometimes "hears" these in near-silence; never trust them on their own.
HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching",
                  "you", "bye", "subtitles by the amaraorg community", "music"}

FRAME = 0.03       # seconds per loudness frame when trimming silence
PAD = 0.3          # silence kept on each side of the speech


def available() -> bool:
    return ENABLED and os.path.isfile(BIN) and os.access(BIN, os.X_OK) and os.path.isfile(MODEL)


def status() -> str:
    """One line for the log at startup."""
    if not ENABLED:
        return "Whisper is off (CHATTY_WHISPER=0); using Vosk for questions"
    if not available():
        missing = BIN if not os.path.isfile(BIN) else MODEL
        return f"Whisper not installed ({missing} missing); using Vosk for questions"
    return f"Whisper on for questions: {os.path.basename(MODEL)}, {THREADS} threads"


def trim_silence(pcm16: bytes, rate: int) -> bytes:
    """Cut the quiet before and after the speech, keeping a little padding."""
    x = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
    n = max(1, int(rate * FRAME))
    frames = len(x) // n
    if frames == 0:
        return pcm16
    rms = np.sqrt(np.mean(x[:frames * n].reshape(frames, n) ** 2, axis=1))
    loud = np.nonzero(rms > max(300.0, 0.1 * float(rms.max())))[0]
    if loud.size == 0:
        return b""
    pad = int(PAD / FRAME)
    start = max(0, int(loud[0]) - pad) * n
    end = min(len(x), (int(loud[-1]) + 1 + pad) * n)
    return x[start:end].astype(np.int16).tobytes()


def clean(text: str) -> str:
    """Whisper's text without [BLANK_AUDIO], (music) and similar notes."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*", " ", text or "")
    return " ".join(text.split())


def audio_ctx(seconds: float) -> int:
    """Encoder context for a clip this long (1500 = the full 30 seconds)."""
    return min(1500, max(256, int(seconds * 50) + 64))


def command(wav_path: str, seconds: float) -> list:
    cmd = [BIN, "-m", MODEL, "-f", wav_path, "-l", "en", "-t", str(THREADS),
           "-nt", "-np", "-bs", str(BEAM), "-bo", str(BEAM)]
    if FAST:
        cmd += ["-ac", str(audio_ctx(seconds))]
    if PROMPT:
        cmd += ["--prompt", PROMPT]
    return cmd


def plausible(whisper_text: str, vosk_text: str) -> bool:
    """Guard against Whisper inventing words in noise."""
    words = whisper_text.lower().strip(" .!?,").split()
    if not words:
        return False
    if " ".join(re.sub(r"[^a-z0-9 ]", "", w) for w in words) in HALLUCINATIONS:
        return len(vosk_text.split()) <= 3   # fine if Vosk also heard something tiny
    return len(words) <= 2 * len(vosk_text.split()) + 8


def transcribe(pcm16: bytes, rate: int, vosk_text: str = ""):
    """Return (text, seconds taken), or (None, seconds) to fall back to Vosk."""
    started = time.time()
    if not available() or not pcm16:
        return None, 0.0
    clip = trim_silence(pcm16, rate)
    seconds = len(clip) / 2 / rate
    if seconds < 0.3:
        return None, time.time() - started
    fd, path = tempfile.mkstemp(prefix="chatty_", suffix=".wav", dir=TMP_DIR)
    try:
        with os.fdopen(fd, "wb") as f, wave.open(f, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(clip)
        r = subprocess.run(command(path, seconds), capture_output=True, text=True,
                           timeout=TIMEOUT)
        if r.returncode != 0:
            print("(whisper failed:", (r.stderr or "").strip()[-200:], ")", flush=True)
            return None, time.time() - started
        text = clean(r.stdout)
        if not plausible(text, vosk_text):
            print(f"(whisper heard {text!r}; doesn't look right, keeping Vosk)", flush=True)
            return None, time.time() - started
        return text, time.time() - started
    except subprocess.TimeoutExpired:
        print(f"(whisper took over {TIMEOUT:.0f}s; using Vosk)", flush=True)
        return None, time.time() - started
    except Exception as e:
        print("(whisper error:", repr(e), ")", flush=True)
        return None, time.time() - started
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    # Test: python3 src/whisper_stt.py some.wav   (16 kHz mono 16-bit)
    import sys
    print(status())
    if len(sys.argv) > 1:
        with wave.open(sys.argv[1], "rb") as w:
            data, r = w.readframes(w.getnframes()), w.getframerate()
        text, secs = transcribe(data, r, "x " * 50)
        print(f"Heard ({secs:.1f}s): {text}")

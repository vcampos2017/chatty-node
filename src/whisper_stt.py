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
  CHATTY_WHISPER_PROMPT      words she should expect to hear (names, places); the default
                             lists the words her own skills use ("square root",
                             "Morse code", "Mandelbrot"...), which steers Whisper toward
                             them when a word is unclear

Borrowed ears (optional, off unless CHATTY_WHISPER_URL is set): a whisper.cpp server
on one of Vincent's own computers (the Dell), reached over Tailscale or the home
network only, never the internet. A bigger model there (small.en) hears better and
answers faster than base.en on the Pi. The clip goes straight there in memory and
nothing is kept; if the computer is off, asleep or slow she uses the Pi's own Whisper
as before and leaves the other computer alone for CHATTY_WHISPER_URL_RETRY seconds.
  CHATTY_WHISPER_URL         e.g. http://my-dell:8178 (a whisper.cpp whisper-server)
  CHATTY_WHISPER_URL_TIMEOUT seconds to wait for it, default 6
  CHATTY_WHISPER_URL_RETRY   rest after a failure, default 300
A public internet address is refused (her voice clips never leave home).
"""
import ipaddress
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import wave

import numpy as np

ENABLED = os.getenv("CHATTY_WHISPER", "1") != "0"
BIN = os.getenv("CHATTY_WHISPER_BIN", "/home/pi/whisper.cpp/build/bin/whisper-cli")
MODEL = os.getenv("CHATTY_WHISPER_MODEL", "/home/pi/whisper.cpp/models/ggml-base.en.bin")
THREADS = int(os.getenv("CHATTY_WHISPER_THREADS", "4"))
BEAM = int(os.getenv("CHATTY_WHISPER_BEAM", "1"))
TIMEOUT = float(os.getenv("CHATTY_WHISPER_TIMEOUT", "15"))
FAST = os.getenv("CHATTY_WHISPER_FAST", "1") != "0"
# Words she hears a lot. Whisper leans toward words in its prompt when a sound is
# unclear ("what's the square root of 81", not "square ring"). Kept short: every word
# here is read by the model on each question.
DEFAULT_PROMPT = ("Hey Chatty. What's the square root of 81? 15 percent of 80, times, "
                  "divided by. Greenhouse, rain gauge, soil, CO2, weather forecast, timer, "
                  "alarm, Morse code, piano, chess, tic-tac-toe, Mandelbrot, fractal, "
                  "Tiny the cat.")
PROMPT = os.getenv("CHATTY_WHISPER_PROMPT", DEFAULT_PROMPT)
REMOTE_URL = os.getenv("CHATTY_WHISPER_URL", "").strip().rstrip("/")
REMOTE_TIMEOUT = float(os.getenv("CHATTY_WHISPER_URL_TIMEOUT", "6"))
REMOTE_RETRY = float(os.getenv("CHATTY_WHISPER_URL_RETRY", "300"))
_remote_down_until = 0.0
TMP_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None

# Whisper sometimes "hears" these in near-silence; never trust them on their own.
HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching",
                  "you", "bye", "subtitles by the amaraorg community", "music"}

FRAME = 0.03       # seconds per loudness frame when trimming silence
PAD = 0.3          # silence kept on each side of the speech


def home_only(url: str) -> bool:
    """True for an address at home: a Tailscale or private address, or a plain
    computer name ('my-dell', 'dell.local', 'dell.tail1234.ts.net'). Public internet
    addresses and ordinary domain names are refused: her voice clips never leave home."""
    try:
        u = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host or host.endswith((".local", ".ts.net", ".lan", ".home.arpa"))
    return (ip.is_private or ip.is_loopback
            or (ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10")))


def remote_on() -> bool:
    return bool(ENABLED and REMOTE_URL and home_only(REMOTE_URL))


def local_on() -> bool:
    return ENABLED and os.path.isfile(BIN) and os.access(BIN, os.X_OK) and os.path.isfile(MODEL)


def available() -> bool:
    return local_on() or remote_on()


def status() -> str:
    """One line for the log at startup."""
    if not ENABLED:
        return "Whisper is off (CHATTY_WHISPER=0); using Vosk for questions"
    borrowed = ""
    if REMOTE_URL and not home_only(REMOTE_URL):
        borrowed = "; CHATTY_WHISPER_URL ignored (not a home or Tailscale address)"
    elif remote_on():
        borrowed = f"; borrowed ears first: {urllib.parse.urlparse(REMOTE_URL).hostname}"
    if not local_on():
        missing = BIN if not os.path.isfile(BIN) else MODEL
        if remote_on():
            return f"Whisper on the Pi not installed ({missing} missing){borrowed}, then Vosk"
        return f"Whisper not installed ({missing} missing); using Vosk for questions{borrowed}"
    return f"Whisper on for questions: {os.path.basename(MODEL)}, {THREADS} threads{borrowed}"


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


def level_db(pcm16: bytes) -> float:
    """Loudest moment of the clip in dB below full scale (0 = the loudest possible).
    For the log: about -30 or lower means the mic hears her owner faintly."""
    x = np.frombuffer(pcm16, dtype=np.int16)
    peak = int(np.max(np.abs(x.astype(np.int32)))) if x.size else 0
    return round(20 * float(np.log10(max(peak, 1) / 32768.0)), 1)


def wav_bytes(pcm16: bytes, rate: int) -> bytes:
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16)
    return buf.getvalue()


def ask_remote(clip: bytes, rate: int):
    """The borrowed ears: send the clip to the whisper.cpp server, get its words.
    Returns the text, or None (and rests the remote) if it is off, slow or odd."""
    global _remote_down_until
    if not remote_on() or time.time() < _remote_down_until:
        return None
    fields = {"response_format": "json", "temperature": "0", "language": "en",
              "no_timestamps": "true"}
    if PROMPT:
        fields["prompt"] = PROMPT
    edge = uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += (f"--{edge}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                 f"{v}\r\n").encode()
    body += (f"--{edge}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"question.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode()
    body += wav_bytes(clip, rate) + f"\r\n--{edge}--\r\n".encode()
    req = urllib.request.Request(f"{REMOTE_URL}/inference", data=bytes(body), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={edge}"})
    try:
        with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT) as r:
            text = json.loads(r.read().decode("utf-8", "replace")).get("text")
        if not isinstance(text, str):
            raise ValueError("no text in the answer")
        return text
    except Exception as e:
        _remote_down_until = time.time() + REMOTE_RETRY
        print(f"(borrowed ears didn't answer: {type(e).__name__}; using the Pi, "
              f"retry in {REMOTE_RETRY / 60:.0f} min)", flush=True)
        return None


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
    """Return (text, seconds taken), or (None, seconds) to fall back to Vosk.
    Tries the borrowed ears first (when set), then whisper.cpp on the Pi."""
    started = time.time()
    if not available() or not pcm16:
        return None, 0.0
    clip = trim_silence(pcm16, rate)
    seconds = len(clip) / 2 / rate
    if seconds < 0.3:
        return None, time.time() - started
    level = level_db(clip)
    remote = ask_remote(clip, rate)
    if remote is not None:
        text = clean(remote)
        if plausible(text, vosk_text):
            print(f"(borrowed ears, level {level:.0f} dB)", flush=True)
            return text, time.time() - started
        print(f"(borrowed ears heard {text!r}; doesn't look right, keeping Vosk)", flush=True)
        return None, time.time() - started
    if not local_on():
        return None, time.time() - started
    fd, path = tempfile.mkstemp(prefix="chatty_", suffix=".wav", dir=TMP_DIR)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(wav_bytes(clip, rate))
        r = subprocess.run(command(path, seconds), capture_output=True, text=True,
                           timeout=TIMEOUT)
        if r.returncode != 0:
            print("(whisper failed:", (r.stderr or "").strip()[-200:], ")", flush=True)
            return None, time.time() - started
        text = clean(r.stdout)
        if not plausible(text, vosk_text):
            print(f"(whisper heard {text!r}; doesn't look right, keeping Vosk)", flush=True)
            return None, time.time() - started
        print(f"(whisper on the Pi, {seconds:.1f}s clip, level {level:.0f} dB)", flush=True)
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

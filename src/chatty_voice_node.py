import os, json, queue, subprocess, time, re, threading, random, uuid
import sys

sys.path.insert(0, os.path.dirname(__file__))  # allow importing src siblings
from tts_piper import speak as speak_piper  # Piper TTS
from datetime import datetime

import numpy as np
import requests
from vosk import Model, KaldiRecognizer
from dotenv import load_dotenv

# ----------------------------
# NumPy streaming resampler (Python 3.13 compatible; replaces audioop.ratecv)
# ----------------------------
_resample_t = 0.0
_resample_last = None


def resample_pcm16_mono(pcm16: bytes, in_rate: int, out_rate: int) -> bytes:
    global _resample_t, _resample_last

    if in_rate == out_rate:
        return pcm16

    x = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
    if x.size == 0:
        return b""

    if _resample_last is not None:
        x = np.concatenate(([float(_resample_last)], x))

    step = in_rate / out_rate
    # number of output samples we can produce from this chunk
    n = int((len(x) - 1 - _resample_t) / step) + 1
    if n <= 0:
        _resample_last = int(x[-1])
        return b""

    idx = _resample_t + step * np.arange(n, dtype=np.float32)
    i0 = np.floor(idx).astype(np.int32)
    frac = idx - i0
    i1 = np.minimum(i0 + 1, len(x) - 1)

    y = (1.0 - frac) * x[i0] + frac * x[i1]
    y = np.clip(np.rint(y), -32768, 32767).astype(np.int16)

    _resample_t = float(idx[-1] + step - (len(x) - 1))
    _resample_last = int(x[-1])
    return y.tobytes()


# ----------------------------
# Config / secrets
# ----------------------------
load_dotenv("/etc/chatty/secrets.env")

BASE = os.getenv("CHATTY_ENDPOINT", "https://ceucomics.com").rstrip("/")
TOKEN = os.getenv("CHATTY_TOKEN")
if not TOKEN:
    raise RuntimeError("CHATTY_TOKEN not found in /etc/chatty/secrets.env")

API_URL = f"{BASE}/chat"

MODEL_PATH = os.getenv(
    "CHATTY_VOSK_MODEL", "/home/pi/vosk-model/vosk-model-small-en-us-0.15"
)
VOSK_RATE = int(os.getenv("CHATTY_VOSK_RATE", "16000"))

# ALSA capture via arecord (this avoids PortAudio/sounddevice issues)
CAPTURE_DEVICE = os.getenv("CHATTY_CAPTURE_DEVICE", "plughw:CARD=CMTECK,DEV=0")
# Capture straight at the recognizer rate; the "plughw" device resamples cleanly in ALSA.
CAPTURE_RATE = int(os.getenv("CHATTY_CAPTURE_RATE", str(VOSK_RATE)))

# How many bytes to read per loop from arecord stdout
READ_BYTES = int(os.getenv("CHATTY_READ_BYTES", "4096"))
# 0 = feed all audio to the recognizer (best accuracy). Dropping quiet chunks
# clips the soft edges of words, so only raise this if CPU is a problem.
RMS_GATE = float(os.getenv("CHATTY_RMS_GATE", "0"))
# Phrases the dedicated wake-word listener is restricted to.
WAKE_GRAMMAR = ["chatty", "hey chatty", "okay chatty", "hi chatty", "[unk]"]
WAKE_MEMORY_SECONDS = 2.5  # how long a wake-listener hit counts for

# TTS output device (aplay)
PLAY_DEVICE = os.getenv("CHATTY_PLAY_DEVICE", "hw:0,0")


# ----------------------------
# TTS
# ----------------------------
def speak(text: str):
    # Delegate to Piper runtime voice engine
    return speak_piper(text)


# ----------------------------
# Capture thread (arecord -> queue)
# ----------------------------
q = queue.Queue(maxsize=32)
stop_evt = threading.Event()


def arecord_reader():
    cmd = [
        "arecord",
        "-D",
        CAPTURE_DEVICE,
        "-f",
        "S16_LE",
        "-c",
        "1",
        "-r",
        str(CAPTURE_RATE),
        "-t",
        "raw",
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while not stop_evt.is_set():
            chunk = p.stdout.read(READ_BYTES)
            if not chunk:
                break
            try:
                q.put_nowait(chunk)
            except queue.Full:
                # drop oldest to keep real-time
                try:
                    _ = q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(chunk)
                except queue.Full:
                    pass
    finally:
        try:
            p.terminate()
        except Exception:
            pass
        try:
            p.wait(timeout=2)
        except Exception:
            pass


# ----------------------------
# Wake/command logic + personality
# ----------------------------
WAKE_VARIANTS = {"chatty", "caddy", "kitty", "charity", "jackie", "jockey", "heidi"}
FILLER_WORDS = {"hey", "hi", "hello", "okay", "ok", "oh", "um", "uh"}

# How long Chatty keeps listening for a follow-up without the wake word
LISTEN_SECONDS = float(os.getenv("CHATTY_LISTEN_SECONDS", "10"))
FOLLOWUP_SECONDS = float(os.getenv("CHATTY_FOLLOWUP_SECONDS", "15"))

GREETINGS = [
    "Hi! What's up?",
    "I'm here. What can I do for you?",
    "Yeah? I'm listening.",
    "Hey there! What's on your mind?",
    "Mm-hm?",
]
GOODBYES = [
    "Okay, I'll be right here.",
    "Sounds good. Just say my name if you need me.",
    "You got it. Talk soon!",
    "Alright, going quiet.",
]
THANKS_REPLIES = [
    "Anytime!",
    "Happy to help!",
    "You're welcome! Say my name if you need me again.",
]
TIMEOUT_LINES = [
    "",  # usually just go quiet
    "",
    "I'll be here if you need me.",
]
ERROR_LINES = [
    "Hmm, I couldn't reach my brain just now. Can you try again in a moment?",
    "Oops, something hiccuped on my end. Mind asking again?",
]
STOP_PHRASES = {"never mind", "nevermind", "thats all", "that is all", "stop", "be quiet",
                "go to sleep", "goodbye", "bye", "nothing", "no thanks"}
THANKS_PHRASES = {"thanks", "thank you", "thanks chatty", "thank you chatty", "cool thanks"}


def pick(lines):
    return random.choice(lines)


def clean_for_speech(text: str) -> str:
    """Remove markdown-ish symbols that sound odd when spoken."""
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"[*_#`>]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    return " ".join(text.split())


def post_chat(text: str, session_id: str) -> str:
    r = requests.post(
        API_URL,
        json={"text": text, "session_id": session_id},
        headers={"X-Chatty-Token": TOKEN},
        timeout=30,
    )
    r.raise_for_status()
    j = r.json()
    reply = j.get("reply", "")
    return reply.strip() if isinstance(reply, str) else str(reply)


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", (s or "").lower()).strip()


def strip_wake(text: str) -> str:
    """Remove wake words and leading filler ('hey', 'okay') from an utterance."""
    words = [w for w in text.split() if w not in WAKE_VARIANTS]
    while words and words[0] in FILLER_WORDS:
        words.pop(0)
    return " ".join(words).strip()


def flush_audio():
    """Drop audio captured while Chatty was talking, so it doesn't hear itself."""
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            break
    rec.Reset()
    wake_rec.Reset()


def say(text: str):
    text = clean_for_speech(text)
    if text:
        print("Chatty:", text, flush=True)
        speak(text)
    flush_audio()


# ----------------------------
# Main
# ----------------------------
print("Loading STT model...", flush=True)
model = Model(MODEL_PATH)
rec = KaldiRecognizer(model, VOSK_RATE)

# A second recognizer that only listens for "Chatty". Restricting it to a few
# phrases makes it far better at catching the wake word than general dictation.
try:
    wake_rec = KaldiRecognizer(model, VOSK_RATE, json.dumps(WAKE_GRAMMAR))
except Exception as e:
    print("Wake grammar unavailable, using dictation only:", e, flush=True)
    wake_rec = None


class _NoWake:
    def AcceptWaveform(self, _): return False
    def Result(self): return "{}"
    def Reset(self): pass


if wake_rec is None:
    wake_rec = _NoWake()

# start capture
t = threading.Thread(target=arecord_reader, daemon=True)
t.start()

say(pick(["Chatty node online. Good to be awake!", "Hello hello! Chatty is up and running."]))
print(
    f"Capture: {CAPTURE_DEVICE} @ {CAPTURE_RATE}Hz -> resample {VOSK_RATE}Hz",
    flush=True,
)
print("Say something. (Wake me by saying 'Chatty ...')", flush=True)

mode = "sleep"          # "sleep" or "active"
active_until = 0.0
session_id = None
wake_heard_at = 0.0


def answer(prompt: str):
    """Send a prompt to the relay, speak the reply, and keep listening for a follow-up."""
    global mode, active_until
    try:
        reply = post_chat(prompt, session_id)
        say(reply or "Hmm, I drew a blank on that one.")
    except Exception as e:
        print("Error:", repr(e), flush=True)
        say(pick(ERROR_LINES))
    mode = "active"
    active_until = time.time() + FOLLOWUP_SECONDS


while True:
    try:
        pcm = q.get(timeout=1.0)
    except queue.Empty:
        pcm = None

    # conversation window ran out with no follow-up
    if mode == "active" and time.time() > active_until:
        mode = "sleep"
        line = pick(TIMEOUT_LINES)
        if line:
            say(line)
        print("(back to sleep)", flush=True)

    if pcm is None:
        continue

    pcm16 = resample_pcm16_mono(pcm, CAPTURE_RATE, VOSK_RATE)
    if RMS_GATE > 0:
        x = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
        if x.size and float(np.sqrt(np.mean(x * x))) < RMS_GATE:
            continue

    # dedicated wake listener runs on the same audio
    if wake_rec.AcceptWaveform(pcm16):
        wake_text = json.loads(wake_rec.Result()).get("text", "")
        if "chatty" in wake_text:
            print("Wake listener heard:", wake_text, flush=True)
            wake_heard_at = time.time()

    if not rec.AcceptWaveform(pcm16):
        continue

    res = json.loads(rec.Result())
    text = normalize(res.get("text", ""))
    if not text:
        continue

    print("Heard:", text, flush=True)
    words = set(text.split())
    woke = bool(words & WAKE_VARIANTS) or (time.time() - wake_heard_at < WAKE_MEMORY_SECONDS)
    if woke:
        wake_heard_at = 0.0
    prompt = strip_wake(text)

    if mode == "sleep":
        if not woke:
            continue
        session_id = uuid.uuid4().hex  # fresh conversation
        if prompt:
            # "Chatty, what's the weather?" -> answer right away
            answer(prompt)
        else:
            # just "Chatty" -> greet and listen
            say(pick(GREETINGS))
            mode = "active"
            active_until = time.time() + LISTEN_SECONDS
        continue

    # mode == "active": no wake word needed
    if not prompt:
        if woke:
            say(pick(["Still here!", "Yep?", "I'm listening."]))
            active_until = time.time() + LISTEN_SECONDS
        continue

    if prompt in STOP_PHRASES:
        say(pick(GOODBYES))
        mode = "sleep"
        continue

    if prompt in THANKS_PHRASES:
        say(pick(THANKS_REPLIES))
        mode = "sleep"
        continue

    answer(prompt)

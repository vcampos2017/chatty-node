import os, json, queue, subprocess, time, re, threading, random, uuid, socket
import sys

sys.path.insert(0, os.path.dirname(__file__))  # allow importing src siblings
from tts_piper import speak as speak_piper  # Piper TTS
import local_skills  # time, date, weather, greenhouse answered on the Pi
import face_link as face  # tells the face what's happening (never blocks)
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
CAPTURE_DEVICE = os.getenv("CHATTY_CAPTURE_DEVICE", "plughw:CARD=PowerConf,DEV=0")
# Capture straight at the recognizer rate; the "plughw" device resamples cleanly in ALSA.
CAPTURE_RATE = int(os.getenv("CHATTY_CAPTURE_RATE", str(VOSK_RATE)))

# How many bytes to read per loop from arecord stdout
READ_BYTES = int(os.getenv("CHATTY_READ_BYTES", "4096"))
# 0 = feed all audio to the recognizer (best accuracy). Dropping quiet chunks
# clips the soft edges of words, so only raise this if CPU is a problem.
RMS_GATE = float(os.getenv("CHATTY_RMS_GATE", "0"))
# Phrases the dedicated wake-word listener is restricted to.
WAKE_GRAMMAR = ["chatty", "hey chatty", "okay chatty", "hi chatty", "[unk]"]
# How sure the recognizer must be that it heard "chatty" (0..1). Raise if
# background speech (TV) wakes Chatty; lower if it misses you.
WAKE_MIN_CONF = float(os.getenv("CHATTY_WAKE_MIN_CONF", "0.85"))
# Quiet mode: 0 turns off voice wake entirely (tap the screen to wake).
VOICE_WAKE = os.getenv("CHATTY_VOICE_WAKE", "1") != "0"

# TTS output device (aplay)
PLAY_DEVICE = os.getenv("CHATTY_PLAY_DEVICE", "plughw:CARD=PowerConf,DEV=0")


# ----------------------------
# TTS
# ----------------------------
def speak(text: str):
    # Delegate to Piper runtime voice engine
    return speak_piper(text, on_level=face.level)  # mouth follows the voice


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
# After "Chatty", how long to wait for the question to start
LISTEN_SECONDS = float(os.getenv("CHATTY_LISTEN_SECONDS", "8"))
# Longest a single question may run; caps run-on sentences when a TV is talking
COMMAND_MAX_SECONDS = float(os.getenv("CHATTY_COMMAND_MAX_SECONDS", "7"))
# Keep listening for a follow-up (no wake word) after replying. 0 = off.
# Off by default: with a TV or other people talking it would treat that as questions.
FOLLOWUP_SECONDS = float(os.getenv("CHATTY_FOLLOWUP_SECONDS", "0"))

GREETINGS = [
    "Yes?",
    "Hi! What's up?",
    "I'm listening.",
    "Mm-hm?",
    "What can I do for you?",
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
        face.state("speaking")
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
    wake_rec.SetWords(True)  # per-word confidence scores
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
print("Say something. (Wake me by saying 'Chatty ...')" if VOICE_WAKE
      else "Quiet mode: voice wake is off. Tap the screen to wake me.", flush=True)
face.state("idle")

# Wake requests from the touchscreen face (tap to wake)
VOICE_PORT = int(os.getenv("CHATTY_VOICE_PORT", "47475"))
tap_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
tap_sock.bind(("127.0.0.1", VOICE_PORT))
tap_sock.setblocking(False)


def tapped() -> bool:
    """True if the face was tapped since we last checked."""
    hit = False
    while True:
        try:
            data, _ = tap_sock.recvfrom(64)
        except (BlockingIOError, OSError):
            return hit
        if data.strip() == b"wake":
            hit = True


def wake_up(source: str):
    global session_id
    print(f"Wake ({source})", flush=True)
    session_id = uuid.uuid4().hex  # fresh conversation
    say(pick(GREETINGS))
    start_listening(LISTEN_SECONDS)


mode = "sleep"          # "sleep" or "active"
active_until = 0.0      # active mode ends if no question starts by then
heard_started = 0.0     # when the current question's audio began (for the cap)
session_id = None


def start_listening(seconds: float):
    """Discard whatever was mid-recognition (e.g. TV audio) and listen fresh."""
    global mode, active_until, heard_started
    rec.Reset()
    mode = "active"
    active_until = time.time() + seconds
    heard_started = 0.0
    face.state("listening")


def go_to_sleep():
    """Back to waiting for the wake word."""
    global mode
    mode = "sleep"
    face.state("idle")


def answer(prompt: str):
    """Send a prompt to the relay and speak the reply."""
    global mode
    face.state("thinking")
    try:
        reply = local_skills.handle(prompt)  # free, on-device answers first
        if reply is not None:
            print("(answered locally)", flush=True)
        else:
            reply = post_chat(prompt, session_id)
        say(reply or "Hmm, I drew a blank on that one.")
    except Exception as e:
        print("Error:", repr(e), flush=True)
        face.state("puzzled")
        time.sleep(0.8)
        say(pick(ERROR_LINES))
    if FOLLOWUP_SECONDS > 0:
        start_listening(FOLLOWUP_SECONDS)
    else:
        go_to_sleep()


def handle_command(text: str):
    """Handle one finished utterance heard while active."""
    global mode
    print("Heard:", text, flush=True)
    prompt = strip_wake(text)
    if not prompt:
        start_listening(LISTEN_SECONDS)  # they just said "Chatty" again
        return
    if prompt in STOP_PHRASES:
        say(pick(GOODBYES))
        go_to_sleep()
        return
    if prompt in THANKS_PHRASES:
        say(pick(THANKS_REPLIES))
        go_to_sleep()
        return
    answer(prompt)


while True:
    try:
        pcm = q.get(timeout=0.5)
    except queue.Empty:
        pcm = None

    now = time.time()

    if tapped():
        if mode == "sleep":
            wake_up("tap")
        else:
            start_listening(LISTEN_SECONDS)  # tap again = "I'm talking to you"
        continue

    if mode == "active":
        # question ran too long (TV talking over it): take what we have
        if heard_started and now - heard_started > COMMAND_MAX_SECONDS:
            text = normalize(json.loads(rec.FinalResult()).get("text", ""))
            rec.Reset()
            heard_started = 0.0
            if text:
                handle_command(text)
                continue
        # nobody asked anything
        elif not heard_started and now > active_until:
            line = pick(TIMEOUT_LINES)
            if line:
                say(line)
            go_to_sleep()
            print("(back to sleep)", flush=True)

    if pcm is None:
        continue

    pcm16 = resample_pcm16_mono(pcm, CAPTURE_RATE, VOSK_RATE)
    if RMS_GATE > 0:
        x = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
        if x.size and float(np.sqrt(np.mean(x * x))) < RMS_GATE:
            continue

    if mode == "sleep":
        # Asleep: only the dedicated wake listener runs, and nothing is logged.
        if VOICE_WAKE and wake_rec.AcceptWaveform(pcm16):
            words = json.loads(wake_rec.Result()).get("result", [])
            confs = [w.get("conf", 0.0) for w in words if w.get("word") == "chatty"]
            if confs:
                best = max(confs)
                if best >= WAKE_MIN_CONF:
                    wake_up(f"wake word, confidence {best:.2f}")
                else:
                    print(f"(ignored possible wake word, confidence {best:.2f})", flush=True)
        continue

    # Active: transcribe the question
    if rec.AcceptWaveform(pcm16):
        text = normalize(json.loads(rec.Result()).get("text", ""))
        heard_started = 0.0
        if text:
            handle_command(text)
    elif not heard_started and json.loads(rec.PartialResult()).get("partial"):
        heard_started = now  # speech has begun; start the length cap

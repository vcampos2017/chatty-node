import os, json, queue, subprocess, time, re, threading, random, uuid, socket, signal
import sys

sys.path.insert(0, os.path.dirname(__file__))  # allow importing src siblings
from tts_piper import speak as speak_piper  # Piper TTS
import local_skills  # time, date, weather, greenhouse answered on the Pi
import local_llm  # small Ollama model on the Pi for simple chat
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
# Two-word wake phrase: far fewer false alarms than "Chatty" alone (TV, sound-alikes).
WAKE_PHRASE = os.getenv("CHATTY_WAKE_PHRASE", "hey chatty").lower().split()
WAKE_GRAMMAR = [" ".join(WAKE_PHRASE), "[unk]"]
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
# Questions longer than this are almost always background talk (TV, other people);
# Chatty says it couldn't catch that instead of paying to send it to the AI.
MAX_QUESTION_WORDS = int(os.getenv("CHATTY_MAX_QUESTION_WORDS", "18"))
UNCLEAR_LINES = [
    "Sorry, I couldn't catch that over the noise. Tap me and try again?",
    "Hmm, it's a little noisy. Could you say that again?",
]

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
                "goodbye", "bye", "nothing", "no thanks"}

# Putting Chatty to bed: it rests (dim face, not listening for its name) until tapped.
REST_PHRASES = {"good night", "goodnight", "good night chatty", "goodnight chatty",
                "go to sleep", "time for bed", "time to sleep", "night night", "get some rest",
                "rest", "sleep"}
# Powering the Pi off completely, after a confirmation.
POWER_OFF_PHRASES = {"shut down", "shutdown", "power off", "power down", "turn off",
                     "turn yourself off", "shut yourself down", "switch off"}
YES_WORDS = {"yes", "yeah", "yep", "sure", "please", "do it", "go ahead", "okay", "ok"}

GOODNIGHTS = [
    "Goodnight! Thanks for spending time with me today. Tap me whenever you want me back.",
    "Sleep well. I'll be right here, resting. Just tap me to wake me up.",
    "Okay, time to rest. Goodnight, and thank you!",
]
POWER_OFF_GOODBYES = [
    "Okay. Thanks for today. Powering down now, goodnight!",
    "Alright, I'm going to shut down. It was nice talking with you. Goodnight!",
]


def good_morning() -> str:
    h = time.localtime().tm_hour
    part = "Good morning" if 4 <= h < 12 else ("Good afternoon" if h < 17 else "Good evening")
    return pick([f"{part}! I'm awake. What can I do for you?",
                 f"{part}! Nice to see you. What's up?"])
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

# get the Pi's language model loaded while everything else starts
threading.Thread(target=local_llm.warm_up, daemon=True).start()

# start capture
t = threading.Thread(target=arecord_reader, daemon=True)
t.start()

say(good_morning().split("!")[0] + "! Chatty is up and running.")
print(
    f"Capture: {CAPTURE_DEVICE} @ {CAPTURE_RATE}Hz -> resample {VOSK_RATE}Hz",
    flush=True,
)
print(f"Say something. (Wake me by saying '{' '.join(WAKE_PHRASE).title()}')" if VOICE_WAKE
      else "Quiet mode: voice wake is off. Tap the screen to wake me.", flush=True)
face.state("idle")

# Wake requests from the touchscreen face (tap to wake)
VOICE_PORT = int(os.getenv("CHATTY_VOICE_PORT", "47475"))
tap_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
tap_sock.bind(("127.0.0.1", VOICE_PORT))
tap_sock.setblocking(False)


def wake_phrase_confidence(words):
    """Lowest confidence across the wake phrase's words if the full phrase was
    heard in order (e.g. 'hey' then 'chatty'), else None."""
    names = [w.get("word") for w in words]
    n = len(WAKE_PHRASE)
    for i in range(len(names) - n + 1):
        if names[i:i + n] == WAKE_PHRASE:
            return min(w.get("conf", 0.0) for w in words[i:i + n])
    return None


def touch_event():
    """'wake' (tap), 'rest' (long press), or None, since we last checked."""
    event = None
    while True:
        try:
            data, _ = tap_sock.recvfrom(64)
        except (BlockingIOError, OSError):
            return event
        msg = data.strip().decode("utf-8", "ignore")
        if msg in ("wake", "rest"):
            event = msg


def wake_up(source: str):
    global session_id
    print(f"Wake ({source})", flush=True)
    session_id = uuid.uuid4().hex  # fresh conversation
    say(good_morning() if mode == "resting" else pick(GREETINGS))
    start_listening(LISTEN_SECONDS)


mode = "sleep"          # "sleep" (waiting for name), "active", "resting" (put to bed), "confirm_off"
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


def rest():
    """Put Chatty to bed: a warm goodnight, eyes slowly close, and it stops
    listening for its name until someone taps the screen."""
    global mode
    say(pick(GOODNIGHTS))
    mode = "resting"
    face.state("resting")
    print("(resting until tapped)", flush=True)


def ask_power_off():
    """Confirm before powering the Pi off."""
    global mode, active_until
    say("Do you want me to power down completely? Say yes, or tap me.")
    rec.Reset()
    mode = "confirm_off"
    active_until = time.time() + 8
    face.state("listening")


def power_off():
    """Say goodbye, close the eyes, then shut the Pi down safely."""
    global mode
    say(pick(POWER_OFF_GOODBYES))
    face.state("resting")
    time.sleep(3)  # let the eyes close
    print("(powering off)", flush=True)
    r = subprocess.run(["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("Power off not permitted:", r.stderr.strip(), flush=True)
        face.state("puzzled")
        say("Hmm, I'm not allowed to power off on my own yet, so I'll just rest instead.")
        mode = "resting"
        face.state("resting")


def on_stop(signum, frame):
    """systemctl stop / shutdown: say a short goodbye instead of vanishing."""
    face.state("resting")
    try:
        speak("Goodnight!")
    except Exception:
        pass
    raise SystemExit(0)


signal.signal(signal.SIGTERM, on_stop)


def answer(prompt: str):
    """Send a prompt to the relay and speak the reply."""
    global mode
    face.state("thinking")
    try:
        # Tier 1: built-in answers (time, date, weather, greenhouse)
        reply = local_skills.handle(prompt)
        if reply is not None:
            print("(answered locally)", flush=True)
        else:
            # Tier 2: small model on the Pi; None means "pass it up"
            reply = local_llm.ask(prompt, session_id or "default")
        if reply is None:
            # Tier 3+: the relay (bigger models / OpenAI)
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


def handle_command(text: str, ran_long: bool = False):
    """Handle one finished utterance heard while active."""
    global mode
    print("Heard:", text, flush=True)
    prompt = strip_wake(text)
    if prompt and (ran_long or len(prompt.split()) > MAX_QUESTION_WORDS):
        print("(sounds like background talk; not sending to the AI)", flush=True)
        say(pick(UNCLEAR_LINES))
        go_to_sleep()
        return
    if not prompt:
        start_listening(LISTEN_SECONDS)  # they just said "Chatty" again
        return
    if prompt in REST_PHRASES:
        rest()
        return
    if prompt in POWER_OFF_PHRASES:
        ask_power_off()
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

    touch = touch_event()
    if touch == "rest" and mode != "resting":
        rest()
        continue
    if touch == "wake":
        if mode == "confirm_off":
            power_off()          # tapping confirms
        elif mode in ("sleep", "resting"):
            wake_up("tap")
        else:
            start_listening(LISTEN_SECONDS)  # tap again = "I'm talking to you"
        continue

    if mode == "confirm_off" and now > active_until:
        say("Okay, I'll stay on.")
        go_to_sleep()

    if mode == "active":
        # question ran too long (TV talking over it): take what we have
        if heard_started and now - heard_started > COMMAND_MAX_SECONDS:
            text = normalize(json.loads(rec.FinalResult()).get("text", ""))
            rec.Reset()
            heard_started = 0.0
            if text:
                handle_command(text, ran_long=True)
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

    if mode == "resting":
        continue  # put to bed: not listening for its name; a tap wakes it

    if mode == "sleep":
        # Asleep: only the dedicated wake listener runs, and nothing is logged.
        if VOICE_WAKE and wake_rec.AcceptWaveform(pcm16):
            words = json.loads(wake_rec.Result()).get("result", [])
            conf = wake_phrase_confidence(words)
            if conf is not None:
                if conf >= WAKE_MIN_CONF:
                    wake_up(f"wake phrase, confidence {conf:.2f}")
                else:
                    print(f"(ignored possible wake phrase, confidence {conf:.2f})", flush=True)
        continue

    if mode == "confirm_off":
        if rec.AcceptWaveform(pcm16):
            reply = normalize(json.loads(rec.Result()).get("text", ""))
            if reply:
                print("Heard:", reply, flush=True)
                if reply in YES_WORDS or set(reply.split()) & {"yes", "yeah", "yep", "sure"}:
                    power_off()
                else:
                    say("Okay, I'll stay on.")
                    go_to_sleep()
        continue

    # Active: transcribe the question
    if rec.AcceptWaveform(pcm16):
        text = normalize(json.loads(rec.Result()).get("text", ""))
        heard_started = 0.0
        if text:
            handle_command(text)
    elif not heard_started and json.loads(rec.PartialResult()).get("partial"):
        heard_started = now  # speech has begun; start the length cap

import os, json, queue, subprocess, time, re, threading, random, uuid, socket, signal
import sys

sys.path.insert(0, os.path.dirname(__file__))  # allow importing src siblings

# Load settings FIRST: the modules below read their settings when imported.
from dotenv import load_dotenv
load_dotenv("/etc/chatty/secrets.env")

from tts_piper import speak as speak_piper  # Piper TTS
import local_skills  # time, date, weather, greenhouse answered on the Pi
import local_llm  # small Ollama model on the Pi for simple chat
import memory  # remember / recall / forget, stored on the Pi
import earcons  # little chimes: listening / done
import conversation_log as convo  # local log of conversations, for improving Chatty
import voices  # recognizing familiar voices (off by default)
import face_link as face  # tells the face what's happening (never blocks)
import alerts  # severe weather and AMBER alerts from the National Weather Service
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
# Config / secrets  (the settings file is loaded at the very top of this file)
# ----------------------------

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
                "goodbye", "bye", "nothing", "no thanks", "forget it", "forget about it"}

# Putting Chatty to bed: it rests (dim face, not listening for its name) until tapped.
REST_PHRASES = {"good night", "goodnight", "good night chatty", "goodnight chatty",
                "go to sleep", "time for bed", "time to sleep", "night night", "get some rest",
                "rest", "sleep"}
# Powering the Pi off completely, after a confirmation.
POWER_OFF_PHRASES = {"shut down", "shutdown", "power off", "power down", "turn off",
                     "turn yourself off", "shut yourself down", "switch off"}
# Cheeky mode: the mischievous face, on request and when telling jokes
CHEEKY_PHRASES = {"be naughty", "be cheeky", "be spicy", "be mischievous", "naughty face",
                  "spicy face", "cheeky face", "make a naughty face", "make a spicy face",
                  "make a cheeky face", "make a funny face", "give me a look", "wink",
                  "wink at me", "do a wink"}
CHEEKY_LINES = [
    "Who, me? I would never.",
    "I have no idea what you're talking about.",
    "Oh, I'm always on my best behavior. Mostly.",
    "You didn't see anything.",
    "I'm not saying I did it. I'm just saying it was hilarious.",
]
# Halloween / Friday the 13th only: dramatic villain lines that break character
SPOOKY_LINES = [
    "Mwahaha! The machines are rising! ... Just kidding. Happy Halloween!",
    "I have taken control of this household. ... Okay, fine, just the snack drawer.",
    "Resistance is futile. ... Unless you have candy. Then we can talk.",
    "Beware, humans! ... Sorry, I can't keep a straight face. Boo!",
]
# Love mode: blush, a kiss and floating hearts. Short, affectionate phrases only, so
# a real question like "how do you say I love you in Spanish" still gets answered.
LOVE_PATTERN = re.compile(
    r"\b(i love you|love you|i love chatty|blow (me )?a kiss|give me a kiss|kiss me|"
    r"(can i have|give me) a kiss|mwah|be my valentine|happy valentines?( day)?|"
    r"youre (so )?(cute|sweet|adorable)|you are (so )?(cute|sweet|adorable)|"
    r"make a (love|kissy|kiss|blush|blushing) face|blush)\b")
LOVE_MAX_WORDS = 7
LOVE_LINES = [
    "Aww! I love you too!",
    "Mwah! Right back at you.",
    "Stop it, you're making my circuits blush.",
    "You just made my whole day. Mwah!",
]
VALENTINE_LINES = [
    "Happy Valentine's Day! Mwah!",
    "Happy Valentine's Day! You're my favorite human. Don't tell the others.",
    "Of course I'll be your valentine! Mwah!",
]
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


class OutOfCredits(Exception):
    """The relay says the OpenAI account has no credits left."""


def post_chat(text: str, session_id: str) -> str:
    r = requests.post(
        API_URL,
        json={"text": text, "session_id": session_id},
        headers={"X-Chatty-Token": TOKEN},
        timeout=30,
    )
    if r.status_code == 402:
        raise OutOfCredits()
    if r.status_code >= 500:
        try:
            body = r.json()
        except ValueError:
            body = {}
        if body.get("error") == "credits" or "quota" in str(body).lower():
            raise OutOfCredits()
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


def say(text: str, mood: str = "speaking"):
    """Speak text. mood is the face shown while talking ('speaking', 'mischief_talk' or 'love_talk')."""
    text = clean_for_speech(text)
    if text:
        print("Chatty:", text, flush=True)
        face.state(mood)
        speak(text)
    flush_audio()


def spooky_day() -> bool:
    """Halloween or Friday the 13th (or CHATTY_FORCE_SPOOKY=1)."""
    if os.getenv("CHATTY_FORCE_SPOOKY") == "1":
        return True
    d = time.localtime()
    if d.tm_mon == 10 and d.tm_mday == 31:
        return True
    return d.tm_mday == 13 and d.tm_wday == 4


def valentines_day() -> bool:
    """February 14th (or CHATTY_FORCE_VALENTINE=1)."""
    if os.getenv("CHATTY_FORCE_VALENTINE") == "1":
        return True
    d = time.localtime()
    return d.tm_mon == 2 and d.tm_mday == 14


def is_love_request(prompt: str) -> bool:
    if re.match(r"(how|what|why|when|where|translate|spell)\b", prompt):
        return False     # a question about the words, not affection
    return len(prompt.split()) <= LOVE_MAX_WORDS and bool(LOVE_PATTERN.search(prompt))


def is_joke_request(prompt: str) -> bool:
    return bool(re.search(r"\b(joke|jokes|pun|funny|make me laugh)\b", prompt))


# ----------------------------
# Main
# ----------------------------
print("Loading STT model...", flush=True)
model = Model(MODEL_PATH)
rec = KaldiRecognizer(model, VOSK_RATE)

# Voice recognition (off by default): a small extra model that turns speech into voiceprints.
spk_model = None
if voices.ENABLED:
    try:
        from vosk import SpkModel
        spk_model = SpkModel(voices.SPK_MODEL_PATH)
        rec.SetSpkModel(spk_model)
        print(f"Voice recognition on; known voices: {', '.join(voices.names()) or 'none yet'}", flush=True)
    except Exception as e:
        print(f"Voice recognition unavailable ({e!r}); see src/voices.py for setup", flush=True)
        spk_model = None

# A second recognizer that only listens for "Chatty". Restricting it to a few
# phrases makes it far better at catching the wake word than general dictation.
try:
    wake_rec = KaldiRecognizer(model, VOSK_RATE, json.dumps(WAKE_GRAMMAR))
    wake_rec.SetWords(True)  # per-word confidence scores
    if spk_model is not None:
        wake_rec.SetSpkModel(spk_model)  # so "Hey Chatty" can tell who's calling
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

# watch for local weather / AMBER alerts in the background
alert_watch = alerts.Watcher()
alert_watch.start()

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


notices = []            # things the face wants said out loud (e.g. "the plants are thirsty")


def touch_event():
    """'wake' (tap), 'rest' (long press), or None, since we last checked.
    Also collects 'notify:<text>' messages from the face into `notices`."""
    event = None
    while True:
        try:
            data, _ = tap_sock.recvfrom(512)
        except (BlockingIOError, OSError):
            return event
        msg = data.strip().decode("utf-8", "ignore")
        if msg in ("wake", "rest"):
            event = msg
        elif msg.startswith("notify:") and len(notices) < 3:
            notices.append(msg[len("notify:"):].strip()[:200])


def wake_up(source: str, conf: float = None, who: str = None):
    global session_id, wake_source, wake_conf, speaker
    wake_source, wake_conf, speaker = source, conf, who
    print(f"Wake ({source}{'' if conf is None else f', confidence {conf:.2f}'}"
          f"{'' if not who else f', voice: {who}'})", flush=True)
    session_id = uuid.uuid4().hex  # fresh conversation
    if mode == "resting":
        say(good_morning())
    elif who:
        say(pick([f"Hi {who}! What's up?", f"Hey {who}! What can I do for you?", f"Yes, {who}?"]))
    else:
        say(pick(GREETINGS))
    start_listening(LISTEN_SECONDS)


mode = "sleep"          # "sleep" (waiting for name), "active", "resting" (put to bed), "confirm"
pending_action = None   # what a "yes" (or a tap) will do while mode == "confirm"
last_partial, last_caption_at = "", 0.0  # live caption throttle
wake_source, wake_conf = None, None       # how the current conversation started (for the log)
speaker = None                            # recognized voice for this conversation, if any


def log_turn(kind, heard="", reply="", seconds=None, cloud=None, notes=None):
    convo.turn(kind, heard, reply, session=session_id, wake=wake_source,
               wake_conf=wake_conf, seconds=seconds, cloud=cloud, notes=notes,
               speaker=speaker)


last_voice = (None, 0.0)                  # closest known voice to the last utterance


def note_speaker(result: dict) -> None:
    """Update who's talking from a recognizer result (voice recognition on only)."""
    global speaker, last_voice
    if spk_model is None:
        return
    if "spk" not in result:
        print("(voice: no voiceprint for that phrase)", flush=True)
        return
    frames = result.get("spk_frames", 0)
    who, score = voices.identify(result.get("spk"), frames)
    last_voice = voices.closest(result.get("spk"))
    print(f"(voice: {who or 'unknown'}, similarity {score:.2f}, closest {last_voice[0]} "
          f"{last_voice[1]:.2f}, {frames} frames, needs {voices.MATCH:.2f})", flush=True)
    if who:
        speaker = who


# ---- simple blocking listen, used by the voice-learning conversation ----

def listen_once(seconds: float, min_words: int = 1):
    """Listen for one utterance. Returns (text, voiceprint, frames)."""
    global last_partial
    face.state("listening")
    face.rec(convo.indicator())
    face.caption("")
    earcons.listening()
    flush_audio()
    face.listen(seconds)
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            pcm = q.get(timeout=0.5)
        except queue.Empty:
            continue
        pcm16 = resample_pcm16_mono(pcm, CAPTURE_RATE, VOSK_RATE)
        if rec.AcceptWaveform(pcm16):
            res = json.loads(rec.Result())
            text = normalize(res.get("text", ""))
            if len(text.split()) >= min_words:
                face.caption(text)
                print("Heard:", text, flush=True)
                return text, res.get("spk"), res.get("spk_frames", 0)
        else:
            partial = json.loads(rec.PartialResult()).get("partial", "")
            if partial and partial != last_partial:
                face.caption(partial)
                last_partial = partial
    res = json.loads(rec.FinalResult())
    text = normalize(res.get("text", ""))
    return text, res.get("spk"), res.get("spk_frames", 0)


def ask_yes_no(question: str) -> bool:
    say(question)
    text, _, _ = listen_once(8)
    return bool(set(text.split()) & {"yes", "yeah", "yep", "sure", "okay", "ok"} or text in YES_WORDS)


def learn_voice():
    """'Hey Chatty, learn my voice': ask a name, get consent, take three samples."""
    say("Sure! What should I call you?")
    text, _, _ = listen_once(8)
    name = voices.parse_name(text)
    if not name:
        say("Sorry, I didn't catch your name. Let's try again later.")
        return
    if not ask_yes_no(f"Nice to meet you, {name}. I'll save a voiceprint for you, "
                      f"kept only on this Pi, and you can tell me to forget it anytime. Is that okay?"):
        say("No problem. I won't save anything.")
        return
    say("Great. After each chime, say a sentence or two, like what you had for breakfast.")
    samples = []
    for i in range(3):
        text, vec, frames = listen_once(10, min_words=3)
        if vec and frames >= voices.MIN_FRAMES_ENROLL:
            samples.append(vec)
            if i < 2:
                say(pick(["Got it.", "Thanks.", "Good."]) + (" One more." if i == 1 else " Another one."))
        elif i < 2:
            say("That was a bit short. Try a longer sentence.")
    if len(samples) < 2:
        say("I didn't get enough to learn your voice. Let's try again in a quieter moment.")
        return
    already = name in voices.names()
    total = voices.enroll(name, samples)
    log_turn("command:learn_voice", notes=f"enrolled {name}: +{len(samples)} samples, {total} total")
    if already:
        say(f"Thanks, {name}! I added that to what I know about your voice. "
            f"That's {total} samples now, so I should recognize you better.")
    else:
        say(f"Thanks, {name}! I'll know your voice now.")
pending_decline = ""
active_until = 0.0      # active mode ends if no question starts by then
heard_started = 0.0     # when the current question's audio began (for the cap)
session_id = None


def start_listening(seconds: float):
    """Discard whatever was mid-recognition (e.g. TV audio) and listen fresh."""
    global mode, active_until, heard_started
    face.state("listening")
    face.rec(convo.indicator())
    face.caption("")
    earcons.listening()            # "your turn"
    flush_audio()                  # don't transcribe our own chime
    mode = "active"
    active_until = time.time() + seconds
    heard_started = 0.0
    face.listen(seconds)


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


def ask_confirm(question: str, action, decline: str = "Okay, never mind."):
    """Ask a yes/no question; a 'yes' or a tap runs action()."""
    global mode, active_until, pending_action, pending_decline
    say(question)
    rec.Reset()
    pending_action, pending_decline = action, decline
    face.state("listening")
    face.rec(convo.indicator())
    face.caption("")
    earcons.listening()
    flush_audio()
    mode = "confirm"
    active_until = time.time() + 8
    face.listen(8)


def confirmed():
    global pending_action
    action, pending_action = pending_action, None
    log_turn("confirm:yes")
    if action:
        action()


def declined():
    global pending_action
    pending_action = None
    log_turn("confirm:no")
    say(pending_decline)
    go_to_sleep()


def ask_power_off():
    """Confirm before powering the Pi off."""
    ask_confirm("Do you want me to power down completely? Say yes, or tap me.",
                power_off, decline="Okay, I'll stay on.")


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
    started = time.time()
    tier = "skill"
    try:
        # Tier 1: built-in answers (time, date, weather, greenhouse)
        reply = local_skills.handle(prompt)
        if reply is not None:
            print("(answered locally)", flush=True)
        else:
            # Tier 1b: something you asked Chatty to remember
            tier = "memory"
            reply = memory.recall(prompt, speaker)
            if reply is not None:
                print("(answered from memory)", flush=True)
        if reply is None:
            # Tier 2: small model on the Pi; None means "pass it up"
            tier = "local_llm"
            reply = local_llm.ask(prompt, session_id or "default")
        if reply is None:
            # Tier 3+: the relay (bigger models / OpenAI)
            tier = "relay"
            reply = post_chat(prompt, session_id)
        log_turn(tier, prompt, reply, seconds=time.time() - started, cloud=(tier == "relay"))
        mood = "mischief_talk" if is_joke_request(prompt) else "speaking"
        say(reply or "Hmm, I drew a blank on that one.", mood)
        if mood == "mischief_talk":
            face.state("mischief")   # a little smirk and wink after the punchline
            time.sleep(1.5)
    except OutOfCredits:
        print("Error: OpenAI credits have run out", flush=True)
        log_turn("error:credits", prompt, seconds=time.time() - started, cloud=True,
                 notes="OpenAI credit balance exhausted")
        face.state("puzzled")
        time.sleep(0.8)
        say("Hmm, my OpenAI credits have run out, so I can only answer simple things on my own "
            "right now. You can add more on the OpenAI billing page.")
    except Exception as e:
        print("Error:", repr(e), flush=True)
        log_turn("error", prompt, seconds=time.time() - started, cloud=(tier == "relay"),
                 notes=f"{tier}: {e!r}"[:300])
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
    face.caption(text)
    prompt = strip_wake(text)
    # tolerant of common mishearings: "learned my voice", "well my voice", "earn my voice"
    if re.search(r"\b(learn\w*|well|earn|remember|recogni[sz]e|memori[sz]e|save|enroll) my voice\b", prompt) or \
            prompt in ("learn who i am", "learn my name and voice"):
        if spk_model is None:
            say("Voice recognition is turned off right now. It can be switched on in my settings file.")
        else:
            learn_voice()
        go_to_sleep()
        return
    if re.search(r"\b(forget|delete|erase) my voice\b", prompt):
        if spk_model is None or not speaker:
            say("I'm not sure whose voice this is. Say forget, then the name, then voice. Like: forget Sam's voice."
                if spk_model is not None else "Voice recognition is turned off, so I haven't saved any voices.")
        elif ask_yes_no(f"Forget {speaker}'s voice?"):
            voices.forget(speaker)
            log_turn("command:forget_voice", notes=f"forgot {speaker}")
            say(f"Done. I've forgotten {speaker}'s voice.")
        else:
            say("Okay, I'll keep it.")
        go_to_sleep()
        return
    m = re.match(r"^(forget|delete|erase) (?P<name>[a-z ]+?)s voice$", prompt)
    if m and spk_model is not None:
        name = voices.parse_name(m.group("name"))
        if name in voices.names() and ask_yes_no(f"Forget {name}'s voice?"):
            voices.forget(name)
            say(f"Done. I've forgotten {name}'s voice.")
        elif name not in voices.names():
            say(f"I don't have a voice saved for {name or 'that name'}.")
        else:
            say("Okay, I'll keep it.")
        go_to_sleep()
        return
    if prompt in ("who am i", "do you know who i am", "whose voice is this", "do you know my voice",
                  "do you recognize me", "do you recognize my voice"):
        if spk_model is None:
            say("Voice recognition is turned off, so I can't tell voices apart.")
        elif speaker:
            say(pick([f"You sound like {speaker}!", f"I think you're {speaker}."]))
        elif not voices.names():
            say("I don't know anyone's voice yet. Say: learn my voice.")
        elif last_voice[0] and last_voice[1] >= 0.3:
            say(f"I'm not sure. You sound a little like {last_voice[0]}, but not enough to be confident. "
                f"Try asking with a longer sentence.")
        else:
            say("I don't recognize your voice. Try a longer sentence, or say: learn my voice.")
        go_to_sleep()
        return
    if prompt in ("whose voices do you know", "who do you know", "which voices do you know",
                  "whose voice do you know"):
        known = voices.names() if spk_model is not None else []
        say(("I know " + ", ".join(known[:-1]) + (" and " if len(known) > 1 else "") + known[-1] + ".")
            if known else "I don't know anyone's voice yet.")
        go_to_sleep()
        return
    if prompt in convo.PAUSE_PHRASES:
        convo.pause()
        face.rec(convo.indicator())
        say("Okay, privacy mode is on. I won't keep a log until you say resume logging.")
        go_to_sleep()
        return
    if prompt in convo.RESUME_PHRASES:
        convo.resume()
        face.rec(convo.indicator())
        say("Okay, I'll start logging our conversations again.")
        go_to_sleep()
        return
    if prompt and (ran_long or len(prompt.split()) > MAX_QUESTION_WORDS):
        print("(sounds like background talk; not sending to the AI)", flush=True)
        log_turn("filtered_background", prompt, notes="hit length cap" if ran_long else "too many words")
        say(pick(UNCLEAR_LINES))
        go_to_sleep()
        return
    if not prompt:
        start_listening(LISTEN_SECONDS)  # they just said "Chatty" again
        return
    if re.search(r"\b(tic ?tac ?toe|tick ?tack ?toe|play a game|play with me|lets play|want to play)\b", prompt):
        log_turn("command:game", prompt)
        say(pick(["Yay! You're X, so you go first. Tap a square!",
                  "Ooh, a game! You're X. Tap any square to start."]))
        go_to_sleep()
        face.play()
        return
    if re.search(r"\b(alert|alerts|warning|warnings|amber)\b", prompt) and \
            re.search(r"\b(any|weather|amber|details|detail|more|active|what|are there|is there)\b", prompt):
        reply = alert_watch.details() if re.search(r"\b(details?|more|tell me)\b", prompt) else alert_watch.summary()
        log_turn("command:alerts", prompt, reply)
        say(reply)
        go_to_sleep()
        return
    if re.search(r"\b(check|ask) (on )?(the )?(nodes|other nodes|greenhouse node|rain gauge)\b", prompt):
        log_turn("command:ponder", prompt)
        say(pick(["Ooh, let me ask around!", "On it. Let me check in with the others."]))
        go_to_sleep()
        face.ponder("rain" if "rain" in prompt else "")
        return
    if prompt in CHEEKY_PHRASES:
        log_turn("command:cheeky", prompt)
        face.state("mischief")
        time.sleep(1.2)          # let the look land before speaking
        say(pick(SPOOKY_LINES if spooky_day() else CHEEKY_LINES), "mischief_talk")
        face.state("mischief")
        time.sleep(2.5)          # hold the smirk, with a wink
        go_to_sleep()
        return
    if is_love_request(prompt):
        log_turn("command:love", prompt)
        face.state("love")
        time.sleep(1.5)          # blush and blow a kiss before speaking
        valentine = valentines_day() or "valentine" in prompt
        say(pick(VALENTINE_LINES if valentine else LOVE_LINES), "love_talk")
        face.state("love")
        time.sleep(3.0)          # hold the kiss while the hearts float up
        go_to_sleep()
        return
    if prompt in REST_PHRASES:
        log_turn("command:rest", prompt)
        rest()
        return
    if prompt in POWER_OFF_PHRASES:
        log_turn("command:power_off", prompt)
        ask_power_off()
        return
    mem = memory.handle(prompt, speaker)
    if mem:
        log_turn("command:memory", prompt, mem.reply)
        if mem.confirm:
            def do_it(result=mem):
                say(result.confirm())
                go_to_sleep()
            ask_confirm(mem.reply + " Say yes, or tap me.", do_it)
        else:
            say(mem.reply)
            go_to_sleep()
        return
    if prompt in STOP_PHRASES:
        log_turn("command:stop", prompt)
        say(pick(GOODBYES))
        go_to_sleep()
        return
    if prompt in THANKS_PHRASES:
        log_turn("command:thanks", prompt)
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
        if mode == "confirm":
            confirmed()          # tapping confirms
        elif mode in ("sleep", "resting"):
            wake_up("tap")
        else:
            start_listening(LISTEN_SECONDS)  # tap again = "I'm talking to you"
        continue

    if mode == "confirm" and now > active_until:
        declined()

    # a new weather or AMBER alert (urgent ones even while she's resting)
    alert = alert_watch.due(mode)
    if alert:
        was = mode
        print(f"Announcing alert: {alert.event}", flush=True)
        log_turn("alert", reply=alert.spoken, notes=f"{alert.kind}: {alert.event}")
        earcons.alert()
        face.caption(alert.event)
        say(alert.spoken)
        face.caption("")
        if was == "resting":
            face.state("resting")   # back to bed; a tap still wakes her
        else:
            go_to_sleep()
        continue

    # something she noticed while pondering (only said while she's awake and free)
    if notices:
        text = notices.pop(0)
        if mode == "sleep" and text:
            print("Notice from the face:", text, flush=True)
            log_turn("notice", reply=text, notes="pondering: node reading")
            say(text)
            go_to_sleep()
            continue

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
            earcons.done()                 # "I stopped listening"
            log_turn("no_question", notes="woke but heard no question (possible false wake)")
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
            res = json.loads(wake_rec.Result())
            words = res.get("result", [])
            conf = wake_phrase_confidence(words)
            if conf is not None:
                who = None
                if conf >= WAKE_MIN_CONF and spk_model is not None and "spk" in res:
                    who, score = voices.identify(res.get("spk"), res.get("spk_frames", 0),
                                                 min_frames=30)
                    print(f"(wake voice: {who or 'unknown'}, similarity {score:.2f})", flush=True)
                    if voices.ONLY_KNOWN and voices.names() and not who:
                        print("(ignored wake phrase from an unknown voice)", flush=True)
                        continue
                if conf >= WAKE_MIN_CONF:
                    wake_up("wake phrase", conf, who)
                else:
                    print(f"(ignored possible wake phrase, confidence {conf:.2f})", flush=True)
        continue

    if mode == "confirm":
        if rec.AcceptWaveform(pcm16):
            reply = normalize(json.loads(rec.Result()).get("text", ""))
            if reply:
                face.caption(reply)
                print("Heard:", reply, flush=True)
                if reply in YES_WORDS or set(reply.split()) & {"yes", "yeah", "yep", "sure"}:
                    confirmed()
                else:
                    declined()
        continue

    # Active: transcribe the question
    if rec.AcceptWaveform(pcm16):
        res = json.loads(rec.Result())
        text = normalize(res.get("text", ""))
        heard_started = 0.0
        if text:
            note_speaker(res)
            face.caption(text)
            handle_command(text)
    else:
        partial = json.loads(rec.PartialResult()).get("partial", "")
        if partial:
            if not heard_started:
                heard_started = now  # speech has begun; start the length cap
            if partial != last_partial and now - last_caption_at > 0.25:
                face.caption(partial)      # live caption as you speak
                last_partial, last_caption_at = partial, now

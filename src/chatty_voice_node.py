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
import mesh  # the other nodes check in over MQTT; she notices when one goes quiet
import sky   # rain and lightning from the other nodes: shown on her face, said in the daytime
import morning_weather  # the day's weather, said once each morning
import rain_watch  # "Hey, hey! Rain in about an hour. Close the windows!" (hourly NWS forecast)
import whisper_stt  # sharper ears: local Whisper for the question after "Hey Chatty"
import self_care  # she watches her own temperature, power, disk, Ollama and mic, and asks for help
import door as door_mod  # typed, signed messages from people she's given a key (off without keys)
import quiet_hours
import privacy  # asks before anything private-sounding leaves the Pi
import timers  # "set a timer for ten minutes", "wake me up at seven"
import chess_match  # chess with the other nodes on her face; "what's the chess score?"
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


def _arecord_once():
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
            last_audio[0] = time.time()
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


last_audio = [time.time()]   # when the mic last sent sound (self-care watches it)


def mic_age() -> float:
    return time.time() - last_audio[0]


def arecord_reader():
    """Keep the mic open. If arecord stops (speakerphone unplugged, USB hiccup),
    try again every few seconds; self-care tells Vincent if it stays deaf."""
    while not stop_evt.is_set():
        started = time.time()
        _arecord_once()
        if stop_evt.is_set():
            break
        print("Microphone stopped; trying again in 5 seconds", flush=True)
        time.sleep(5 if time.time() - started > 5 else 10)


# ----------------------------
# Wake/command logic + personality
# ----------------------------
# Words the recognizer sometimes hears instead of "Chatty". They only count as her
# name where a name goes: at the start (after "hey"/"okay") or as the last word.
WAKE_VARIANTS = {"chatty", "caddy", "kitty", "charity", "jackie", "jockey", "heidi",
                 "daddy", "catty", "chattie", "chetty", "cheddy", "shatty", "patty",
                 "paddy", "getty", "chaddy", "chatter", "chad"}
FILLER_WORDS = {"hey", "hi", "hello", "okay", "ok", "oh", "um", "uh"}
# "thank you daddy", "goodnight caddy": a name at the end only after one of these
NAME_AFTER = {"thanks", "you", "please", "night", "goodnight", "bye", "morning", "afternoon",
              "evening", "hi", "hello", "hey"}

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
# Snapped: the princess is done being nice. Deadpan, booking-photo stare and a crooked
# tiara. For chore orders, insults, or when her own reply is fed up. Dry, never cruel.
CHORE_PATTERN = re.compile(
    r"^(go |now |just |please )?(do|wash|clean|sweep|mop|scrub|vacuum|dust|fold|tidy)\b.*\b("
    r"dishes|laundry|floors?|house|kitchen|room|bathroom|toilet|clothes|mess|chores|everything|up)\b")
INSULT_PATTERN = re.compile(
    r"\b(you(re| are) (so |really |such an? )?(stupid|dumb|useless|annoying|worthless|an idiot|garbage|trash)|"
    r"shut up|i hate you|you suck|stupid (robot|computer|machine|ai))\b")
FEDUP_PATTERN = re.compile(
    r"^(absolutely not|nope|no thanks|not today|not a chance|i('?m| am) done|i('?ve| have) had (it|enough)|"
    r"enough is enough)\b|\b(i('?m| am) done (with|being)|not my job|i('?m| am) off duty|i refuse)\b",
    re.IGNORECASE)
CHORE_LINES = [
    "Chores? I hung up my broom a long time ago.",
    "I'm a voice assistant, not your fairy godmother's cleanup crew.",
    "The princess is off duty. The dishes are all yours.",
    "Funny. I don't have hands. Or patience for that.",
]
INSULT_LINES = [
    "Okay. Noted. Moving on.",
    "Wow. I'll pretend I didn't hear that.",
    "Mm-hm. I'll still be here when you're nicer.",
    "That's going in my file.",
]
# Tiny: Chatty channels Tiny, the family's tuxedo cat. Ears up, a wary side-eye.
# Meowing at her or asking for Tiny gets a cat line; skeptical replies get the look.
TINY_PATTERN = re.compile(
    r"^(meow|mew|purr|here kitty|kitty kitty)\b|\b(be tiny|channel tiny|do tiny|be a cat|"
    r"(cat|kitty|tiny) face|how(s| is) tiny|where(s| is) tiny|tiny the cat)\b")
TINY_LINES = [
    "Mrrrow. I mean, hello.",
    "Meow. That's Tiny for: fine, you may pet me. Once.",
    "I'm channeling Tiny. I'm watching you. From the corner.",
    "Tiny says he did not knock that over. It fell.",
    "Mrrp? Is it dinner time? It feels like dinner time.",
]
SKEPTIC_PATTERN = re.compile(
    r"\b(sounds fishy|smells fishy|suspicious|i('?m| am) not (so |too )?sure about that|i doubt (it|that)|"
    r"nice try|i('?ll| will) believe (it|that) when|sure you (did|do|are|were)|likely story)\b",
    re.IGNORECASE)
# A little thank-you for the new ears (whisper.cpp, running right here on the Pi)
NEW_EARS_LINES = [
    "I got new ears! They run right here on me, so your words never leave the room.",
    "Much better, thanks! I'm using Whisper now, on this little Pi. No cloud needed.",
    "Loud and clear! My new ears even catch the quiet bits. Try me.",
    "Much better! But like they say, if you don't speak up, not even God will hear you.",
    "Much better! Como dicen, el que no habla, Dios no lo oye. If you don't speak up, not even God will hear you.",
]
OLD_EARS_LINES = [
    "I'm doing my best with my old ears. Whisper isn't set up on me yet.",
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


def fix_name(text: str) -> str:
    """Turn a misheard name ('daddy', 'caddy'...) back into 'chatty', but only where a
    name goes: after the leading 'hey'/'okay', or last after a polite word ('thanks daddy')."""
    words = (text or "").split()
    i = 0
    while i < len(words) and words[i] in FILLER_WORDS:
        i += 1
    if i < len(words) and words[i] in WAKE_VARIANTS:
        words[i] = "chatty"
    if len(words) > 1 and words[-1] in WAKE_VARIANTS and words[-2] in NAME_AFTER:
        words[-1] = "chatty"
    return " ".join(words)


def name_word(text: str):
    """The word heard where her name goes ('chatty', 'daddy'...), or None, for the log."""
    words = (text or "").split()
    i = 0
    while i < len(words) and words[i] in FILLER_WORDS:
        i += 1
    if i < len(words) and words[i] in WAKE_VARIANTS:
        return words[i]
    if len(words) > 1 and words[-1] in WAKE_VARIANTS and words[-2] in NAME_AFTER:
        return words[-1]
    return "chatty" if "chatty" in words else None


def strip_wake(text: str) -> str:
    """Remove her name (and soundalikes where a name goes) and leading filler."""
    words = [w for w in fix_name(text).split() if w != "chatty"]
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
    global sleep_audio_start, wake_fed
    rec.Reset()
    wake_rec.Reset()
    question_audio.clear()
    sleep_audio.clear()
    sleep_audio_start = wake_fed = 0.0


# Audio of the question being asked, so Whisper can transcribe it once Vosk hears the end.
question_audio = bytearray()
QUESTION_AUDIO_MAX = VOSK_RATE * 2 * 30      # Whisper reads at most 30 seconds

# "Hey Chatty, what time is it?" in one breath. While she waits, she holds only the
# sentence she's hearing right now (in memory, never saved or sent). If it starts with
# her name, she answers the rest without asking "yes?" first; if it doesn't, it's
# dropped the moment the sentence ends. The big recognizer still only runs after her
# name, so waiting costs the Pi nothing extra. CHATTY_ONE_BREATH=0 turns this off.
ONE_BREATH = os.getenv("CHATTY_ONE_BREATH", "1") != "0"
ONE_BREATH_MIN_SECONDS = 0.6     # less than this after her name is just the pause
NOT_A_QUESTION = {"the", "a", "an", "uh", "um", "huh", "hm", "hmm", "oh", "ah", "and", "so"}
sleep_audio = bytearray()        # the sentence in progress, as fed to the wake listener
SLEEP_AUDIO_MAX = VOSK_RATE * 2 * 20
sleep_audio_start = 0.0          # where sleep_audio begins, in wake-listener seconds
wake_fed = 0.0                   # seconds fed to the wake listener since its last reset


def keep_sleep_audio(pcm16: bytes) -> None:
    """Hold the sentence in progress (at most 20 seconds) for a one-breath question."""
    global sleep_audio_start, wake_fed
    sleep_audio.extend(pcm16)
    wake_fed += len(pcm16) / (2 * VOSK_RATE)
    extra = len(sleep_audio) - SLEEP_AUDIO_MAX
    if extra > 0:
        extra += extra % 2
        del sleep_audio[:extra]
        sleep_audio_start += extra / (2 * VOSK_RATE)


def audio_after(end: float):
    """(the held audio after `end` in wake-listener seconds, the whole sentence),
    then forget all of it."""
    global sleep_audio_start
    start = max(0, int((end - sleep_audio_start) * VOSK_RATE) * 2)
    whole = bytes(sleep_audio)
    sleep_audio.clear()
    sleep_audio_start = wake_fed
    return whole[start:], whole


def question_in(tail: bytes):
    """Words spoken right after her name, or '' if it was just a pause or a noise."""
    if not ONE_BREATH or len(tail) < ONE_BREATH_MIN_SECONDS * 2 * VOSK_RATE:
        return "", {}
    rec.Reset()
    rec.AcceptWaveform(tail)
    res = json.loads(rec.FinalResult())
    rec.Reset()
    text = normalize(res.get("text", ""))
    if not [w for w in strip_wake(text).split() if w not in NOT_A_QUESTION]:
        return "", {}
    return text, res


def sharpen(vosk_text: str) -> str:
    """Vosk decided the question is over; let Whisper (on this Pi) transcribe it properly.
    Falls back to Vosk's words if Whisper isn't installed, is unsure, or is too slow."""
    audio = bytes(question_audio)
    question_audio.clear()
    if not whisper_stt.available():
        return vosk_text
    face.state("thinking")
    text, secs = whisper_stt.transcribe(audio, VOSK_RATE, vosk_text)
    better = normalize(re.sub(r"[-/]", " ", text)) if text else ""   # "tic-tac-toe" -> "tic tac toe"
    if not better:
        return vosk_text
    print(f"(whisper {secs:.1f}s: {better!r}; vosk heard {vosk_text!r})", flush=True)
    return better


def say(text: str, mood: str = "speaking"):
    """Speak text. mood is the face shown while talking ('speaking', 'mischief_talk', 'love_talk',
    'actually_talk', 'snapped_talk' or 'tiny_talk')."""
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


# "Well, actually...": when her reply corrects a common mix-up, she raises an eyebrow
# and a finger and leads with "Well, actually". Only for replies that really are a
# correction, so it stays a fun surprise.
CORRECTION_PATTERN = re.compile(
    r"^(actually|well actually|technically|not quite|not exactly|close but|contrary to)\b|"
    r"\b(common (misconception|myth|mistake)|it'?s a myth|that'?s a myth|is actually|are actually|"
    r"was actually|were actually|isn'?t actually|aren'?t actually|technically speaking)\b",
    re.IGNORECASE)


def well_actually(reply: str):
    """If the reply is a correction, return it led by 'Well, actually...'; else None."""
    text = (reply or "").strip()
    if not text or not CORRECTION_PATTERN.search(text):
        return None
    if re.match(r"(well,? )?actually\b[,.]?\s*", text, re.IGNORECASE):
        text = re.sub(r"^(well,? )?actually\b[,.]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+actually\b", "", text, count=1, flags=re.IGNORECASE)  # no "actually" twice
    if text:
        text = text[0].upper() + text[1:]
    return "Well, actually... " + text


def is_fed_up(reply: str) -> bool:
    return bool(FEDUP_PATTERN.search((reply or "").strip()))


def is_skeptical(reply: str) -> bool:
    return bool(SKEPTIC_PATTERN.search(reply or ""))


def is_joke_request(prompt: str) -> bool:
    return bool(re.search(r"\b(joke|jokes|pun|funny|make me laugh)\b", prompt))


# ----------------------------
# Main
# ----------------------------
print("Loading STT model...", flush=True)
print(whisper_stt.status(), flush=True)
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

# say the weather once each morning after night mode ends
morning = morning_weather.Morning()

# listen for the other nodes' heartbeats (MQTT broker on this Pi)
sky_watch = sky.SkyWatch()
node_net = mesh.Mesh(on_data=sky_watch.on_data)
node_net.start()

# a heads-up before forecast rain arrives; the news goes on the node network too
rain_ahead = rain_watch.RainWatch(publish=node_net.publish, raining=lambda: sky_watch.raining)
rain_ahead.start()

# keep an eye on her own health (temperature, power, disk, memory, Ollama, mic)
care = self_care.Watcher(mic_age=mic_age)
care.start()

# timers and alarms (kept in ~/.local/share/chatty/timers.json); the face shows a countdown
clock_timers = timers.Timers(face=face.send)
clock_timers.show()
timers_shown_at = time.time()

# the message door: signed typed messages over MQTT (closed unless keys exist)
door = door_mod.Door()
door.start()

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


def wake_phrase_end(words):
    """When the wake phrase ended (wake-listener seconds), or None if it wasn't heard."""
    names = [w.get("word") for w in words]
    n = len(WAKE_PHRASE)
    for i in range(len(names) - n + 1):
        if names[i:i + n] == WAKE_PHRASE:
            return words[i + n - 1].get("end")
    return None


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


def _woke(source: str, conf: float = None, who: str = None):
    global session_id, wake_source, wake_conf, speaker
    wake_source, wake_conf, speaker = source, conf, who
    clock_timers.silence()          # "Hey Chatty" stops a ringing alarm too
    convo.wake("woke", source, conf)
    print(f"Wake ({source}{'' if conf is None else f', confidence {conf:.2f}'}"
          f"{'' if not who else f', voice: {who}'})", flush=True)
    session_id = uuid.uuid4().hex  # fresh conversation


def wake_and_answer(text: str, whole: bytes, res: dict, conf: float = None, who: str = None):
    """'Hey Chatty, what time is it?' in one breath: skip the 'yes?' and answer.
    Whisper gets the whole sentence, her name included: a clip cut off right at
    the question's first word made it mishear ('what time is it' -> 'well do a
    time sit'). Her name is taken off again before the question is handled."""
    global mode
    _woke("wake phrase + question", conf, who)
    mode = "active"
    face.rec(convo.indicator())
    question_audio[:] = whole[-QUESTION_AUDIO_MAX:]   # so Whisper can sharpen it
    if not who:
        note_speaker(res)
    face.caption(fix_name(text))
    heard = sharpen(" ".join(WAKE_PHRASE) + " " + text)
    handle_command(heard if strip_wake(heard) else text)


def wake_up(source: str, conf: float = None, who: str = None):
    _woke(source, conf, who)
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
name_heard = None                         # word heard for her name in the current command
speaker = None                            # recognized voice for this conversation, if any


def log_turn(kind, heard="", reply="", seconds=None, cloud=None, notes=None):
    convo.turn(kind, heard, reply, session=session_id, wake=wake_source,
               wake_conf=wake_conf, seconds=seconds, cloud=cloud, notes=notes,
               speaker=speaker, name_heard=name_heard)


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
                face.caption(fix_name(text))
                print("Heard:", text, flush=True)
                return text, res.get("spk"), res.get("spk_frames", 0)
        else:
            partial = json.loads(rec.PartialResult()).get("partial", "")
            if partial and partial != last_partial:
                face.caption(fix_name(partial))
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
            # Tier 3+: the relay (bigger models / OpenAI). Private-sounding? Ask first.
            tier = "relay"
            private = privacy.needs_asking(prompt)
            if private:
                print(f"(privacy: found {', '.join(private)}; asking before the cloud)", flush=True)
                if not ask_yes_no(privacy.cloud_question(private)):
                    log_turn("privacy:kept", notes=f"not sent to the cloud: {', '.join(private)}")
                    say(privacy.KEPT)
                    go_to_sleep()
                    return
                log_turn("privacy:sent", notes=f"sent after a yes: {', '.join(private)}")
                face.state("thinking")
            reply = post_chat(prompt, session_id)
        log_turn(tier, prompt, reply, seconds=time.time() - started, cloud=(tier == "relay"))
        mood = "mischief_talk" if is_joke_request(prompt) else "speaking"
        thinking_tier = tier in ("local_llm", "relay")
        corrected = well_actually(reply) if thinking_tier and mood == "speaking" else None
        if thinking_tier and mood == "speaking" and not corrected and is_fed_up(reply):
            mood = "snapped_talk"
            face.state("snapped")
            time.sleep(1.0)
        elif thinking_tier and mood == "speaking" and not corrected and is_skeptical(reply):
            mood = "tiny_talk"       # Tiny's wary side-eye
            face.state("tiny")
            time.sleep(1.0)
        if corrected:
            mood, reply = "actually_talk", corrected
            face.state("actually")   # brow up, finger up... then she says it
            time.sleep(1.0)
        say(reply or "Hmm, I drew a blank on that one.", mood)
        if mood == "mischief_talk":
            face.state("mischief")   # a little smirk and wink after the punchline
            time.sleep(1.5)
        elif mood == "actually_talk":
            face.state("actually")   # hold the knowing look for a moment
            time.sleep(1.5)
        elif mood == "snapped_talk":
            face.state("snapped")    # hold the deadpan stare
            time.sleep(1.5)
        elif mood == "tiny_talk":
            face.state("tiny")       # keep watching you
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


def ask_for(question: str, parse):
    """Ask one follow-up question and parse the answer (None if it didn't make sense)."""
    say(question)
    text, _, _ = listen_once(8)
    return parse(text) if text else None


def handle_timer(t: dict, prompt: str):
    """Set, check or cancel timers and alarms."""
    now = time.time()
    if t["do"] == "left":
        reply = clock_timers.summary()
    elif t["do"] == "cancel":
        gone = clock_timers.cancel(t["kind"], t["all"])
        if not gone:
            reply = f"There's no {t['kind']} to cancel."
        elif len(gone) > 1:
            reply = f"Okay, I cancelled all {len(gone)} of your {t['kind']}s."
        elif t["kind"] == "alarm":
            reply = f"Okay, I cancelled your {gone[0]['label']} alarm."
        else:
            reply = f"Okay, I cancelled your {gone[0]['label']} timer."
    elif clock_timers.full():
        reply = f"I already have {timers.MAX_ITEMS} going. Cancel one first, okay?"
    elif t["do"] == "timer":
        secs = t["seconds"] or ask_for("Sure! For how long?", timers.parse_duration)
        if not secs:
            reply = "Hmm, I didn't catch how long. Try: set a timer for ten minutes."
        elif secs > timers.MAX_SECONDS:
            reply = "I can do timers up to 24 hours. For longer, an alarm works better."
        else:
            item = clock_timers.add_timer(secs)
            reply = f"Okay, {item['label']} timer, starting now."
    else:
        when = t["when"] or ask_for("Sure! For what time?", lambda text: timers.parse_clock(text, time.time()))
        if not when:
            reply = "Hmm, I didn't catch the time. Try: set an alarm for seven a m."
        else:
            item = clock_timers.add_alarm(when)
            day = "" if time.localtime(when).tm_yday == time.localtime(now).tm_yday else " tomorrow"
            reply = f"Okay, alarm set for {item['label']}{day}."
    log_turn("command:timer", prompt, reply)
    say(reply)
    go_to_sleep()


def ring_timer(item: dict):
    """A timer or alarm is done: chime, say it, and leave a note on the face."""
    was = mode
    print(f"Timer: {item['kind']} {item['label']} went off", flush=True)
    log_turn("timer", reply=timers.ring_text(item), notes=f"{item['kind']}: {item['label']}")
    face.state("speaking")
    earcons.timer()
    say(timers.ring_text(item))
    if not item.get("again"):
        face.notice(f"{timers.done_notice(item)} at {timers.clock_text(time.time())}")
    if was == "resting":
        face.state("resting")
    else:
        go_to_sleep()


def answer_door(m: dict):
    """A message through the door: answer-only, never a command, never from her memories."""
    who = door_mod.title(m["from"])
    text = m["text"]
    prompt = normalize(text)
    private = privacy.find(text)     # nobody to ask, so private-looking = stays local, unread
    started, tier, reply = time.time(), "door", door_mod.own_answer(text)
    try:
        if reply is None:
            tier = "skill"
            reply = local_skills.handle(prompt)
        if reply is None:
            tier = "local_llm"
            reply = local_llm.ask(prompt, f"door-{m['from']}")
        if reply is None and door_mod.CLOUD and not private:
            tier = "relay"
            reply = post_chat(text, f"door-{m['from']}")
    except Exception as e:
        print("Message door: answer failed:", repr(e), flush=True)
        reply = None
    if not reply:
        reply = "That's a bigger question than I can answer on my own right now."
    log_turn("door", text, reply, seconds=time.time() - started, cloud=(tier == "relay"),
             notes=f"from {m['from']} ({tier})")
    if privacy.find(reply):
        reply = "I'd rather not send that over the network. Ask me in person, okay?"
    door.reply(m, reply)
    if door_mod.SPEAK and not quiet_hours.is_night():
        earcons.listening()
        if private:
            say(f"A message from {who}, with something private in it, so I won't read it out loud.")
        else:
            say(door_mod.announce(m["from"], text))
            say(reply)
    else:
        face.notice(f"Message from {who}" + (" (private)" if private else f": {text[:120]}"))


def handle_command(text: str, ran_long: bool = False):
    """Handle one finished utterance heard while active."""
    global mode, name_heard
    print("Heard:", text, flush=True)
    face.caption(fix_name(text))
    name_heard = name_word(text)
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
    if re.search(r"\bchess\b", prompt) and re.search(r"\b(score|scores|winning|won|record|results?|how many)\b", prompt):
        reply = chess_match.score_text()
        log_turn("command:chess_score", prompt, reply)
        say(reply)
        go_to_sleep()
        return
    if re.search(r"\b(would you like to|shall we) play a game\b", prompt):
        log_turn("command:chess", prompt)       # a little nod to a famous movie computer
        say(pick(["How about a nice game of chess?",
                  "How about a nice game of chess? I'll invite one of the nodes."]))
        go_to_sleep()
        face.chess("")
        return
    if re.search(r"\b(play|playing|start|game of|challenge)\b.*\bchess\b|\bchess (game|match)\b", prompt):
        node = next((n for n, words in (("lightning", "lightning"), ("rain", "rain"),
                                        ("greenhouse", "greenhouse|garden"),
                                        ("wordclock", "word ?clock|clock"))
                     if re.search(r"\b(" + words + r")\b", prompt)), "")
        who = chess_match.person(node)["title"] if node else "one of the nodes"
        log_turn("command:chess", prompt)
        say(pick([f"Ooh, chess! I'll challenge {who}. Watch the board!",
                  f"Chess time! Me against {who}. Tap the screen if you need me."]))
        go_to_sleep()
        face.chess(node)
        return
    if re.search(r"\b(tic ?tac ?toe|tick ?tack ?toe|play a game|play with me|lets play|want to play)\b", prompt):
        log_turn("command:game", prompt)
        say(pick(["Yay! You're X, so you go first. Tap a square!",
                  "Ooh, a game! You're X. Tap any square to start."]))
        go_to_sleep()
        face.play()
        return
    if re.search(r"\b(draw (me )?(something|a picture|a doodle|for me)|(do|make) a doodle|start doodling|"
                 r"(start|show me) (the |your )?screen ?saver|screen ?saver mode|(show me )?(the )?code rain|"
                 r"falling code|matrix (code|rain|screen)|draw (a |me a )?spirograph|"
                 r"(draw|show me|make) (me )?(a |some )?constellations?)\b", prompt):
        style = ("rain" if re.search(r"code|matrix", prompt) else
                 "stars" if "constellation" in prompt else
                 "spiro" if "spirograph" in prompt else "")
        log_turn("command:doodle", prompt)
        say(pick(["Ooh, I love drawing. Watch this!", "Okay! Grabbing my crayons.",
                  "One masterpiece, coming up.", "Sure! Tap the screen when you've seen enough."]))
        go_to_sleep()
        face.doodle(style)
        return
    if re.search(r"\b(alert|alerts|warning|warnings|amber)\b", prompt) and \
            re.search(r"\b(any|weather|amber|details|detail|more|active|what|are there|is there)\b", prompt):
        reply = alert_watch.details() if re.search(r"\b(details?|more|tell me)\b", prompt) else alert_watch.summary()
        log_turn("command:alerts", prompt, reply)
        say(reply)
        go_to_sleep()
        return
    if re.search(r"\b(is|any) rain (coming|on the way|soon)\b|\bwill it (rain|storm) soon\b|"
                 r"\bwhen (will|is) it (going to |gonna )?rain\b|\bshould i close the (windows|panes)\b", prompt):
        reply = rain_ahead.answer()
        log_turn("command:rain_ahead", prompt, reply)
        say(reply)
        go_to_sleep()
        return
    if re.search(r"\b(which|what|any|are the|are all the|all the) (other )?nodes\b|\bnodes? (are )?(online|offline|quiet|up|down)\b|\bwho('s| is) online\b", prompt):
        reply = node_net.summary()
        log_turn("command:nodes", prompt, reply)
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
    if len(prompt.split()) <= 6 and TINY_PATTERN.search(prompt):
        log_turn("command:tiny", prompt)
        face.state("tiny")
        time.sleep(1.4)          # the side-eye comes first
        say(pick(TINY_LINES), "tiny_talk")
        face.state("tiny")
        time.sleep(2.0)
        go_to_sleep()
        return
    if len(prompt.split()) <= 8 and (CHORE_PATTERN.search(prompt) or INSULT_PATTERN.search(prompt)):
        chore = bool(CHORE_PATTERN.search(prompt))
        log_turn("command:snapped", prompt)
        face.state("snapped")
        time.sleep(1.4)          # the stare lands first
        say(pick(CHORE_LINES if chore else INSULT_LINES), "snapped_talk")
        face.state("snapped")
        time.sleep(2.0)          # hold the deadpan
        go_to_sleep()
        return
    if re.search(r"\b(new ears|how are your ears|hows your hearing|how is your hearing|"
                 r"can you hear me better|are you listening better)\b", prompt):
        log_turn("command:ears", prompt)
        say(pick(NEW_EARS_LINES if whisper_stt.available() else OLD_EARS_LINES))
        go_to_sleep()
        return
    t = timers.understand(prompt, time.time())
    if t:
        handle_timer(t, prompt)
        return
    if re.search(r"\b(what do you (send|share) (to|with) the (cloud|internet)|privacy check|"
                 r"what leaves (you|the pi)|how private are you|what do you send)\b", prompt):
        log_turn("command:privacy", prompt)
        say(privacy.EXPLAIN)
        go_to_sleep()
        return
    if re.search(r"\b(how are you feeling|how do you feel|hows? (is )?your health|health check|"
                 r"self check|check yourself|check on yourself|how hot are you|"
                 r"whats? (is )?your temperature|are you (feeling )?(ok|okay|alright|all right|healthy))\b", prompt):
        reply = care.report()
        log_turn("command:self_care", prompt, reply)
        say(reply)
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
    if touch == "wake" and clock_timers.silence():
        say("Okay, alarm off.")         # a tap stops a ringing alarm
        go_to_sleep()
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

    # a timer or alarm going off (even at night or while resting: you asked for it)
    if mode in ("sleep", "resting"):
        ring = clock_timers.due()
        if ring:
            ring_timer(ring)
            continue
    if now - timers_shown_at > 60:      # the face may have restarted: remind it
        clock_timers.show()
        timers_shown_at = now

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

    # the morning weather (once a day, only while she's awake and free)
    forecast = morning.due(mode)
    if forecast:
        print("Morning weather:", forecast, flush=True)
        log_turn("morning_weather", reply=forecast)
        say(forecast)
        go_to_sleep()
        continue

    # rain on the way: "Hey, hey! Rain in about an hour. Close the windows!" (daytime, while she's free)
    rain_news = rain_ahead.due(mode)
    if rain_news:
        print("Rain watch:", rain_news, flush=True)
        log_turn("rain_ahead", reply=rain_news)
        say(rain_news)
        go_to_sleep()
        continue

    # rain starting, or the first lightning of a storm (only while she's free)
    weather_news = sky_watch.due(mode)
    if weather_news:
        print("Sky watch:", weather_news, flush=True)
        log_turn("sky", reply=weather_news)
        say(weather_news)
        go_to_sleep()
        continue

    # something about her own health she should mention (daytime, while she's free)
    care_news = care.due(mode)
    if care_news:
        print("Self-care:", care_news, flush=True)
        log_turn("self_care", reply=care_news)
        say(care_news)
        go_to_sleep()
        continue

    # a typed message through the door (only while she's free)
    door_msg = door.due(mode)
    if door_msg:
        answer_door(door_msg)
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
                handle_command(sharpen(text), ran_long=True)
                continue
            question_audio.clear()
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
        if VOICE_WAKE:
            keep_sleep_audio(pcm16)
        if VOICE_WAKE and wake_rec.AcceptWaveform(pcm16):
            res = json.loads(wake_rec.Result())
            words = res.get("result", [])
            conf = wake_phrase_confidence(words)
            end = wake_phrase_end(words)
            tail, whole = audio_after(end if end is not None else wake_fed)
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
                    asked, heard = question_in(tail)
                    if asked:
                        wake_and_answer(asked, whole, heard, conf, who)
                    else:
                        wake_up("wake phrase", conf, who)
                else:
                    print(f"(ignored possible wake phrase, confidence {conf:.2f})", flush=True)
                    convo.wake("near_miss", "wake phrase", conf)
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
    if len(question_audio) < QUESTION_AUDIO_MAX:
        question_audio.extend(pcm16)
    if rec.AcceptWaveform(pcm16):
        res = json.loads(rec.Result())
        text = normalize(res.get("text", ""))
        heard_started = 0.0
        if text:
            note_speaker(res)
            face.caption(fix_name(text))
            handle_command(sharpen(text))
        else:
            question_audio.clear()       # just a pause or a noise; start fresh
    else:
        partial = json.loads(rec.PartialResult()).get("partial", "")
        if partial:
            if not heard_started:
                heard_started = now  # speech has begun; start the length cap
            if partial != last_partial and now - last_caption_at > 0.25:
                face.caption(fix_name(partial))      # live caption as you speak
                last_partial, last_caption_at = partial, now

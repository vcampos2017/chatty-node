import os, json, queue, subprocess, time, re, threading, random, uuid, socket, signal
import sys
from typing import Optional

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
import red_alert  # Red Alert: only for a tornado warning here (red face, her alarm, voice, phone)
import mesh  # the other nodes check in over MQTT; she notices when one goes quiet
import sky   # rain and lightning from the other nodes: shown on her face, said in the daytime
import morning_briefing  # good morning: weather, rain chances and the nodes, once a day
import bedtime  # the bedtime wind-down: tomorrow's numbers, the node roll call, lights down
import rain_hold  # no "the plants are thirsty" nag right after rain or just before it
import rain_watch  # "Hey, hey! Rain in about an hour. Close the windows!" (hourly NWS forecast)
import whisper_stt  # sharper ears: local Whisper for the question after "Hey Chatty"
import self_care  # she watches her own temperature, power, disk, Ollama and mic, and asks for help
import door as door_mod  # typed, signed messages from people she's given a key (off without keys)
import quiet_hours
import privacy  # asks before anything private-sounding leaves the Pi
import fact_check  # double-checks factual answers (and every "Well, actually...") before she says them
import timers  # "set a timer for ten minutes", "wake me up at seven"
import chess_match  # chess with the other nodes on her face; "what's the chess score?"
import chess_mail  # chess by letter with Claude (and other door key holders)
import trickster  # "Who's the Trickster?", a kind little mystery game on her face
import imagine  # "Hey Chatty, imagine a dragon": a rainbow sweep and a made-up idea, all local
import morse  # "say hello in Morse": beeps + a telegraph tape on her face; reads dots and dashes and beeps
import panel_link  # the remote panel: a web page for asking her things without touching her face
import eliza  # a tribute to ELIZA: "Please go on."
import chat_memory  # the last few exchanges, so "please" and "what about tomorrow?" make sense
import homecoming  # "Welcome home, Vincent!" when his phone is back on the home WiFi (off until set up)
from words import (  # her name, filler, yes/no/thanks and tidy speech (src/words.py)
    WAKE_VARIANTS, FILLER_WORDS, NAME_AFTER, YES_WORDS, THANKS_PHRASES, JUST_NO, CONFIRM_NOISE,
    normalize, fix_name, name_word, strip_wake, clean_for_speech, is_just_thanks, is_just_no, pick)
from personality import (  # her lines, trigger phrases and moods (src/personality.py)
    UNCLEAR_LINES, GREETINGS, GOODBYES, THANKS_REPLIES, TIMEOUT_LINES, ERROR_LINES,
    STOP_PHRASES, REST_PHRASES, POWER_OFF_PHRASES, CHEEKY_PHRASES, CHEEKY_LINES, SPOOKY_LINES,
    LOVE_PATTERN, LOVE_MAX_WORDS, LOVE_LINES, VALENTINE_LINES, CHORE_PATTERN, INSULT_PATTERN,
    FEDUP_PATTERN, CHORE_LINES, INSULT_LINES, TINY_PATTERN, TINY_LINES, SKEPTIC_PATTERN,
    NEW_EARS_LINES, OLD_EARS_LINES, GOODNIGHTS, POWER_OFF_GOODBYES, good_morning, spooky_day,
    valentines_day, is_love_request, CORRECTION_PATTERN, well_actually, is_fed_up,
    is_skeptical, is_joke_request
)
import announcements  # the things she says on her own, in one line-up
import relay  # the paid cloud tier (ceucomics.com relay): post_chat, OutOfCredits
import watchdog  # a heartbeat for systemd: if she ever freezes, she's restarted by herself
from datetime import datetime

import numpy as np
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

if not relay.TOKEN:
    raise RuntimeError("CHATTY_TOKEN not found in /etc/chatty/secrets.env")

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
# Wake/command logic (her lines and moods live in personality.py)
# ----------------------------

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
# Ask before using the paid cloud (the relay): 1 = ask every time (default), 0 = just go
CLOUD_ASK = os.getenv("CHATTY_CLOUD_ASK", "1") != "0"
CLOUD_ASK_PANEL_SECONDS = 60     # time to press Yes on the panel


# the relay client lives in relay.py (the paid cloud tier)
OutOfCredits = relay.OutOfCredits
post_chat = relay.post_chat


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


class RedCutIn(BaseException):
    """A tornado warning came in while she was busy: drop what she's doing so the
    main loop can start Red Alert right away. (BaseException, so no ordinary
    `except Exception` on the way swallows it.)"""


def red_waiting() -> bool:
    """True when a tornado warning (or a Red Alert test) is waiting and Red Alert
    hasn't started yet. Safe to call before the alert watcher exists."""
    r, watch = globals().get("red"), globals().get("alert_watch")
    if r is None or watch is None or r.on:
        return False
    return globals().get("red_test_wanted") is not None or watch.red_warning() is not None


def unless_red(fn, *args, **kwargs):
    """Run a slow call (the Pi model, the relay) but give up on it the moment a
    tornado warning arrives (RedCutIn). Without this, Red Alert waited for the answer,
    up to about a minute. The abandoned call finishes in the background, unheard."""
    if red_waiting():
        raise RedCutIn()
    box = {}

    def run():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as e:      # handed back to the caller below
            box["error"] = e
    worker = threading.Thread(target=run, daemon=True, name="slow-answer")
    worker.start()
    while worker.is_alive():
        worker.join(0.5)
        watchdog.ping()        # waiting on an answer is not frozen
        if worker.is_alive() and red_waiting():
            raise RedCutIn()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def say(text: str, mood: str = "speaking"):
    """Speak text. mood is the face shown while talking ('speaking', 'mischief_talk', 'love_talk',
    'actually_talk', 'snapped_talk', 'tiny_talk' or 'imagine_talk')."""
    text = clean_for_speech(text)
    if text and red_waiting():
        # a tornado warning just came in: Red Alert speaks first, this waits for nobody
        print("(held back for Red Alert:", text[:80] + ")", flush=True)
        flush_audio()
        return
    if text:
        print("Chatty:", text, flush=True)
        panel.said(text)
        if panel.hush:
            return          # asked quietly from the panel: the answer is shown there only
        face.state(mood)
        speak(text)
    flush_audio()


def imagine_out_loud(idea: str, intro: bool = False):
    """The imagination moment: her hands sweep a rainbow open, then she says the idea."""
    face.state("imagine")
    time.sleep(1.4)          # let the rainbow sweep all the way open first
    if intro and random.random() < 0.5:
        idea = imagine.intro() + " " + idea
    say(idea, "imagine_talk")
    face.state("imagine")
    time.sleep(2.5)          # hold the rainbow and the starry eyes for a moment


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

# listen for the other nodes' heartbeats (MQTT broker on this Pi)
sky_watch = sky.SkyWatch(on_wet=rain_hold.note_wet)   # rain_hold: no thirsty nag right after rain
node_net = mesh.Mesh(on_data=sky_watch.on_data)
node_net.start()

# watch for local weather / AMBER alerts in the background; the list goes on the
# node network too (chatty/alerts/active), for the word clock's note
alert_watch = alerts.Watcher(publish=node_net.publish)
alert_watch.start()
red = red_alert.RedAlert()      # a Tornado Warning for this spot turns on Red Alert
red_test_wanted = None          # "redalert:test[:phone]" from `python3 src/red_alert.py --test`
red_test_phone = False

# the morning briefing (default 7:30, after night mode ends): weather, rain chances, the nodes
morning = morning_briefing.Briefing(mesh=node_net, raining=lambda: sky_watch.raining)

# a heads-up before forecast rain arrives; the news goes on the node network too
rain_ahead = rain_watch.RainWatch(publish=node_net.publish, raining=lambda: sky_watch.raining,
                                  on_outlook=rain_hold.note_forecast)
rain_ahead.start()

# keep an eye on her own health (temperature, power, disk, memory, Ollama, mic)
care = self_care.Watcher(mic_age=mic_age)
care.start()


def home_news() -> str:
    """One line for a long-gone person coming home: only if a node went quiet meanwhile."""
    with node_net.tracker.lock:
        quiet = sorted(n.title for n in node_net.tracker.nodes.values() if not n.online)
    if not quiet:
        return ""
    return f"Just so you know, {homecoming._join(quiet)} {'is' if len(quiet) == 1 else 'are'} quiet."


# say hello when someone's phone comes back onto the home WiFi (CHATTY_HOME_PHONES; off without it)
welcome = homecoming.Homecoming(extras=home_news)
welcome.start()


def anyone_home():
    """False only when the homecoming watcher knows every listed phone is away."""
    if not welcome.enabled:
        return None
    seen = [p.home for p in welcome.people.values()]
    return False if seen and all(h is False for h in seen) else None


# the bedtime wind-down (default 9:30 PM): tomorrow's numbers, the node roll call, lights down
winddown = bedtime.WindDown(mesh=node_net, raining=lambda: sky_watch.raining, home=anyone_home)

# the things she says on her own, asked in this order each round (first one wins)
extras = announcements.Lineup([
    announcements.Announcer("morning_briefing", "Morning briefing", morning.due),
    announcements.Announcer("bedtime", "Bedtime", winddown.due, after="tuck_in"),
    announcements.Announcer("rain_ahead", "Rain watch", rain_ahead.due),
    announcements.Announcer("sky", "Sky watch", sky_watch.due),
    announcements.Announcer("self_care", "Self-care", care.due),
    announcements.Announcer("homecoming", "Homecoming", welcome.due),
])

# timers and alarms (kept in ~/.local/share/chatty/timers.json); the face shows a countdown
clock_timers = timers.Timers(face=face.send)
clock_timers.show()
timers_shown_at = time.time()

# the message door: signed typed messages over MQTT (closed unless keys exist)
door = door_mod.Door()
door.chess_ok = chess_mail.ENABLED
door.start()
letters = chess_mail.Correspondence()   # games by letter through the door

# the remote panel (panel.py, a web page): its requests, the lines it shows, a status file
panel = panel_link.Panel(log_mode=convo.indicator)
# the last few exchanges (voice and panel alike, RAM only), forgotten after a few quiet minutes
chat = chat_memory.ChatMemory()

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
    global red_test_wanted
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
            notices.append(msg[len("notify:"):].strip()[:300])
        elif msg.startswith("panel:"):
            panel.take(msg)
        elif msg.startswith(red_alert.TEST_MESSAGE):     # a test from this Pi (red_alert.py --test)
            red_test_wanted = msg.endswith(":phone")


def _woke(source: str, conf: float = None, who: str = None):
    global session_id, wake_source, wake_conf, speaker
    wake_source, wake_conf, speaker = source, conf, who
    clock_timers.silence()          # "Hey Chatty" stops a ringing alarm too
    if red.acknowledge():           # ...and the Red Alert's alarm (the red screen stays)
        print("Red alert: heard (alarm stopped)", flush=True)
    convo.wake("woke", source, conf)
    print(f"Wake ({source}{'' if conf is None else f', confidence {conf:.2f}'}"
          f"{'' if not who else f', voice: {who}'})", flush=True)
    session_id = chat.session_id()  # same conversation while it's fresh, else a new one


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


def tuck_in():
    """After the bedtime wind-down: a soft chime, the screen dims until morning, and
    she dozes off (still listening for her name, unless CHATTY_BEDTIME_REST=1)."""
    global mode
    earcons.lullaby()
    face.send("bedtime")
    if bedtime.REST:
        chat.forget()
        mode = "resting"
        face.state("resting")
        print("(resting until tapped)", flush=True)
    else:
        mode = "sleep"
        face.state("sleepy")


def rest():
    """Put Chatty to bed: a warm goodnight, eyes slowly close, and it stops
    listening for its name until someone taps the screen."""
    global mode
    say(pick(GOODNIGHTS))
    chat.forget()               # a new day, a new conversation
    mode = "resting"
    face.state("resting")
    print("(resting until tapped)", flush=True)


def ask_confirm(question: str, action, decline: str = "Okay, never mind.", seconds: float = 8):
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
    active_until = time.time() + seconds
    face.listen(seconds)


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


CLOUD_QUESTIONS = [
    "That one's too big for me to answer here on the Pi. Should I ask the cloud? It costs a "
    "little. Say yes, or tap me.",
    "I'd need the cloud for that, and it costs a little. Want me to ask it? Say yes, or tap me.",
]


def ask_cloud(prompt: str, local_guess: Optional[str] = None):
    """Before anything goes to the paid relay: 'Should I ask the cloud?' A yes (said, a tap,
    or the panel's Yes button) sends it; anything else keeps it on the Pi."""
    log_turn("cloud:asked", prompt)
    keep = "Okay, I'll keep it here on the Pi."
    decline = (f"{keep} {fact_check.hedge(local_guess)}" if local_guess
               else f"{keep} Maybe ask me a simpler way?")
    ask_confirm(pick(CLOUD_QUESTIONS),
                lambda: answer(prompt, cloud_ok=True, local_guess=local_guess),
                decline=decline,
                seconds=CLOUD_ASK_PANEL_SECONDS if wake_source == "panel" else 8)


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


def answer(prompt: str, cloud_ok: bool = False, local_guess: Optional[str] = None):
    """Answer on the Pi if she can; the paid relay only after a yes (CHATTY_CLOUD_ASK).
    cloud_ok=True is that yes: straight to the relay, the Pi's tiers already tried."""
    global mode
    face.state("thinking")
    started = time.time()
    tier = "relay" if cloud_ok else "skill"
    checked = "skipped"
    if not cloud_ok:
        prompt = chat.expand(prompt)    # "another one" -> the last question again, a new answer
    try:
        reply = None
        if not cloud_ok:
            # Tier 1: built-in answers (time, date, weather, greenhouse)
            reply = local_skills.handle(prompt)
            if reply is None:
                # a tribute to ELIZA (MIT, 1966): "who is ELIZA?", and now and then "Please go on."
                reply = eliza.about(prompt) or eliza.go_on(prompt)
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
                if not fact_check.skip_local(prompt):
                    reply = unless_red(local_llm.ask, prompt, session_id or "default",
                                       history=chat.messages())
                if reply is not None and not fact_check.keep_local(prompt, reply):
                    # a fact the little model could stretch ("bats are super duper good at
                    # seeing"): ask the relay, keep this only as a careful fallback
                    print("(fact check: passing the Pi's answer up to be sure)", flush=True)
                    local_guess, reply = reply, None
        if reply is None:
            # Tier 3+: the relay (bigger models / OpenAI). Private-sounding? Ask first.
            tier = "relay"
            relay_text = chat.for_relay(prompt)   # "please" goes up with what it answers
            private = privacy.needs_asking(relay_text)
            if private:
                print(f"(privacy: found {', '.join(private)}; asking before the cloud)", flush=True)
                if not ask_yes_no(privacy.cloud_question(private)):
                    log_turn("privacy:kept", notes=f"not sent to the cloud: {', '.join(private)}")
                    say(privacy.KEPT)
                    if local_guess:
                        say(fact_check.hedge(local_guess))
                    go_to_sleep()
                    return
                log_turn("privacy:sent", notes=f"sent after a yes: {', '.join(private)}")
                face.state("thinking")
            elif CLOUD_ASK and not cloud_ok:
                ask_cloud(prompt, local_guess)   # the relay costs money: ask first
                return
            try:
                reply = unless_red(post_chat, relay_text, session_id)
            except OutOfCredits:
                raise
            except Exception as e:
                if not local_guess:
                    raise
                print(f"(relay unavailable: {e!r}; using the Pi's answer, hedged)", flush=True)
                tier, reply, checked = "local_llm", fact_check.hedge(local_guess), "failed"
            if tier == "relay":
                reply, checked = fact_check.review(
                    prompt, reply,
                    lambda text: unless_red(post_chat, text, f"check-{uuid.uuid4().hex[:8]}",
                                            timeout=fact_check.SECONDS))
        log_turn(tier, prompt, reply, seconds=time.time() - started, cloud=(tier == "relay"),
                 notes=f"fact check: {checked}" if checked != "skipped" else None)
        mood = "mischief_talk" if is_joke_request(prompt) else "speaking"
        thinking_tier = tier in ("local_llm", "relay")
        # "Well, actually..." only for a correction that passed the fact check
        trusted = checked in ("ok", "fix") or fact_check.MODE == "off"
        corrected = well_actually(reply) if thinking_tier and mood == "speaking" and trusted else None
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
        chat.add(prompt, reply)
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
    except RedCutIn:
        print("Red alert: dropped the answer in progress", flush=True)
        log_turn("red_alert", prompt, seconds=time.time() - started,
                 notes="answer dropped for a tornado warning")
        go_to_sleep()       # the main loop starts Red Alert on its next turn
        return
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
    if FOLLOWUP_SECONDS > 0 and not panel.hush:   # no follow-up for a quiet panel question
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


def red_alert_moment(step: str):
    """Red Alert (a tornado warning here): 'start', 'ring' (no answer yet) or 'end'.
    Said in any mode, day or night; the red screen itself comes from red.face_message()."""
    global red_test_phone
    test = red.test
    face.send(red.face_message())
    face.caption("")
    if step == "end":
        line = red_alert.over_line(test)
        print("Red alert: over", flush=True)
        log_turn("red_alert", reply=line, notes="over" + (" (test)" if test else ""))
        say(line)
        go_to_sleep()
        return
    first = step == "start"
    if first and test and red_test_phone:
        red_test_phone = False
        alerts.send_phone_alert(red_alert.phone_text(red.expires, test=True))
    text = red_alert.spoken(red.expires, first, test)
    print(f"Red alert: {step}{' (test)' if test else ''}", flush=True)
    log_turn("red_alert", reply=text, notes=step + (" (test)" if test else ""))
    face.state("speaking")
    earcons.red_alert()
    say(text)
    go_to_sleep()        # awake and listening, even if she was resting: a tap or her name stops the alarm


def answer_door(m: dict):
    """A message through the door: answer-only, never a command, never from her memories."""
    who = door_mod.title(m["from"])
    text = m["text"]
    prompt = normalize(text)
    private = privacy.find(text)     # nobody to ask, so private-looking = stays local, unread
    started, tier, reply = time.time(), "door", door_mod.own_answer(text)
    local_guess = None
    try:
        if reply is None:
            tier = "skill"
            reply = local_skills.handle(prompt)
        if reply is None:
            tier = "local_llm"
            if not (door_mod.CLOUD and not private and fact_check.skip_local(prompt)):
                reply = unless_red(local_llm.ask, prompt, f"door-{m['from']}")
            if reply is not None and door_mod.CLOUD and not private \
                    and not fact_check.keep_local(prompt, reply):
                local_guess, reply = reply, None
        if reply is None and door_mod.CLOUD and not private:
            tier = "relay"
            try:
                reply = unless_red(post_chat, text, f"door-{m['from']}")
                reply, _ = fact_check.review(
                    text, reply,
                    lambda t: unless_red(post_chat, t, f"check-{uuid.uuid4().hex[:8]}",
                                         timeout=fact_check.SECONDS))
            except Exception:
                if not local_guess:
                    raise
                tier, reply = "local_llm", fact_check.hedge(local_guess)
    except RedCutIn:
        print("Message door: answer dropped for Red Alert", flush=True)
        log_turn("door", text, notes=f"from {m['from']} (dropped for Red Alert)")
        door.reply(m, "Something urgent came up here, so I had to stop. Please ask me again later.")
        return
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
        elif morse.ENABLED and morse.find_code(text):
            code = morse.find_code(text)       # a letter in Morse: she beeps it, then reads it
            say(door_mod.announce(m["from"], "It's in Morse code!"))
            play_morse(code)
            say(morse.read_reply(code))
        else:
            say(door_mod.announce(m["from"], text))
            say(reply)
    else:
        face.notice(f"Message from {who}" + (" (private)" if private else f": {text[:120]}"))


def answer_chess_letter(m: dict):
    """A chess move by letter (chess_mail.py). Quick and silent: the reply goes
    straight back; the board shows on her face only while she's free."""
    started = time.time()
    try:
        r = letters.handle(m["from"], m["text"])
    except Exception as e:
        print("Chess by letter: failed:", repr(e), flush=True)
        r = chess_mail.Result("Sorry, my chess board fell off the table. Try that move again?")
    door.reply(m, r.reply, sign_off=False)
    log_turn("door_chess", m["text"], r.reply, seconds=time.time() - started,
             notes=f"from {m['from']}")
    if mode != "sleep":
        return
    if r.show:
        face.send(f"chessmail:{m['from']}:{r.show}")
    if r.event and r.line:
        if door_mod.SPEAK and not quiet_hours.is_night():
            earcons.listening()
            say(r.line)
            go_to_sleep()
        else:
            face.notice(r.line)


def mystery_command(prompt: str):
    """Who's the Trickster? (trickster.py): the score, a vote, or a new game."""
    if re.search(r"\b(score|scores|solved|how many|record)\b", prompt):
        reply = trickster.score_text()
        log_turn("command:trickster_score", prompt, reply)
        say(reply)
        go_to_sleep()
        return
    who = trickster.node_key(re.sub(r"\b(trickster|mystery)\b", "", prompt))
    if who and re.search(r"\b(vote|voting|think|guess|accuse|suspect|it'?s|it is|it was|bet)\b", prompt):
        log_turn("command:trickster_vote", prompt)
        say(pick([f"Your vote is in: {trickster.title(who)}!", f"{trickster.title(who)}? Ooh. Noted!"]))
        go_to_sleep()
        face.trickster("vote:" + who)
        return
    log_turn("command:trickster", prompt)
    say(pick(["Ooh, a mystery! One of the nodes is a trickster. Watch my screen closely!",
              "Who's the trickster? Watch the nodes do their chores, and tap the bell when you've got a hunch.",
              "Mystery time! Somebody's pulling kind little pranks. Help me catch them!"]))
    go_to_sleep()
    face.trickster()


def play_morse(code: str):
    """Beep Morse code out loud while the telegraph tape on her face follows along."""
    if not code or red_waiting():
        return
    if panel.hush:
        panel.said(code)             # asked quietly from the panel: just show it
        return
    face.state("morse")
    start = time.time() + 0.2        # aplay takes a moment to get going
    face.send(morse.face_message(code, start))
    morse.play(code)
    time.sleep(0.6)                  # let the last letter show on the tape
    flush_audio()                    # don't hear her own beeps


def listen_for_morse():
    """'Hey Chatty, listen for Morse': record beeps on the mic (nothing is kept) and read them."""
    say(pick(["Okay, I'm all ears. Send your Morse after the chime.",
              "Ready! Start beeping after the chime. I'll stop when it goes quiet."]))
    face.state("listening")
    face.caption("")
    earcons.listening()
    flush_audio()
    seconds = morse.LISTEN_SECONDS
    face.listen(seconds)
    audio, started, checked, result = bytearray(), time.time(), 0.0, None
    while time.time() - started < seconds:
        watchdog.ping()
        if red_waiting():
            return                   # Red Alert goes first
        try:
            audio += q.get(timeout=0.5)
        except queue.Empty:
            continue
        if time.time() - checked < 1.0:
            continue
        checked = time.time()
        result = morse.decode_audio(bytes(audio), CAPTURE_RATE)
        if result:
            face.caption(result["code"][-40:])       # the dits and dahs so far
            if result["quiet_after"] >= morse.END_QUIET:
                break
        elif time.time() - started > morse.GIVE_UP:
            break
    result = morse.decode_audio(bytes(audio), CAPTURE_RATE) if audio else None
    audio.clear()                    # the recording is gone as soon as it's read
    if not result:
        log_turn("command:morse_listen", notes="no beeps")
        say(pick(["I didn't hear any beeps. Try a little louder, or a bit closer to me.",
                  "Hmm, no Morse that I could hear. Want to try again?"]))
        return
    face.caption(result["code"][-40:])
    print(f"(morse heard: {result['code']!r} -> {result['text']!r}, {result['wpm']} WPM, "
          f"{result['tone']} Hz)", flush=True)
    reply = morse.read_reply(result["code"])
    if result["text"].strip("? "):
        reply += f" You were sending about {round(result['wpm'])} words a minute."
    log_turn("command:morse_listen", result["text"], reply)
    say(reply)


def morse_command(prompt: str, kind: str, value: str):
    """Morse code: send it as beeps, read spoken dots and dashes, listen for beeps, teach, explain."""
    if kind == "send":
        text, cut = morse.fit(value)
        code = morse.encode(text)
        if not code:
            say("I couldn't find any letters or numbers in that to send.")
        elif panel.hush:
            say(f'"{text}" in Morse code: {code}')
        else:
            say(pick([f"Here's {text} in Morse code. Listen!", f"{text}, in Morse. Here goes!"])
                + (" It's a long one, so here's the start." if cut else ""))
            play_morse(code)
            if len(code.replace(" ", "").replace("/", "")) <= 12:
                say(morse.spoken(code) + ".")
        log_turn("command:morse_send", prompt, code)
    elif kind == "read":
        reply = morse.read_reply(value)
        log_turn("command:morse_read", prompt, reply)
        say(f"{value}: {reply}" if panel.hush else reply)
    elif kind == "listen":
        listen_for_morse()
    elif kind == "teach":
        letter, hook = random.choice(morse.TEACH)
        log_turn("command:morse_teach", prompt, letter)
        say(f"Here's the letter {letter}. Listen!")
        play_morse(morse.CODE[letter])
        say(f"{letter} is {hook}")
    else:
        log_turn("command:morse_about", prompt)
        say(morse.ABOUT)
    go_to_sleep()


def handle_command(text: str, ran_long: bool = False):
    """Handle one finished utterance heard while active."""
    global mode, name_heard
    print("Heard:", text, flush=True)
    face.caption(fix_name(text))
    panel.heard(fix_name(text))
    name_heard = name_word(text)
    prompt = strip_wake(text)
    if chat.wants_new_subject(prompt):
        chat.forget()
        log_turn("command:new_subject")
        say(pick(["Sure! What's on your mind?", "Okay, fresh start. What's up?"]))
        start_listening(LISTEN_SECONDS)
        return
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
    morse_ask = morse.asked(prompt) if prompt else None    # spoken dots and dashes run long
    if prompt and (ran_long or (len(prompt.split()) > MAX_QUESTION_WORDS and not morse_ask)):
        print("(sounds like background talk; not sending to the AI)", flush=True)
        log_turn("filtered_background", prompt, notes="hit length cap" if ran_long else "too many words")
        say(pick(UNCLEAR_LINES))
        go_to_sleep()
        return
    if not prompt:
        start_listening(LISTEN_SECONDS)  # they just said "Chatty" again
        return
    if morse_ask:
        morse_command(prompt, *morse_ask)
        return
    if re.search(r"\bchess\b", prompt) and re.search(r"\b(score|scores|winning|won|record|results?|how many)\b", prompt):
        reply = chess_match.score_text()
        log_turn("command:chess_score", prompt, reply)
        say(reply)
        go_to_sleep()
        return
    if re.search(r"\bchess\b", prompt) and re.search(r"\b(claude|chat ?gpt|by letter|by mail|letters?)\b", prompt):
        who = "chatgpt" if re.search(r"\bchat ?gpt\b", prompt) else "claude" if "claude" in prompt else None
        reply = letters.status_text(who)
        log_turn("command:chess_letter", prompt, reply)
        say(reply)
        go_to_sleep()
        if who and chess_mail.load().get(who):
            face.send(f"chessmail:{who}:0")      # show the board too
        return
    if trickster.ENABLED and (re.search(r"\btrickster\b|\bmystery game\b|\b(play|start|host)\b.*\bmystery\b|"
                                        r"\bwho ?dunn?it\b|\bwho done it\b", prompt)
                              or (re.search(r"\b(i vote|vote for|my vote)\b", prompt) and trickster.node_key(prompt))):
        mystery_command(prompt)
        return
    if trickster.ENABLED and re.search(r"\b(call|ring|start|have|emergency|tea) (a |an |the )?(emergency |tea )?(meeting|bell)\b", prompt):
        log_turn("command:trickster_meeting", prompt)
        say(pick(["Ding ding! Tea meeting!", "Ringing the bell! Everybody to the mailbox."]))
        go_to_sleep()
        face.trickster("meeting")
        return
    topic = imagine.asked(prompt)
    if topic is not None:
        log_turn("command:imagine", prompt)
        imagine_out_loud(imagine.idea(topic=topic), intro=not topic)
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
    if bedtime.asked(prompt):
        reply, tonight = winddown.answer()
        log_turn("command:bedtime", prompt, reply)
        say(reply)
        if tonight:
            tuck_in()
        else:
            go_to_sleep()
        return
    if bedtime.asked_roll_call(prompt):
        reply = winddown.roll_call()
        log_turn("command:roll_call", prompt, reply)
        say(reply)
        go_to_sleep()
        return
    if morning_briefing.asked(prompt):
        reply = morning.answer()
        log_turn("command:briefing", prompt, reply)
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
    who = homecoming.asked_who(prompt, welcome.people)
    if who is not None:
        reply = welcome.answer(who)
        log_turn("command:homecoming", prompt, reply)
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
    if prompt in STOP_PHRASES or is_just_no(prompt):
        log_turn("command:stop", prompt)
        say(pick(GOODBYES))
        go_to_sleep()
        return
    if prompt in THANKS_PHRASES or is_just_thanks(prompt):
        log_turn("command:thanks", prompt)
        say(pick(THANKS_REPLIES))
        go_to_sleep()
        return
    answer(prompt)


def panel_status():
    """What the remote panel shows about her (written to its status file; panel_link.py)."""
    return panel_link.status(VOICE_WAKE, convo.indicator(), quiet_hours.is_night(), node_net,
                             clock_timers, rain_ahead, sky_watch.raining)


def handle_panel(kind: str, text: str):
    """A request from the remote panel. Questions go through handle_command like
    spoken ones (so "shut down" still asks first); quiet ones aren't spoken."""
    global mode
    print(f"Panel: {kind}" + (f" {text!r}" if text else ""), flush=True)
    was = mode
    if kind == "wake":
        if mode in ("sleep", "resting"):
            wake_up("panel")
        return
    if kind == "rest":
        if mode != "resting":
            rest()
        return
    if kind in ("yes", "no"):
        with panel.turn(quiet=panel.last_quiet):
            confirmed() if kind == "yes" else declined()
        return
    if kind == "say":
        with panel.turn():
            log_turn("panel:say", reply=text)
            say(text)
    else:
        _woke("panel")
        mode = "active"
        with panel.turn(quiet=kind == "hush"):
            typed = panel_link.typed_question(text)    # typed like spoken words
            if typed:
                handle_command(typed)
        if mode == "active" and kind == "hush":
            go_to_sleep()           # nobody is in the room to ask a follow-up
    if kind == "say" and mode in ("sleep", "active"):
        go_to_sleep()
    if was == "resting" and mode == "sleep" and kind == "hush":
        mode = "resting"            # asked quietly while she was resting: back to bed
        face.state("resting")


watchdog.ready()
while True:
    watchdog.ping()                 # "still alive" for systemd (WatchdogSec)
    try:
        pcm = q.get(timeout=0.5)
    except queue.Empty:
        pcm = None

    now = time.time()

    touch = touch_event()
    panel.write(mode, panel_status())
    request = panel.next(mode)
    if request:
        handle_panel(*request)
        panel.write(mode, panel_status(), force=True)
        continue
    if touch == "rest" and mode != "resting":
        rest()
        continue
    if touch == "wake" and red.acknowledge():
        print("Red alert: heard (tap)", flush=True)
        say(red_alert.acknowledged_line(red.test))   # the alarm stops; the red screen stays
        go_to_sleep()
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

    # Red Alert: a tornado warning for this spot (any mode, day or night, before anything else)
    if red_test_wanted is not None:
        red_test_phone, red_test_wanted = red_test_wanted, None
        red.start_test(now)
    red_step = red.step(alert_watch.red_warning(), now)
    if red_step:
        red_alert_moment(red_step)
        continue
    if red.face_due(now):           # keep the face in step (it may have restarted)
        face.send(red.face_message())
    free_mode = "red alert" if red.on else mode    # no chit-chat while it's on

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

    # things she says on her own (announcements.py, in this order, first one wins):
    # the morning briefing, the bedtime wind-down, rain on the way, rain or lightning
    # starting, her own health, "Welcome home" (each keeps its own time-of-day rules)
    news = extras.next_due(free_mode)
    if news:
        print(f"{news.label}:", news.text, flush=True)
        log_turn(news.kind, reply=news.text)
        say(*news.say_args)
        if news.after == "tuck_in":
            tuck_in()
        else:
            go_to_sleep()
        continue

    # a chess move by letter (answered right away; quiet unless a game starts or ends)
    chess_msg = door.due_chess()
    if chess_msg:
        answer_chess_letter(chess_msg)

    # a typed message through the door (only while she's free)
    door_msg = door.due(free_mode)
    if door_msg:
        answer_door(door_msg)
        go_to_sleep()
        continue

    # something she noticed while pondering (only said while she's awake and free)
    if notices and not red.on:
        text = notices.pop(0)
        if mode == "sleep" and text.startswith("imagine:"):
            text = text[len("imagine:"):].strip()     # a daydream she wants to share
            if text:
                print("Daydream from the face:", text, flush=True)
                log_turn("notice", reply=text, notes="daydream")
                imagine_out_loud(text)
            go_to_sleep()
            continue
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
                if reply in CONFIRM_NOISE:
                    print("(stray word, still waiting for yes or no)", flush=True)
                elif reply in YES_WORDS or set(reply.split()) & {"yes", "yeah", "yep", "sure"}:
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

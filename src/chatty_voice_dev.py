import os, json, queue, subprocess, time, re, threading
from datetime import datetime

from weather_lookup import summarize_forecast
import numpy as np
import requests
from vosk import Model, KaldiRecognizer
from dotenv import load_dotenv

import math

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
CAPTURE_DEVICE = os.getenv("CHATTY_CAPTURE_DEVICE", "plughw:1,0")
CAPTURE_RATE = int(os.getenv("CHATTY_CAPTURE_RATE", "44100"))

# How many bytes to read per loop from arecord stdout
READ_BYTES = int(os.getenv("CHATTY_READ_BYTES", "4096"))
RMS_GATE = float(os.getenv("CHATTY_RMS_GATE", "250"))  # ignore audio below this energy

# TTS output device (aplay)
PLAY_DEVICE = os.getenv("CHATTY_PLAY_DEVICE", "plughw:1,0")


# ----------------------------
# TTS
# ----------------------------
def speak(text: str):
    text = (text or "").strip()
    if not text:
        return
    p1 = subprocess.Popen(["espeak-ng", "--stdout", text], stdout=subprocess.PIPE)
    subprocess.run(["aplay", "-D", PLAY_DEVICE], stdin=p1.stdout, check=False)
    try:
        p1.stdout.close()
    except Exception:
        pass


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
# Wake/command logic (kept simple + robust)
# ----------------------------
WAKE_VARIANTS = {"chatty", "caddy", "kitty", "charity", "jackie", "jockey", "heidi"}
CONFIRM_WORDS = {"yes", "yeah", "yep", "sure", "okay", "ok", "please"}
DENY_WORDS = {"no", "nope", "nah", "stop", "quiet"}


def post_chat(text: str) -> str:
    r = requests.post(
        API_URL,
        json={"text": text},
        headers={"X-Chatty-Token": TOKEN},
        timeout=30,
    )
    r.raise_for_status()
    j = r.json()
    return j.get("reply", "").strip()


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", (s or "").lower()).strip()


# ----------------------------
# Main
# ----------------------------
print("Loading STT model...", flush=True)
model = Model(MODEL_PATH)
rec = KaldiRecognizer(model, VOSK_RATE)

# start capture
t = threading.Thread(target=arecord_reader, daemon=True)
t.start()

speak("Chatty node online.")
print(
    f"Capture: {CAPTURE_DEVICE} @ {CAPTURE_RATE}Hz -> resample {VOSK_RATE}Hz",
    flush=True,
)
print("Say something. (Wake me by saying 'Chatty ...')", flush=True)

mode = "sleep"
pending_until = 0.0
active_until = 0.0

while True:
    pcm = q.get()

    # DEV health: queue depth + rough audio level every ~2 seconds
    if not hasattr(time, "_last_dev_print"):
        time._last_dev_print = 0.0
    nowp = time.time()
    if nowp - time._last_dev_print > 2.0:
        time._last_dev_print = nowp
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        GAIN = 6.0  # software boost for diagnostics only
        x *= GAIN
        x = np.clip(x, -32768, 32767)
        rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
        dbfs = 20.0 * math.log10(max(rms, 1.0) / 32768.0)
        print(f"DEV qsize={q.qsize():>2}  rms={rms:8.1f}  dBFS={dbfs:6.1f}", flush=True)

    pcm16 = resample_pcm16_mono(pcm, CAPTURE_RATE, VOSK_RATE)

    if rec.AcceptWaveform(pcm16):
        res = json.loads(rec.Result())
        text = normalize(res.get("text", ""))
        if not text:
            continue

        print("Heard:", text, flush=True)
        now = time.time()
        words = set(text.split())
        woke = any(w in WAKE_VARIANTS for w in words)

        if mode == "sleep":
            if woke:
                prompt = " ".join(
                    [w for w in text.split() if w not in WAKE_VARIANTS]
                ).strip()

                if prompt:
                    try:
                        prompt_l = prompt.lower()
                        if "sleep" in prompt_l and ("go to sleep" in prompt_l or "sleep now" in prompt_l):
                            reply = "Okay. Going to sleep."
                            print("Chatty:", reply, flush=True)
                            speak(reply)
                            mode = "sleep"
                            continue
                        elif "weather" in prompt_l or "forecast" in prompt_l:
                            if "tomorrow" in prompt_l:
                                reply = summarize_forecast("tomorrow")
                            else:
                                reply = summarize_forecast("today")
                        elif "time" in prompt_l:
                            reply = f"The time is {datetime.now().strftime('%I:%M %p')}."
                        elif (
                            "what day" in prompt_l
                            or "what date" in prompt_l
                            or "todays date" in prompt_l
                            or "today's date" in prompt_l
                            or "what day is it" in prompt_l
                        ):
                            reply = f"Today's date is {datetime.now().strftime('%B %d, %Y')}."
                        else:
                            reply = post_chat(prompt)

                        print("Chatty:", reply, flush=True)
                        speak(reply)
                    except Exception as e:
                        print("Error:", repr(e), flush=True)
                        speak("Sorry, I hit an error.")
                else:
                    speak("Yes?")
                    mode = "active"
                    active_until = now + 12.0
            continue

        if mode == "active":
            if now > active_until:
                mode = "sleep"
                continue

            prompt = " ".join(
                [w for w in text.split() if w not in WAKE_VARIANTS]
            ).strip()
            if not prompt:
                continue

            try:
                prompt_l = prompt.lower()
                if "weather" in prompt_l or "forecast" in prompt_l:
                    if "tomorrow" in prompt_l:
                        reply = summarize_forecast("tomorrow")
                    else:
                        reply = summarize_forecast("today")
                else:
                    reply = post_chat(prompt)

                print("Chatty:", reply, flush=True)
                speak(reply)
            except Exception as e:
                print("Error:", repr(e), flush=True)
                speak("Sorry, I hit an error.")

            mode = "sleep"

    else:
        pres = json.loads(rec.PartialResult())
        ptext = normalize(pres.get("partial", ""))
        if ptext:
            print("Partial:", ptext, flush=True)

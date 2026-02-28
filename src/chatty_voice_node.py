import os, json, queue, subprocess, time, re
import audioop
from datetime import datetime
import requests
import sounddevice as sd
from vosk import Model, KaldiRecognizer
from dotenv import load_dotenv

# ---- secrets ----
load_dotenv("/etc/chatty/secrets.env")

BASE = os.getenv("CHATTY_ENDPOINT", "https://ceucomics.com").rstrip("/")
TOKEN = os.getenv("CHATTY_TOKEN")
if not TOKEN:
    raise RuntimeError("CHATTY_TOKEN not found in /etc/chatty/secrets.env")

API_URL = f"{BASE}/chat"

# ---- audio/model ----
MODEL_PATH = "/home/pi/vosk-model/vosk-model-small-en-us-0.15"
VOSK_RATE = 16000  # Vosk model expects 16kHz
BLOCK_SIZE = 4000  # smaller helps reduce "input overflow" on slower Pis
PLAY_DEVICE = "hw:0,0"  # your headphones output

# Optional: allow selecting input device (USB mic) by substring or index.
# Example:
#   export CHATTY_INPUT_DEVICE="USB PnP Audio"
#   export CHATTY_INPUT_DEVICE="1"   (device index)
INPUT_DEVICE_ENV = os.getenv("CHATTY_INPUT_DEVICE", "").strip()

q = queue.Queue()

def callback(indata, frames, t, status):
    if status:
        print(status, flush=True)
    q.put(bytes(indata))

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

def pick_input_device():
    if not INPUT_DEVICE_ENV:
        return None

    # If numeric, treat as index
    if INPUT_DEVICE_ENV.isdigit():
        return int(INPUT_DEVICE_ENV)

    # Otherwise match by name substring
    target = INPUT_DEVICE_ENV.lower()
    try:
        devs = sd.query_devices()
        for i, d in enumerate(devs):
            name = str(d.get("name", "")).lower()
            if target in name and d.get("max_input_channels", 0) > 0:
                return i
    except Exception:
        pass
    return None

# ---- wake / sleep logic ----
MODE = "sleep"
ACTIVE_UNTIL = 0.0
PENDING_CONFIRM_UNTIL = 0.0

# Common Vosk-small “chatty” mishears observed in your logs
WAKE_VARIANTS = {
    "chatty",
    "caddy", "kitty", "fatty", "charity", "heidi", "jackie", "jockey",
    "crappy", "czech", "karate",
}

CONFIRM_WORDS = {"yes", "yeah", "yep", "sure", "okay", "ok", "please"}
DENY_WORDS = {"no", "nope", "nah", "never", "stop", "quiet"}
SLEEP_WORDS = {"goodnight", "good night", "thanks", "thank you", "bye"}

def normalize_words(text: str):
    t = (text or "").lower().strip()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t

def is_wake(text: str) -> bool:
    t = normalize_words(text)
    if not t:
        return False
    words = t.split()

    # If "chatty" appears anywhere, wake.
    if "chatty" in words:
        return True

    # If first word is a known variant, wake.
    if words and words[0] in WAKE_VARIANTS:
        return True

    # If phrase like "hello ___" where second word is a variant, wake.
    if len(words) >= 2 and words[0] in {"hello", "hey", "hi"} and words[1] in WAKE_VARIANTS:
        return True

    return False

def strip_wake(text: str) -> str:
    t = normalize_words(text)
    words = t.split()
    if not words:
        return ""

    # Remove greeting + wakeword if present
    if len(words) >= 2 and words[0] in {"hello", "hey", "hi"} and (words[1] in WAKE_VARIANTS or words[1] == "chatty"):
        return " ".join(words[2:]).strip()

    # Remove leading wake variant
    if words[0] in WAKE_VARIANTS or words[0] == "chatty":
        return " ".join(words[1:]).strip()

    # Remove wakeword anywhere (rare), keep the rest
    if "chatty" in words:
        idx = words.index("chatty")
        return " ".join(words[idx+1:]).strip()

    return t

def local_tool_reply(user_text: str):
    t = normalize_words(user_text)

    # Time/date handled locally (fast + reliable)
    if ("what time" in t) or ("current time" in t) or ("time is it" in t):
        return datetime.now().strftime("It's %I:%M %p.").lstrip("0")

    if ("what day" in t) or ("what date" in t) or ("today" in t and "date" in t):
        return datetime.now().strftime("Today is %A, %B %d, %Y.").replace(" 0", " ")

    return None

print("Loading STT model...", flush=True)
model = Model(MODEL_PATH)
rec = KaldiRecognizer(model, VOSK_RATE)

speak("Chatty node online.")
print("Say something. (Wake me by saying 'Chatty ...')", flush=True)

device = pick_input_device()
if device is not None:
    print(f"Using input device: {device}", flush=True)

# ---- capture rate selection + resampler ----
# Your mic (e.g., CMTECK) may reject 8000/16000/22050 and only accept 44100/48000.
# We capture at a supported rate, then resample down to VOSK_RATE for recognition.
def pick_capture_rate(dev):
    try:
        default_sr = int(sd.query_devices(dev, 'input').get('default_samplerate', 44100))
    except Exception:
        default_sr = 44100
    candidates = []
    for r in (default_sr, 44100, 48000):
        if r not in candidates:
            candidates.append(r)
    for r in candidates:
        try:
            sd.check_input_settings(device=dev, samplerate=r, channels=1, dtype='int16')
            return r
        except Exception:
            pass
    raise RuntimeError(f'No supported capture sample rate found for input device {dev}')

CAPTURE_RATE = pick_capture_rate(device if device is not None else sd.default.device[0])
print(f'Capture rate: {CAPTURE_RATE} Hz  -> resample to {VOSK_RATE} Hz for Vosk', flush=True)

_resample_state = None
def to_vosk_rate(pcm16: bytes) -> bytes:
    global _resample_state
    if CAPTURE_RATE == VOSK_RATE:
        return pcm16
    out, _resample_state = audioop.ratecv(pcm16, 2, 1, CAPTURE_RATE, VOSK_RATE, _resample_state)
    return out


try:
    with sd.RawInputStream(
        samplerate=CAPTURE_RATE,
        blocksize=BLOCK_SIZE,
        dtype="int16",
        channels=1,
        callback=callback,
        device=device,
    ):
        while True:
            data = to_vosk_rate(q.get())
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = (result.get("text") or "").strip()
                if not text:
                    continue

                print("Heard:", text, flush=True)

                now = time.time()
                tnorm = normalize_words(text)

                # If user says sleep/thanks, go quiet (even if active)
                if any(w in tnorm for w in SLEEP_WORDS):
                    MODE = "sleep"
                    ACTIVE_UNTIL = 0.0
                    PENDING_CONFIRM_UNTIL = 0.0
                    speak("Okay. Resting.")
                    continue

                # If currently active window, accept everything as a prompt
                if MODE == "active" and now <= ACTIVE_UNTIL:
                    user_text = tnorm
                else:
                    # Not active: require wake (or variants)
                    if not is_wake(text):
                        continue

                    # Wake detected: strip wake word; if nothing left, do a gentle confirm
                    user_text = strip_wake(text)
                    if not user_text:
                        MODE = "sleep"
                        PENDING_CONFIRM_UNTIL = now + 6.0
                        speak("Yes? Do you need something?")
                        continue

                    MODE = "active"
                    ACTIVE_UNTIL = now + 20.0  # short “awake window”

                # If we asked “do you need something?”, interpret confirm/deny
                if PENDING_CONFIRM_UNTIL and now <= PENDING_CONFIRM_UNTIL:
                    if any(w in tnorm.split() for w in CONFIRM_WORDS):
                        MODE = "active"
                        ACTIVE_UNTIL = now + 20.0
                        PENDING_CONFIRM_UNTIL = 0.0
                        speak("Okay. I'm here.")
                        continue
                    if any(w in tnorm.split() for w in DENY_WORDS):
                        MODE = "sleep"
                        PENDING_CONFIRM_UNTIL = 0.0
                        speak("Okay. Staying quiet.")
                        continue
                    # Not clear -> keep waiting
                    continue
                PENDING_CONFIRM_UNTIL = 0.0

                # Local tools (time/date) first
                tool = local_tool_reply(user_text)
                if tool:
                    print("Chatty:", tool, flush=True)
                    speak(tool)
                    continue

                # Remote relay
                r = requests.post(
                    API_URL,
                    json={"text": user_text},
                    headers={"X-Chatty-Token": TOKEN},
                    timeout=30,
                )
                if r.status_code != 200:
                    print("Relay error:", r.status_code, r.text, flush=True)
                    speak("Relay error.")
                    continue

                reply = (r.json().get("reply") or "").strip()
                print("Chatty:", reply, flush=True)
                speak(reply)

except KeyboardInterrupt:
    print("\nStopping.", flush=True)
    speak("Chatty node offline.")
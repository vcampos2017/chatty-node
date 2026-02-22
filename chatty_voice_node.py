import os, json, queue, subprocess, requests, time
import sounddevice as sd
from vosk import Model, KaldiRecognizer
from dotenv import load_dotenv

load_dotenv("/etc/chatty/secrets.env")

BASE = os.getenv("CHATTY_ENDPOINT", "https://ceucomics.com").rstrip("/")
TOKEN = os.getenv("CHATTY_TOKEN")
if not TOKEN:
    raise RuntimeError("CHATTY_TOKEN not found")

API_URL = f"{BASE}/chat"
MODEL_PATH = "/home/pi/vosk-model/vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000
PLAY_DEVICE = "hw:0,0"   # headphones
q = queue.Queue()

# --- Compassionate wake state machine ---
MODE = "sleep"  # "sleep" or "active"
PENDING_CONFIRM_UNTIL = 0.0  # unix time
LAST_ACTIVE_AT = 0.0

# Vosk often mishears "Chatty"
WAKE_WORDS = (
    "chatty", "chatting",
    "caddy", "code caddy", "oh caddy",
    "jockey", "czech team", "crappy"
)

# Soft triggers (looser, more lifelike)
SOFT_TRIGGERS = (
    "can you hear me",
    "are you there",
    "hello",
    "hey",
    "excuse me",
    "i need help",
    "help me",
)

CONFIRM_WORDS = ("yes", "yeah", "yep", "please", "ok", "okay", "wake up", "go ahead", "sure")
DENY_WORDS = ("no", "nope", "never mind", "nevermind", "cancel", "stop", "ignore", "go away")

EXIT_PHRASES = (
    "thank you", "thanks",
    "that's all", "that is all",
    "goodbye", "bye",
    "sleep", "go offline", "go quiet"
)

# Ignore filler in active mode (don't forward to the API)
FILLER_PHRASES = ("huh", "um", "uh", "hmm", "mm", "what", "okay", "ok")

# Auto-sleep after inactivity (seconds)
ACTIVE_TIMEOUT = 45.0

    "thank you", "thanks",
    "that's all", "that is all",
    "goodbye", "bye",
    "sleep", "go offline", "go quiet"
)

def callback(indata, frames, time_info, status):
    if status:
        print(status)
    q.put(bytes(indata))

def speak(text: str):
    text = text.strip()
    if not text:
        return
    p1 = subprocess.Popen(["espeak-ng", "--stdout", text], stdout=subprocess.PIPE)
    subprocess.run(["aplay", "-D", PLAY_DEVICE], stdin=p1.stdout, check=False)
    p1.stdout.close()

print("Loading STT model...")
model = Model(MODEL_PATH)
rec = KaldiRecognizer(model, SAMPLE_RATE)

speak("Chatty node online.")
print("\nSay a short sentence. Press Ctrl+C to stop.\n")

try:
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=8000,
        dtype="int16",
        channels=1,
        callback=callback,
    ):
        while True:
            data = q.get()
            if not rec.AcceptWaveform(data):
                continue

            result = json.loads(rec.Result())
            text = (result.get("text") or "").strip()
            if not text:
                continue

            print("Heard:", text)
            t = text.lower()
            now = time.time()

            # 1) If pending confirmation, listen for confirm/deny
            if MODE == "sleep" and PENDING_CONFIRM_UNTIL and now <= PENDING_CONFIRM_UNTIL:
                if any(w in t for w in CONFIRM_WORDS) or any(w in t for w in WAKE_WORDS):
                    MODE = "active"
                    PENDING_CONFIRM_UNTIL = 0.0
                    LAST_ACTIVE_AT = now
                    speak("Okay. I'm here.")
                    # Don't forward the confirmation phrase itself
                    continue
                if any(w in t for w in DENY_WORDS):
                    PENDING_CONFIRM_UNTIL = 0.0
                    speak("Okay. Staying quiet.")
                    continue
                # Still waiting for confirmation
                continue

            # 2) Sleep mode: soft trigger -> gentle check-in
            if MODE == "sleep":
                hit_wake = any(w in t for w in WAKE_WORDS)
                hit_soft = any(w in t for w in SOFT_TRIGGERS)
                if hit_wake or hit_soft:
                    PENDING_CONFIRM_UNTIL = now + 8.0
                    speak("Yes? Did you mean to wake me?")
                continue

            # 3) Active mode: exit phrases -> sleep
            # Auto-sleep if idle
            if LAST_ACTIVE_AT and (now - LAST_ACTIVE_AT) > ACTIVE_TIMEOUT:
                MODE = "sleep"
                PENDING_CONFIRM_UNTIL = 0.0
                speak("Going quiet.")
                continue

            if ("thank you" in t) or ("thanks" in t) or any(x in t for x in EXIT_PHRASES):
                MODE = "sleep"
                PENDING_CONFIRM_UNTIL = 0.0
                speak("Okay. Going quiet.")
                continue

            # 4) Active mode: strip wake word prefix if present
            send_text = text
            for w in WAKE_WORDS:
                if t.startswith(w):
                    send_text = text[len(w):].strip(" ,.-")
                    break
            send_text = send_text.strip()
            if not send_text:
                continue

            # Ignore filler utterances while active
            if send_text.lower() in FILLER_PHRASES:
                continue

            LAST_ACTIVE_AT = now
            print("You:", send_text)

            r = requests.post(
                API_URL,
                json={"text": send_text},
                headers={"X-Chatty-Token": TOKEN},
                timeout=30,
            )
            if r.status_code != 200:
                print("Relay error:", r.status_code, r.text)
                speak("Relay error.")
                continue

            reply = (r.json().get("reply") or "").strip()
            print("Chatty:", reply)
            speak(reply)

except KeyboardInterrupt:
    print("\nStopping.")
    speak("Chatty node offline.")

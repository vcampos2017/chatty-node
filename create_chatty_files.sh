#!/bin/bash

echo "Creating Chatty module files..."

cat <<'EOF' > config.py
import os

HOME = os.path.expanduser("~")

SAMPLERATE = 48000
RECORD_SECONDS = 5
AUDIO_DEVICE_INDEX = 1

STATE_FILE = os.path.join(HOME, "chatty_state.txt")
SECRETS_FILE = os.path.join(HOME, "chatty_secrets.env")
AUDIO_FILENAME = os.path.join(HOME, "chatty_input.wav")

WAKE_WORDS = [
    "chatty",
    "hey chatty",
    "okay chatty",
]

CHAT_MODEL = "gpt-4.1-mini"
TRANSCRIBE_MODEL = "gpt-4o-transcribe"

STARTUP_MESSAGE = "Chatty is ready."
SLEEP_MESSAGE = "Chatty is going to sleep."
EOF


cat <<'EOF' > state.py
from config import STATE_FILE

def set_state(state: str) -> None:
    with open(STATE_FILE, "w") as f:
        f.write(state)
EOF


cat <<'EOF' > audio.py
import os
import re
import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write

from config import SAMPLERATE, RECORD_SECONDS, AUDIO_DEVICE_INDEX, AUDIO_FILENAME

def record_audio(filename: str = AUDIO_FILENAME) -> str:
    print("\nSpeak now...")
    audio = sd.rec(
        int(RECORD_SECONDS * SAMPLERATE),
        samplerate=SAMPLERATE,
        channels=1,
        device=AUDIO_DEVICE_INDEX
    )
    sd.wait()

    audio_int16 = np.int16(audio * 32767)
    write(filename, SAMPLERATE, audio_int16)
    return filename

def clean_text_for_speech(text: str) -> str:
    text = re.sub(r"[*_`#]", "", text)
    text = " ".join(text.split())
    return text

def speak_text(text: str) -> None:
    cleaned = clean_text_for_speech(text)
    safe_text = cleaned.replace('"', '\\"')
    os.system(f'espeak-ng "{safe_text}"')
EOF


cat <<'EOF' > ai.py
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

from config import SECRETS_FILE, CHAT_MODEL, TRANSCRIBE_MODEL

load_dotenv(SECRETS_FILE)
client = OpenAI()

def transcribe_audio(filename: str) -> str:
    with open(filename, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model=TRANSCRIBE_MODEL,
            file=audio_file
        )
    return transcript.text.strip()

def get_chatty_reply(text: str) -> str:
    current_time = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

    prompt = f"""You are Chatty, a local Raspberry Pi voice assistant.
Local system time is: {current_time}
User said: {text}

Answer naturally and helpfully. If the user asks for the time or date, use the local system time provided above.
"""

    response = client.responses.create(
        model=CHAT_MODEL,
        input=prompt
    )
    return response.output_text.strip()
EOF


cat <<'EOF' > main.py
import time

from config import WAKE_WORDS, STARTUP_MESSAGE
from state import set_state
from audio import record_audio, speak_text
from ai import transcribe_audio, get_chatty_reply

def strip_punctuation(text: str) -> str:
    return text.lower().strip(" ,.!?")

def detect_wake_word(text: str):
    heard = strip_punctuation(text)

    for wake in sorted(WAKE_WORDS, key=len, reverse=True):
        if heard.startswith(wake):
            cleaned = heard[len(wake):].strip(" ,.!?")
            return cleaned if cleaned else "Hello"

    return None

def main():
    print("Chatty continuous loop started. Press Ctrl+C to stop.")
    speak_text(STARTUP_MESSAGE)
    set_state("idle")

    while True:
        try:
            set_state("listening")
            filename = record_audio()

            print("Processing speech...")
            user_text = transcribe_audio(filename)
            print("You said:", user_text)

            if not user_text.strip():
                set_state("idle")
                time.sleep(1)
                continue

            cleaned_text = detect_wake_word(user_text)
            if cleaned_text is None:
                print("Wake word not detected.")
                set_state("idle")
                time.sleep(1)
                continue

            reply = get_chatty_reply(cleaned_text)
            print("Chatty:", reply)

            set_state("speaking")
            speak_text(reply)

            set_state("idle")
            time.sleep(2)

        except KeyboardInterrupt:
            set_state("sleepy")
            print("\nStopping Chatty.")
            time.sleep(3)
            break
        except Exception as e:
            print("Error:", e)
            set_state("idle")
            time.sleep(2)

if __name__ == "__main__":
    main()
EOF

echo "Chatty project files created successfully."

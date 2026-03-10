import re
import time
import os
import subprocess
from datetime import datetime

from config import WAKE_WORDS, STARTUP_MESSAGE
from state import set_state
from audio import record_audio, speak_text
from ai import transcribe_audio, get_chatty_reply

def strip_punctuation(text: str) -> str:
    return text.lower().strip(" ,.!?")

def detect_wake_word(text: str):
    heard = text.lower()
    heard = re.sub(r"[^a-z\s]", " ", heard)
    heard = " ".join(heard.split())

    for wake in sorted(WAKE_WORDS, key=len, reverse=True):
        wake_norm = wake.lower()
        wake_norm = re.sub(r"[^a-z\s]", " ", wake_norm)
        wake_norm = " ".join(wake_norm.split())
        if heard.startswith(wake_norm):
            cleaned = heard[len(wake_norm):].strip()
            return cleaned if cleaned else "Hello"

    return None
def is_puzzled_reply(reply: str) -> bool:
    reply_lower = reply.lower()
    puzzled_phrases = [
        "could you clarify",
        "can you clarify",
        "need more context",
        "more context",
        "more information",
        "could you explain",
        "can you provide more details",
        "what do you mean",
    ]
    return any(phrase in reply_lower for phrase in puzzled_phrases)


def ensure_face_running():
    face_script = os.path.expanduser("~/chatty_face.py")
    try:
        result = subprocess.run(
            ["pgrep", "-f", face_script],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            env["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")
            subprocess.Popen(
                ["python3", face_script],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1)
    except Exception as e:
        print(f"Warning: could not start face: {e}")



def handle_local_command(text: str):
    text = text.lower().strip()

    if "what time is it" in text:
        now = datetime.now().strftime("%I:%M %p")
        return f"The time is {now}."

    if "what day is it" in text:
        day = datetime.now().strftime("%A")
        return f"Today is {day}."

    if "what is today's date" in text or "what is todays date" in text:
        today = datetime.now().strftime("%B %d, %Y")
        return f"Today's date is {today}."

    if "go to sleep" in text or "please sleep" in text:
        return "__sleep__"

    return None


def main():
    ensure_face_running()
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

            set_state("thinking")
            local_reply = handle_local_command(cleaned_text)
            if local_reply == "__sleep__":
                set_state("sleepy")
                speak_text("Okay. Going to sleep.")
                print("Chatty: Okay. Going to sleep.")
                time.sleep(2)
                break

            if local_reply is not None:
                reply = local_reply
                print("Chatty:", reply)
                set_state("speaking")
                speak_text(reply)
            else:
                set_state("thinking")
                reply = get_chatty_reply(cleaned_text)
                print("Chatty:", reply)

                if is_puzzled_reply(reply):
                    set_state("puzzled")
                    time.sleep(1)
                else:
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

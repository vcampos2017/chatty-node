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

            set_state("thinking")
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

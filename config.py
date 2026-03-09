import os

HOME = os.path.expanduser("~")

SAMPLERATE = 48000
RECORD_SECONDS = 5
AUDIO_DEVICE_INDEX = 1

STATE_FILE = os.path.join(HOME, "chatty_state_pipe")
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

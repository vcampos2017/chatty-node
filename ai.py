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

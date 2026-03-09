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

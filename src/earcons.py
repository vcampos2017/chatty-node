"""
Short sound cues so you don't have to watch the screen:
    listening()  rising two-note chime: "your turn, I'm listening"
    done()       falling two-note chime: "I stopped listening"
Generated once with numpy and played through the same speaker as the voice.
Set CHATTY_SOUNDS=0 to turn them off.
"""
import os
import subprocess
import tempfile
import wave

import numpy as np

ENABLED = os.getenv("CHATTY_SOUNDS", "1") != "0"
DEVICE = os.getenv("CHATTY_ALSA_OUT", "plughw:CARD=PowerConf,DEV=0")
VOLUME = float(os.getenv("CHATTY_SOUND_VOLUME", "0.25"))
RATE = 22050
_files = {}


def _tone_wav(notes, path):
    parts = []
    for freq, dur in notes:
        t = np.arange(int(RATE * dur)) / RATE
        env = np.minimum(1, t / 0.01) * np.exp(-t * 9)  # soft attack, quick fade: a gentle "ding"
        tone = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)
        parts.append(tone * env)
    audio = np.concatenate(parts) * VOLUME * 32767 / 1.3
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio.astype(np.int16).tobytes())


def _play(name, notes):
    if not ENABLED:
        return
    try:
        if name not in _files:
            path = os.path.join(tempfile.gettempdir(), f"chatty_{name}.wav")
            _tone_wav(notes, path)
            _files[name] = path
        subprocess.run(["aplay", "-q", "-D", DEVICE, _files[name]],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    except Exception as e:
        print(f"(sound cue failed: {e!r})", flush=True)


def listening():
    _play("listen", [(784, 0.09), (1175, 0.16)])   # G5 -> D6, rising


def done():
    _play("done", [(988, 0.09), (659, 0.16)])      # B5 -> E5, falling

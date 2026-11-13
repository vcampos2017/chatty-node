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


def lullaby():
    """After the bedtime wind-down: a soft, slow three-note goodnight (G E C)."""
    _play("lullaby", [(784, 0.22), (659, 0.22), (523, 0.45)])


def timer():
    """A timer or alarm going off: a bright little music-box run, twice
    (plays even with CHATTY_SOUNDS=0, since you asked for it)."""
    global ENABLED
    was, ENABLED = ENABLED, True
    try:
        notes = [(1047, 0.14), (1319, 0.14), (1568, 0.14), (2093, 0.3)]
        _play("timer", notes + [(0.0001, 0.15)] + notes)
    finally:
        ENABLED = was


def alert():
    """Attention tone before a weather / AMBER alert (plays even with CHATTY_SOUNDS=0)."""
    global ENABLED
    was, ENABLED = ENABLED, True
    try:
        _play("alert", [(880, 0.22), (660, 0.22), (880, 0.22), (660, 0.3)])
    finally:
        ENABLED = was


RED_VOLUME = float(os.getenv("CHATTY_RED_ALERT_VOLUME", "0.6"))


def _red_alert_wav(path):
    """Chatty's own Red Alert tone (an original pattern, made here): three quick
    bright beeps, then her two-note "listening" chime (G5 -> D6), three times over.
    Steady beeps with soft 8 ms edges, so it carries across the house without
    clicking."""
    def beep(freq, dur):
        t = np.arange(int(RATE * dur)) / RATE
        edge = np.minimum(1, np.minimum(t, dur - t) / 0.008)
        tone = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(6 * np.pi * freq * t) / 3
        return tone * edge

    def rest(dur):
        return np.zeros(int(RATE * dur))

    one = [beep(1175, 0.11), rest(0.06), beep(1175, 0.11), rest(0.06), beep(1175, 0.11),
           rest(0.12), beep(784, 0.16), beep(1175, 0.30), rest(0.35)]
    audio = np.concatenate(one * 3)
    audio = audio / max(1e-9, float(np.max(np.abs(audio)))) * RED_VOLUME * 32767 * 0.95
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio.astype(np.int16).tobytes())


def red_alert():
    """Before a Red Alert line (tornado warning, red_alert.py). Always plays, even
    with CHATTY_SOUNDS=0: this is the one sound that has to get through."""
    try:
        path = _files.get("red_alert")
        if path is None:
            path = os.path.join(tempfile.gettempdir(), "chatty_red_alert.wav")
            _red_alert_wav(path)
            _files["red_alert"] = path
        subprocess.run(["aplay", "-q", "-D", DEVICE, path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
    except Exception as e:
        print(f"(red alert tone failed: {e!r})", flush=True)

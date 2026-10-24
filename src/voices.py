"""
Recognizing familiar voices (OFF by default).

Turn on with CHATTY_VOICE_ID=1 in /etc/chatty/secrets.env. It also needs Vosk's
small speaker model (about 13 MB):

    cd ~/vosk-model
    wget https://alphacephei.com/vosk/models/vosk-model-spk-0.4.zip
    unzip vosk-model-spk-0.4.zip

How it works: for each phrase, Vosk produces a "voiceprint" (a list of 128
numbers describing how the voice sounds). Enrolling averages a few of them under
a name; recognizing compares new voiceprints with the saved ones.

Voiceprints are personal data: they are only created when someone asks
("Hey Chatty, learn my voice") and agrees, are stored only on this Pi
(~/.local/share/chatty/voices.json, owner-only), and "forget my voice" deletes them.
This is for friendly things like greetings, NOT for security: a recording or a
similar voice can fool it.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

ENABLED = os.getenv("CHATTY_VOICE_ID", "0") == "1"
SPK_MODEL_PATH = os.getenv("CHATTY_SPK_MODEL", "/home/pi/vosk-model/vosk-model-spk-0.4")
VOICES_FILE = Path(os.getenv(
    "CHATTY_VOICES_FILE", os.path.expanduser("~/.local/share/chatty/voices.json")))
# How similar (0..1) a voice must be to count as a match. Logged with every
# guess so it can be tuned; raise it if Chatty confuses people.
MATCH = float(os.getenv("CHATTY_VOICE_MATCH", "0.55"))
# Also optional and OFF by default: ignore "Hey Chatty" from voices it doesn't know.
ONLY_KNOWN = os.getenv("CHATTY_ONLY_KNOWN_VOICES", "0") == "1"
MIN_FRAMES_ID = 30       # ~0.3 s of speech before trying a guess (short phrases like "who am I")
MIN_FRAMES_ENROLL = 100  # ~1 s per enrollment sample


# ----------------------------
# math
# ----------------------------

def _unit(v: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity, 0..1-ish (1 = identical)."""
    return sum(x * y for x, y in zip(_unit(a), _unit(b)))


def average(vectors: List[List[float]]) -> List[float]:
    units = [_unit(v) for v in vectors]
    return _unit([sum(col) / len(units) for col in zip(*units)])


# ----------------------------
# storage
# ----------------------------

def load() -> dict:
    try:
        return json.loads(VOICES_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    VOICES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = VOICES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.chmod(tmp, 0o600)
    tmp.replace(VOICES_FILE)


def enroll(name: str, vectors: List[List[float]]) -> int:
    """Save (or add to) a voiceprint. Re-learning someone ADDS samples, so their
    voiceprint gets better with variety (different times, distances, moods).
    Returns the total number of samples."""
    data = load()
    new = average(vectors)
    old = data.get(name)
    if old:
        n_old, n_new = old.get("samples", 3), len(vectors)
        merged = _unit([(a * n_old + b * n_new) / (n_old + n_new)
                        for a, b in zip(_unit(old["vector"]), new)])
        total = n_old + n_new
        data[name] = {"vector": merged, "samples": total, "enrolled": old.get("enrolled"),
                      "updated": time.strftime("%Y-%m-%d %H:%M")}
    else:
        total = len(vectors)
        data[name] = {"vector": new, "samples": total,
                      "enrolled": time.strftime("%Y-%m-%d %H:%M")}
    _save(data)
    return total


def forget(name: str) -> bool:
    data = load()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True


def names() -> List[str]:
    return sorted(load())


def closest(vector: Optional[List[float]]) -> Tuple[Optional[str], float]:
    """The most similar known voice and its score, match or not (for 'who am I' hints)."""
    best_name, best = None, -1.0
    if vector:
        for name, info in load().items():
            score = similarity(vector, info["vector"])
            if score > best:
                best_name, best = name, score
    return best_name, max(best, 0.0)


def identify(vector: Optional[List[float]], frames: int = 0,
             min_frames: int = MIN_FRAMES_ID) -> Tuple[Optional[str], float]:
    """(name, score) of the closest known voice if it's a match, else (None, best score)."""
    if not vector or frames < min_frames:
        return None, 0.0
    best_name, best = None, -1.0
    for name, info in load().items():
        score = similarity(vector, info["vector"])
        if score > best:
            best_name, best = name, score
    if best_name and best >= MATCH:
        return best_name, best
    return None, max(best, 0.0)


# ----------------------------
# names spoken aloud
# ----------------------------

_NAME_PREFIX = re.compile(r"^(hey chatty |chatty )?(my name is|my names|call me|i am|im|its|it is|this is|i go by)\s+")
_NOT_NAMES = {"yes", "no", "okay", "ok", "um", "uh", "the", "a", "hey", "chatty", "what", "nothing"}


def parse_name(text: str) -> Optional[str]:
    """'my name is vincent' -> 'Vincent'."""
    t = _NAME_PREFIX.sub("", (text or "").strip().lower())
    words = [w for w in re.sub(r"[^a-z\s]", "", t).split() if w not in _NOT_NAMES]
    if not words or len(words) > 3:
        return None
    return " ".join(w.capitalize() for w in words[:2])

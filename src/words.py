"""
Chatty's words: the small, pure text helpers the voice node uses to understand what
she heard (her name and its soundalikes, filler words, yes / no / thanks) and to
tidy what she says. No microphone, no models, nothing on import, so tests and
other modules can use them directly (the voice node opens the mic when imported).
"""
from __future__ import annotations

import random
import re


# Words the recognizer sometimes hears instead of "Chatty". They only count as her


# name where a name goes: at the start (after "hey"/"okay") or as the last word.
WAKE_VARIANTS = {"chatty", "caddy", "kitty", "charity", "jackie", "jockey", "heidi",
                 "daddy", "catty", "chattie", "chetty", "cheddy", "shatty", "patty",
                 "paddy", "getty", "chaddy", "chatter", "chad"}

FILLER_WORDS = {"hey", "hi", "hello", "okay", "ok", "oh", "um", "uh"}


# "thank you daddy", "goodnight caddy": a name at the end only after one of these
NAME_AFTER = {"thanks", "you", "please", "night", "goodnight", "bye", "morning", "afternoon",
              "evening", "hi", "hello", "hey"}

YES_WORDS = {"yes", "yeah", "yep", "sure", "please", "do it", "go ahead", "okay", "ok"}

THANKS_PHRASES = {"thanks", "thank you", "thanks chatty", "thank you chatty", "cool thanks"}


def is_just_thanks(prompt: str) -> bool:
    """'Thanks, I did not know that about the Raspberry Pi': a thank-you, not a question.
    Answered right here instead of waiting on (or paying for) a model."""
    p = prompt.strip().lower()
    return (bool(re.match(r"^(ok(ay)? |oh )?(thanks|thank you)\b", p)) and len(p.split()) <= 14
            and not re.search(r"\b(can|could|would|will) you\b|\b(but|and) (what|how|why|when|where|who|"
                              r"can|could|is|are|tell|set|play|remind)\b|\?$", p))


# "No thank you", "nope", "I'm good": a polite no, answered at once (never a model, never the cloud)
JUST_NO = re.compile(r"^(oh |well |um |uh )?(no|nope|nah|no no|not really|not now|i'?m good|im good|"
                     r"i'?m okay|that'?s okay|thats okay|that'?s fine|thats fine|that'?s all right)"
                     r"( thank you| thanks| thank you though| thats okay| that'?s all| i'?m good)?( chatty)?$")


# a lone stray word heard while she waits for yes or no ("the", "uh"): keep waiting
CONFIRM_NOISE = {"the", "a", "an", "uh", "um", "huh", "hmm", "mm", "oh", "and", "i", "it", "of", "to", "in"}


def is_just_no(prompt: str) -> bool:
    return bool(JUST_NO.match(prompt.strip().lower()))


def pick(lines):
    return random.choice(lines)


def clean_for_speech(text: str) -> str:
    """Remove markdown-ish symbols that sound odd when spoken."""
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"[*_#`>]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    return " ".join(text.split())


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", (s or "").lower()).strip()


def fix_name(text: str) -> str:
    """Turn a misheard name ('daddy', 'caddy'...) back into 'chatty', but only where a
    name goes: after the leading 'hey'/'okay', or last after a polite word ('thanks daddy')."""
    words = (text or "").split()
    i = 0
    while i < len(words) and words[i] in FILLER_WORDS:
        i += 1
    if i < len(words) and words[i] in WAKE_VARIANTS:
        words[i] = "chatty"
    if len(words) > 1 and words[-1] in WAKE_VARIANTS and words[-2] in NAME_AFTER:
        words[-1] = "chatty"
    return " ".join(words)


def name_word(text: str):
    """The word heard where her name goes ('chatty', 'daddy'...), or None, for the log."""
    words = (text or "").split()
    i = 0
    while i < len(words) and words[i] in FILLER_WORDS:
        i += 1
    if i < len(words) and words[i] in WAKE_VARIANTS:
        return words[i]
    if len(words) > 1 and words[-1] in WAKE_VARIANTS and words[-2] in NAME_AFTER:
        return words[-1]
    return "chatty" if "chatty" in words else None


def strip_wake(text: str) -> str:
    """Remove her name (and soundalikes where a name goes) and leading filler."""
    words = [w for w in fix_name(text).split() if w != "chatty"]
    while words and words[0] in FILLER_WORDS:
        words.pop(0)
    return " ".join(words).strip()

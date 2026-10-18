"""
Chatty's memory: things people ask it to remember, stored only on the Pi.

Voice commands (after "Hey Chatty"):
    remember (that) <fact>      -> confirm, then save
    what do you remember        -> list a few recent notes
    forget (about) <something>  -> confirm, then delete the closest note
    forget everything           -> confirm, then delete all notes
Questions are matched against saved notes by shared keywords
("where is the spare key" finds "the spare key is under the blue pot").

Notes live in a small JSON file you can read or edit:
    ~/.local/share/chatty/memory.json   (override with CHATTY_MEMORY_FILE)
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

MEMORY_FILE = Path(os.getenv(
    "CHATTY_MEMORY_FILE", os.path.expanduser("~/.local/share/chatty/memory.json")))
MAX_NOTES = 300

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "am", "to", "of", "in",
    "on", "at", "for", "and", "or", "but", "it", "its", "this", "that", "these", "those",
    "i", "im", "me", "my", "mine", "we", "our", "you", "your", "yours", "he", "she",
    "they", "them", "his", "her", "their", "what", "whats", "where", "wheres", "when",
    "who", "whos", "which", "how", "do", "does", "did", "can", "could", "would", "will",
    "should", "please", "chatty", "hey", "tell", "know", "remember", "about", "with",
    "there", "here", "so", "just", "some", "any", "all", "have", "has", "had", "s",
}

QUESTION_START = re.compile(
    r"^(where|what|whats|when|who|whos|which|how|is|are|does|do|did|can|tell me|"
    r"remind me|wheres|any idea)\b")

# first person -> second person, for repeating notes back to the speaker
_SWAP = [
    (r"\bim\b", "you're"), (r"\bi am\b", "you are"), (r"\bive\b", "you've"),
    (r"\bi have\b", "you have"), (r"\bid\b", "you'd"), (r"\bill\b", "you'll"),
    (r"\bi\b", "you"), (r"\bmy\b", "your"), (r"\bmine\b", "yours"),
    (r"\bme\b", "you"), (r"\bmyself\b", "yourself"),
    (r"\bour\b", "your"), (r"\bours\b", "yours"), (r"\bwe\b", "you"), (r"\bus\b", "you"),
]


def to_you(text: str) -> str:
    """'my keys are in the drawer' -> 'your keys are in the drawer'."""
    out = " " + text + " "
    for pat, rep in _SWAP:
        out = re.sub(pat, rep, out)
    return " ".join(out.split())


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def keywords(text: str) -> set:
    words = re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()
    return {_stem(w) for w in words if w not in STOPWORDS and len(w) > 1}


# ----------------------------
# storage
# ----------------------------

def load() -> List[dict]:
    try:
        return json.loads(MEMORY_FILE.read_text())
    except (OSError, ValueError):
        return []


def _save(notes: List[dict]) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MEMORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(notes[-MAX_NOTES:], indent=2))
    tmp.replace(MEMORY_FILE)  # atomic: a power cut can't leave a half-written file


def add(text: str) -> None:
    notes = load()
    notes.append({"text": text, "saved": time.strftime("%Y-%m-%d %H:%M")})
    _save(notes)


def best_match(query: str, notes: Optional[List[dict]] = None):
    """(score, note) for the note sharing the most keywords with query, or (0, None)."""
    q = keywords(query)
    if not q:
        return 0.0, None
    best = (0.0, None)
    for note in notes if notes is not None else load():
        n = keywords(note["text"])
        shared = len(q & n)
        if not shared:
            continue
        score = shared / len(q)
        if score > best[0]:
            best = (score, note)
    return best


def remove(note: dict) -> None:
    _save([n for n in load() if n != note])


def clear() -> None:
    _save([])


# ----------------------------
# voice commands
# ----------------------------

@dataclass
class Result:
    reply: str                                   # what Chatty says now
    confirm: Optional[Callable[[], str]] = None  # if set, ask yes/no; run on yes, speak its result


REMEMBER = re.compile(r"^(please )?(remember|remind yourself|make a note|note|save)( that)? (?P<fact>.+)$")
FORGET_ALL = re.compile(r"^(forget everything|forget all|erase your memory|clear your memory|wipe your memory)$")
FORGET = re.compile(r"^(please )?forget( about| that| the thing about)? (?P<what>.+)$")
LIST = re.compile(r"^(what do you remember|what do you know about me|what have you remembered|"
                  r"what do you know|list your notes|what are your notes)$")


def handle(prompt: str) -> Optional[Result]:
    """Memory commands and recall. None if this isn't a memory thing."""
    p = prompt.strip().lower()

    m = REMEMBER.match(p)
    if m:
        fact = m.group("fact").strip()
        if len(fact.split()) < 2:
            return Result("Sorry, what should I remember?")
        spoken = to_you(fact)

        def save() -> str:
            add(fact)
            return "Got it, I'll remember that."
        joiner = "" if spoken.startswith("to ") else "that "
        return Result(f"You want me to remember {joiner}{spoken}?", confirm=save)

    if FORGET_ALL.match(p):
        count = len(load())
        if not count:
            return Result("My memory is already empty.")

        def wipe() -> str:
            clear()
            return "Okay. I've forgotten everything."
        return Result(f"Forget all {count} things I remember? This can't be undone.", confirm=wipe)

    m = FORGET.match(p)
    if m and m.group("what").strip() not in ("it", "that", "about it", "it chatty"):
        score, note = best_match(m.group("what"))
        if not note:
            return Result("Hmm, I don't remember anything about that.")

        def drop() -> str:
            remove(note)
            return "Done. I've forgotten it."
        return Result(f"Forget this: {to_you(note['text'])}?", confirm=drop)

    if LIST.match(p):
        notes = load()
        if not notes:
            return Result("Nothing yet. Say 'remember that' and tell me something.")
        recent = [to_you(n["text"]) for n in notes[-3:]]
        more = f" I know {len(notes)} things in all." if len(notes) > 3 else ""
        return Result("Here's what I remember: " + ". ".join(recent) + "." + more)

    return None


def recall(prompt: str) -> Optional[str]:
    """Answer a question from saved notes, or None."""
    p = prompt.strip().lower()
    if not QUESTION_START.match(p) or len(p.split()) > 14:
        return None
    q = keywords(p)
    score, note = best_match(p)
    # need a solid match: most of the question's keywords, and at least one real word
    if not note or score < (0.6 if len(q) > 2 else 0.99):
        return None
    return f"You told me {to_you(note['text'])}."

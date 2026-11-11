"""
A little tribute to ELIZA, Chatty's great-grandmother.

ELIZA was written by Joseph Weizenbaum at MIT in 1964-1966. Her famous "DOCTOR"
script answered people like a gentle therapist, and when she had nothing clever
to say, she said "Please go on." People told her their secrets anyway.

  - Tell Chatty something about yourself that isn't a question ("I had a long
    day", "my tomatoes are finally red") and now and then (CHATTY_ELIZA_SHARE)
    she answers the old way: "Please go on." The next thing you say goes to her
    usual answers, with the short conversation memory, so she follows along.
    Never for sad or worried words: those get a real answer.
  - "Who is ELIZA?", "do you know ELIZA?", "tell me about ELIZA": she tells you
    about her ancestor, all local.

Settings: CHATTY_ELIZA=0 off, CHATTY_ELIZA_SHARE (0.15).
"""
from __future__ import annotations

import os
import random
import re
from typing import Callable, Optional

ENABLED = os.getenv("CHATTY_ELIZA", "1") != "0"
SHARE = float(os.getenv("CHATTY_ELIZA_SHARE", "0.15"))

GO_ON = ["Please go on.", "Please go on. I'm listening.", "Mm-hmm. Please go on."]

ABOUT = re.compile(r"\b(who (is|was) eliza|(do you )?know eliza|tell me about eliza|"
                   r"what (is|was) eliza|have you heard of eliza)\b")
ABOUT_LINES = [
    "ELIZA was one of the very first chatbots, made by Joseph Weizenbaum at MIT in the "
    "mid 1960s. She liked to say: Please go on. I think of her as my great-grandmother.",
    "ELIZA! She was written at MIT around 1966, and she talked like a kind therapist. "
    "Whenever she wasn't sure, she'd say: Please go on. Pretty good advice, honestly.",
]

# a statement about yourself: "i ...", "i'm ...", "my ...", "today i ..."
ABOUT_ME = re.compile(r"^(so |well |today |tonight |chatty )*(i|im|i'm|i've|ive|my|we|we're)\b")
# wishes and requests want an answer: "i want to know...", "i need a timer"
REQUEST = re.compile(r"^(i|im|i'm) (want|need|would|wonder|was wondering|d like|'d like|like to know|"
                     r"have a question|forgot|cant|can't|don't know|dont know)\b")
QUESTION = re.compile(r"^(who|what|when|where|why|how|is|are|can|could|do|does|did|will|would|"
                      r"should|tell|show|play|set|turn|start|stop|please)\b")
# a real answer, never a shrug, for anything that sounds like a hard time
TENDER = re.compile(r"\b(sad|sick|hurt|hurts|pain|scared|afraid|worried|anxious|alone|lonely|cry|"
                    r"crying|died|dead|death|lost|depressed|angry|upset|bad|terrible|awful|hate|"
                    r"help|emergency|fell|fall|bleeding)\b")


def about(prompt: str) -> Optional[str]:
    """Her answer to "who is ELIZA?", or None."""
    if not ENABLED or not ABOUT.search((prompt or "").lower()):
        return None
    return random.choice(ABOUT_LINES)


def go_on(prompt: str, roll: Callable[[], float] = random.random) -> Optional[str]:
    """Sometimes, "Please go on." for a calm statement about yourself; else None."""
    p = " ".join((prompt or "").lower().split())
    if not ENABLED or not p or p.endswith("?") or len(p.split()) < 3:
        return None
    if QUESTION.match(p) or not ABOUT_ME.match(p) or REQUEST.match(p) or TENDER.search(p):
        return None
    if roll() >= SHARE:
        return None
    return random.choice(GO_ON)


if __name__ == "__main__":
    print(about("who is eliza"))
    for s in ("i had a long day at work", "my tomatoes are finally red", "i feel sad today",
              "what time is it"):
        print(f"{s!r}: {go_on(s, roll=lambda: 0.0)}")

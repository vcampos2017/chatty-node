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

# "tell me more about ELIZA" (also what "another one" / "go on" become after her answer)
# "read me a line of ELIZA's code": two real lines, quoted exactly. Her original code and
# DOCTOR script were found in Weizenbaum's papers at MIT and released by his estate in
# 2021 under CC0 (public domain), so quoting them is fine; we say where they're from.
CODE = re.compile(r"\b(line|lines|bit|piece|some|read|show|say|quote)\b.*\beliza'?s?\b.*\b(code|script|program)\b|"
                  r"\b(code|script) (from|of) eliza\b")
CODE_LINES = [
    "Here's the very first thing ELIZA ever said to people, straight from her DOCTOR "
    "script, in capital letters like an old teletype: HOW DO YOU DO. PLEASE TELL ME YOUR "
    "PROBLEM. Then she'd wait, very patiently.",
    "Here's a tiny rule from her DOCTOR script: open parenthesis, HOW, open parenthesis, "
    "equals WHAT, close, close. It means: when someone asks how, treat it just like what. "
    "One little line, and she seemed to understand you.",
]
_code_next = 0


def code_line(prompt: str) -> Optional[str]:
    """A real line from ELIZA's DOCTOR script, explained, or None."""
    global _code_next
    if not ENABLED or not CODE.search((prompt or "").lower()):
        return None
    line = CODE_LINES[_code_next % len(CODE_LINES)]
    _code_next += 1
    return line


MORE_ABOUT = re.compile(r"\bmore about eliza\b")
MORE_LINES = [
    "Joseph Weizenbaum named her after Eliza Doolittle from Pygmalion, the flower seller who "
    "learns to speak like a lady. ELIZA learned to talk, too, sort of.",
    "Her most famous script was called DOCTOR. She turned your words back into questions: "
    "you'd say I'm sad, and she'd ask why you're sad.",
    "Weizenbaum's own secretary asked him to leave the room so she could talk to ELIZA in "
    "private. He was surprised how much people trusted a few hundred lines of code.",
    "ELIZA had no memory at all, so she couldn't follow a conversation. I keep a few lines, "
    "so I can. She'd be proud, I think.",
    "In 2021 people found her original code in Weizenbaum's papers at MIT, and a few "
    "years later they got it running again, about sixty years after she was born.",
    "That's all I know about ELIZA for now. Please go on... with something new!",
]
_more_next = 0


def more_about(prompt: str) -> Optional[str]:
    """The next ELIZA fact for "tell me more about ELIZA", or None."""
    global _more_next
    if not ENABLED or not MORE_ABOUT.search((prompt or "").lower()):
        return None
    line = MORE_LINES[min(_more_next, len(MORE_LINES) - 1)]
    _more_next = 0 if _more_next >= len(MORE_LINES) - 1 else _more_next + 1
    return line


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
    """Her answer to "who is ELIZA?" (or the next fact for "tell me more"), or None."""
    more = code_line(prompt) or more_about(prompt)
    if more:
        return more
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

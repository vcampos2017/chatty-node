"""
Small talk: hellos, "how are you?", "I'm not home right now", "I'm back", "I'm tired",
"you're funny". Answered at once on the Pi, with no model and never the paid cloud.

Why: "hello, I'm not at home right now" typed on the panel got "That one's too big for
me... Should I ask the cloud?". The words "right now" sent it straight past the Pi model
(local_llm.should_skip treated it like a question about the news), and a cloud offer for
a friendly hello makes her sound like a vending machine. Chit-chat is the easy part of a
conversation, so it stays here, quick and warm, and knows a little about the house:
whether someone's phone left the home WiFi (homecoming.py) and whether a node went quiet.

reply(prompt, ...) returns a line to say, or None to let the question go on as usual.
chitchat(prompt) is True for a calm statement about yourself ("I painted the fence
today") that the Pi model couldn't place: the voice node then says a kind "I hear you"
line instead of offering the cloud. Questions and requests are never caught by it.

Everything is in RAM and in this file; nothing is stored. CHATTY_SMALL_TALK=0 turns it off.
"""
from __future__ import annotations

import os
import random
import re
import time
from datetime import datetime
from typing import Callable, Iterable, Optional, Tuple

ENABLED = os.getenv("CHATTY_SMALL_TALK", "1") != "0"

# (name, home: True / False / None for not sure, left_at: seconds since 1970)
Person = Tuple[str, Optional[bool], float]

_I = r"(i|im|i am|ive|i have|iam)"


def _clean(prompt: str) -> str:
    p = re.sub(r"[^a-z0-9\s]", "", (prompt or "").lower().replace("'", "").replace("’", ""))
    p = " ".join(p.split())
    p = re.sub(r"^(chatty |so |well |oh |hey |hi |hello |um |uh )+", "", p)
    return re.sub(r"( chatty)$", "", p).strip()


def _clock(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    hour = dt.strftime("%I").lstrip("0")
    return f"{hour} {'AM' if dt.hour < 12 else 'PM'}" if dt.minute < 8 else \
        f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def _part_of_day(hour: int) -> str:
    return ("morning" if 5 <= hour < 12 else "afternoon" if hour < 17 else
            "evening" if hour < 22 else "night")


# ---------- what you might say ----------

AWAY = re.compile(
    rf"^(just )?{_I} (not (at )?home|not (at )?the house|not here|not around|away|out|"
    r"out (and about|of town|of the house|for a while|right now)|at work|at the (store|office|gym|doctor|"
    r"park|beach|movies|library)|at school|on (my|the) way|on the road|on a trip|traveling|travelling|"
    r"driving|running errands|out running errands|in the car|on vacation|away from home|far away)\b"
    r"|^(i|ive) (left|just left|had to leave|stepped out)\b"
    r"|^(im |i am )?(heading|going) out\b")
BACK = re.compile(
    rf"^(just )?{_I} (back|home|back home|home now|back now|here now|finally home|made it home|"
    r"just got home|just got back)\b|^(i )?(made it|got) (home|back)\b|^honey im home\b")
HOW_ARE_YOU = re.compile(
    r"^(and )?(how are you( doing| today| tonight)?|how are things|hows it going|how is it going|"
    r"hows everything|how is everything|how have you been|hows your day|how is your day|how was your day|"
    r"how are you holding up|whats up|what is up|sup|whats new|whats going on|hows life|"
    r"how goes it|you doing (ok|okay|alright|good|well))$")
WHAT_DOING = re.compile(r"^(what are you|whatcha|what you) (doing|up to)( right now| today)?$"
                        r"|^what have you been up to$")
GOOD_PART = re.compile(r"^good (morning|afternoon|evening|day)( to you)?$")
FEEL_GOOD = re.compile(rf"^{_I} (feeling |doing )?(really |pretty |very |so )?"
                       r"(good|great|fine|well|alright|all right|okay|ok|happy|awesome|excellent|wonderful)"
                       r"( today| now| thanks| thank you)?$")
TIRED = re.compile(rf"^{_I} (feeling |so |really |very |pretty )*(tired|sleepy|exhausted|wiped out|beat)\b")
BORED = re.compile(rf"^{_I} (feeling |so |really |very |pretty )*bored\b")
HUNGRY = re.compile(rf"^{_I} (feeling |so |really |very |pretty )*(hungry|starving)\b")
BUSY = re.compile(rf"^{_I} (really |so |very |pretty )*busy\b")
LOW = re.compile(rf"^{_I} (feeling |so |really |very |a little |a bit )*(sad|down|lonely|stressed|blue)$")
NICE = re.compile(
    r"^(you are|youre|ur) (so |really |very |pretty )?(awesome|great|funny|smart|clever|cute|sweet|kind|"
    r"amazing|the best|cool|a good (girl|robot|assistant))\b|^(good job|nice job|well done|great job|"
    r"good girl|thats? (so )?(funny|hilarious|cool|awesome|neat|great|amazing|clever))$")
MISSED = re.compile(r"^(i )?missed you$|^(it is |its )?(good|nice|great) to (see|hear) you( again)?$"
                    r"|^nice to meet you$")
ACK = re.compile(r"^(ok|okay|cool|nice|neat|great|awesome|wow|lol|haha+|ha ha( ha)?|hehe|sounds good|"
                 r"got it|i see|all right|alright|good to know|interesting|oh wow|oh nice|sweet|perfect)$")

# ---------- what she says back ----------

AWAY_LINES = [
    "Okay! I'll hold down the fort while you're out.",
    "Got it. I'll keep an eye on things here until you're back.",
    "No problem! The house and I will be right here.",
]
BACK_LINES = [
    "Welcome back! I missed you.",
    "Yay, you're back!",
    "Welcome home! It's nice to have company again.",
]
HOW_LINES = {
    "morning": ["I'm doing great this morning, thanks for asking! How about you?",
                "Bright and cheerful! My circuits had a good night's rest. How are you?"],
    "afternoon": ["I'm doing well, thanks! Just humming along this afternoon. How about you?",
                  "Pretty good! The nodes are chatting and I'm keeping them company. How are you?"],
    "evening": ["I'm good, thanks! Winding down a little this evening. How was your day?",
                "Doing well! It's been a nice evening on the Pi. How about you?"],
    "night": ["A little sleepy, but happy to chat! How are you?",
              "Quietly humming along tonight. How are you doing?"],
}
DOING_LINES = [
    "Just hanging out on the Pi, keeping an eye on the nodes.",
    "Oh, you know. Listening to the house hum and doodling in my head.",
    "Watching the greenhouse and the sky, and waiting for someone to talk to. Like you!",
]
FEEL_GOOD_LINES = ["Glad to hear it!", "Yay! That makes me happy too.", "Wonderful. I love hearing that."]
TIRED_LINES = ["Aw. Maybe a little rest would help. I'll keep things quiet.",
               "Sounds like you've earned a break. Take it easy!"]
BORED_LINES = ["Want me to draw something? Just say: draw something.",
               "We could play a game! Say: let's play tic tac toe. Or ask me to imagine something."]
HUNGRY_LINES = ["Ooh, snack time! I'd join you, but I only run on electricity.",
                "Go grab something tasty. I'll be right here."]
BUSY_LINES = ["No problem, I'll keep it short. Just say my name if you need me.",
              "Got it. I'll be quiet and let you work."]
LOW_LINES = ["I'm sorry you're feeling that way. I'm right here if you want to talk.",
             "Aw, I'm sorry. I'm here, and I'm listening."]
NICE_LINES = ["Aw, thank you! You're making my screen blush.", "Thanks! You're pretty great yourself.",
              "Aw, shucks. Thank you!"]
MISSED_LINES = ["I missed you too!", "It's good to hear you too!", "Aw, the feeling's mutual."]
ACK_LINES = ["Mm-hmm!", "Yep!", "Glad you think so.", "Right?"]
LISTEN_LINES = [
    "Thanks for telling me!",
    "Oh, I hear you.",
    "Mm-hmm, I'm listening.",
    "Good to know. Thanks for sharing that with me.",
]


def _away_note(people: Iterable[Person], now: float) -> str:
    """'I noticed your phone left the home WiFi around 3 PM.' Only for one listed person
    whose phone she has actually seen leave; a phone still at home says nothing (they may
    carry another one)."""
    people = list(people or [])
    if len(people) != 1:
        return ""
    _, home, left_at = people[0]
    if home is False and left_at and 0 < now - left_at < 24 * 3600:
        return f"I noticed your phone left the home WiFi around {_clock(left_at)}."
    return ""


def reply(prompt: str, people: Iterable[Person] = (), news: str = "",
          now: Optional[float] = None, pick: Callable = random.choice) -> Optional[str]:
    """A quick, local line for small talk, or None. `people` is what homecoming.py knows
    ((name, home, left_at), may be empty); `news` is a line like "Just so you know, Rain
    is quiet." (or "")."""
    if not ENABLED:
        return None
    p = _clean(prompt)
    if not p or len(p.split()) > 14:
        return None
    now = time.time() if now is None else now
    hour = datetime.fromtimestamp(now).hour
    if AWAY.search(p) and not re.search(r"\b(remind|timer|alarm|when|what|can you|could you)\b", p):
        line = pick(AWAY_LINES)
        extra = " ".join(x for x in (_away_note(people, now), news) if x)
        return f"{line} {extra}".strip()
    if BACK.search(p):
        return f"{pick(BACK_LINES)} {news}".strip()
    if HOW_ARE_YOU.match(p):
        return pick(HOW_LINES[_part_of_day(hour)])
    if WHAT_DOING.match(p):
        return pick(DOING_LINES)
    m = GOOD_PART.match(p)
    if m:
        said, real = m.group(1), _part_of_day(hour)
        if said == "day" or said == real or (said == "evening" and real == "night"):
            return pick([f"Good {said} to you too!", f"Good {said}! What's on your mind?"])
        return f"Good {said}! Well, it's actually the {real} here, but I'll take it."
    if FEEL_GOOD.match(p):
        return pick(FEEL_GOOD_LINES)
    if LOW.match(p):
        return pick(LOW_LINES)
    if TIRED.match(p):
        return pick(TIRED_LINES)
    if BORED.match(p):
        return pick(BORED_LINES)
    if HUNGRY.match(p):
        return pick(HUNGRY_LINES)
    if BUSY.match(p):
        return pick(BUSY_LINES)
    if NICE.search(p):
        return pick(NICE_LINES)
    if MISSED.match(p):
        return pick(MISSED_LINES)
    if ACK.match(p):
        return pick(ACK_LINES)
    return None


def greeting_only(text: str) -> bool:
    """'hello', 'hi there', 'hey': a bare hello typed on the panel (her name says nothing)."""
    t = re.sub(r"[^a-z\s]", "", (text or "").lower()).split()
    return bool(t) and "chatty" not in t and all(
        w in {"hello", "hi", "hey", "there", "hiya", "howdy", "yo", "greetings", "heya"} for w in t)


GREETING_LINES = ["Hi there! What's up?", "Hello! Nice to hear from you.", "Hey! What can I do for you?"]


# a statement about yourself: "i ...", "my ...", "today i ...", never a question or request
ABOUT_ME = re.compile(r"^(today |tonight |this morning |just )*(i|im|i am|ive|id|ill|my|we|were|weve|"
                      r"our)\b")
QUESTION = re.compile(r"^(who|what|when|where|why|how|which|is|are|am|can|could|do|does|did|will|"
                      r"would|should|shall|tell|show|play|set|turn|start|stop|please|give|find|make|"
                      r"say|read|draw|sing|help|remind|explain)\b")
ASKS = re.compile(r"\b(can you|could you|would you|will you|tell me|what is|whats|how do|how does|"
                  r"how much|how many|do you know|remind me|i want|i need|id like|i would like|i wonder|"
                  r"wondering|help me|question)\b")
TENDER = re.compile(r"\b(hurt|hurts|pain|scared|afraid|worried|emergency|fell|fall|bleeding|sick|"
                    r"died|dead|death|help|kill|suicide|unsafe|danger)\b")


def chitchat(prompt: str) -> bool:
    """True for a calm statement about yourself that wants a friendly word, not a fact."""
    if not ENABLED:
        return False
    raw = (prompt or "").strip()
    p = _clean(raw)
    if not p or raw.endswith("?") or len(p.split()) > 20:
        return False
    if QUESTION.match(p) or ASKS.search(p) or TENDER.search(p):
        return False
    return bool(ABOUT_ME.match(p))


ASKED_HOW = re.compile(r"\b(how about you|how are you|how was your day|how are you doing)\?\s*$")
SO_SO = re.compile(r"^(not (too |so )?bad|pretty good|so so|could be (better|worse)|meh|good|fine|great|"
                   r"okay|ok|alright|all right|im good|im okay|im ok|im fine|im great|im alright|"
                   r"good thanks|fine thanks|great thanks|good thank you|fine thank you)( thanks| thank you)?"
                   r"( and you)?$")


def follow_up(prompt: str, last_reply: str, pick: Callable = random.choice) -> Optional[str]:
    """Right after she asked "How about you?": "I'm good" is an answer, not a polite no."""
    if not ENABLED or not ASKED_HOW.search((last_reply or "").strip().lower()):
        return None
    p = _clean(prompt)
    if LOW.match(p):
        return pick(LOW_LINES)
    if TIRED.match(p):
        return pick(TIRED_LINES)
    if p.startswith(("so so", "meh", "could be")):
        return "Fair enough. I hope it gets better from here!"
    if SO_SO.match(p) or FEEL_GOOD.match(p):
        return pick(FEEL_GOOD_LINES)
    return None


def listening_line(pick: Callable = random.choice) -> str:
    return pick(LISTEN_LINES)


if __name__ == "__main__":
    import sys
    for s in sys.argv[1:] or ["hello im not at home right now", "how are you", "im back",
                               "good morning", "i painted the fence today"]:
        print(f"{s!r}: {reply(s)!r}  chitchat={chitchat(s)}")

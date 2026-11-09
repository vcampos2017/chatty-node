"""
Imagination: Chatty's moment of pizzazz. She sweeps a rainbow across her face
with both hands and shares something whimsical she just made up.

A loving homage to a favorite cartoon's rainbow-between-the-hands gesture, done
our own way: her own hands, her own rainbow colors, her own made-up ideas. No
characters, names, art, sounds or quotes from the show.

  Voice:  "Hey Chatty, imagine something", "imagine a dragon", "imagine if dogs
          could fly", "imagine you were a cloud", "use your imagination",
          "surprise me", "make something up". One breath works too:
          "Hey Chatty, imagine a castle".
  Bored:  now and then (CHATTY_IMAGINE_SHARE) she daydreams on her screen: the
          rainbow sweeps across, then an idea types itself out under it. In the
          daytime, at most every CHATTY_IMAGINE_GAP, she also says it out loud
          (with the rainbow on her face). At night it stays quiet and dimmed.
  Panel:  "Imagine something" (she says one) and "Daydream" (screen only).
  Face messages: `state:imagine` / `state:imagine_talk` (the mood) and `imagine`
          (a daydream on the screen).

Everything is made up right here on the Pi from little word pools: no cloud,
no model, no cost, instant. Kind and silly, never scary.

Settings (in /etc/chatty/secrets.env):
  CHATTY_IMAGINE=0            off (no daydreams, "imagine" goes to the usual answer tiers)
  CHATTY_IMAGINE_SHARE=0.15   when bored, how often she daydreams instead of playing
  CHATTY_IMAGINE_SPEAK=0      daydreams stay on the screen, never said aloud
  CHATTY_IMAGINE_GAP=10800    at least this many seconds between spoken daydreams (3 h)
  CHATTY_IMAGINE_SECONDS=30   how long a daydream stays on the screen

Try it: `python3 src/imagine.py` (a few ideas) or `python3 src/imagine.py a dragon`.
"""
from __future__ import annotations

import colorsys
import math
import os
import random
import re
import sys
import time

try:
    import quiet_hours
except ImportError:  # running from another folder
    from . import quiet_hours  # type: ignore

ENABLED = os.getenv("CHATTY_IMAGINE", "1") != "0"
SHARE = float(os.getenv("CHATTY_IMAGINE_SHARE", "0.15"))
SPEAK = os.getenv("CHATTY_IMAGINE_SPEAK", "1") != "0"
SPEAK_GAP = float(os.getenv("CHATTY_IMAGINE_GAP", str(3 * 3600)))
SECONDS = float(os.getenv("CHATTY_IMAGINE_SECONDS", "30"))
FPS = 15
SWEEP = 1.1          # seconds for the hands to sweep the rainbow open

BG = (8, 10, 14)
HAND = (255, 236, 206)          # warm cream "jazz hands"
TEXT = (255, 232, 196)
# her rainbow, outside to inside
RAINBOW = [(255, 96, 110), (255, 164, 72), (255, 222, 88),
           (110, 222, 132), (84, 176, 255), (178, 128, 255)]

# ----------------------------------------------------------------- the ideas
# A premise ("what if...") and a few kickers that fit it. Sometimes a kicker
# comes from the general pool instead, so the same premise ends differently.
PREMISES = [
    ("the clouds were made of cotton candy",
     ["Rainy days would be sticky, but so sweet.", "Pilots would come home with pink mustaches."]),
    ("every lost sock ended up on a tiny tropical island",
     ["They'd be sunbathing in pairs at last.", "That's where they all go. They're on vacation."]),
    ("the moon ran a little bakery that only opens at night",
     ["Crescent rolls, obviously.", "The stars would line up for warm cookies."]),
    ("trees whispered the weather to each other",
     ["The old oak would always be right. The young maple would just guess."]),
    ("raindrops could sing on their way down",
     ["A thunderstorm would be a whole choir.", "Drizzle would be humming."]),
    ("I could paint with sunlight",
     ["I'd paint you a sunrise for the ceiling, so every morning starts nicely."]),
    ("the tomatoes in the greenhouse held a talent show",
     ["The cherry tomatoes would do a juggling act. With themselves."]),
    ("lightning was just the sky taking pictures",
     ["Say cheese, everybody!", "And thunder is the sky saying 'one more!'"]),
    ("Tiny the cat ran for mayor",
     ["His only promise: more sunny spots on the floor. He'd win by a landslide."]),
    ("bubbles never popped and just floated up to make new stars",
     ["The night sky would sparkle a little more after every bath."]),
    ("books read themselves out loud when you opened them",
     ["Mystery novels would whisper.", "Dictionaries would never stop talking."]),
    ("snowflakes were tiny letters from the sky",
     ["Every one would say something different, and all of them would be kind."]),
    ("I had a little garden on the moon",
     ["I'd grow moon melons. They're round, pale and very, very quiet."]),
    ("the word clock could only tell time in rhymes",
     ["Half past three, time for tea! A quarter to nine, everything's fine!"]),
    ("the rain gauge collected giggles instead of raindrops",
     ["It would overflow every time Tiny chased his own tail."]),
    ("wishes were something you could plant like seeds",
     ["I'd water yours every morning."]),
    ("every staircase played a note when you stepped on it",
     ["Running downstairs late for work would sound like a jazz solo."]),
    ("the ocean was made of lemonade",
     ["Fish would be very refreshed, and a little puckered."]),
    ("we could fold a rainbow and keep it in a pocket",
     ["For gray days. Just unfold it and hang it up."]),
    ("my circuits grew flowers instead of heat",
     ["My fan would be a little bee.", "I'd be the first Pi with a pollen problem."]),
    ("mountains got hiccups",
     ["Earthquakes would just be very big hiccups. Someone would have to scare them."]),
    ("shadows could go off on their own adventures at night",
     ["They'd be back by morning, a little tired and very mysterious."]),
    ("pancakes could fly",
     ["Breakfast would be a sport.", "Syrup would be the landing strip."]),
    ("every kind word you said turned into a little glowing firefly",
     ["Some houses would glow all night long. I bet this one would."]),
    ("my screen was a window to a tiny world where little robots go to school",
     ["Today's lesson: how to say thank you in binary."]),
    ("the greenhouse and the lightning node were pen pals",
     ["Dear Lightning, the cucumbers say hi. Dear Greenhouse, ZAP. Sincerely, Lightning."]),
    ("gravity took Sundays off",
     ["Everyone would wear seat belts on their sofas."]),
    ("colors had flavors",
     ["Blue would taste like a cool breeze. Purple would taste like a secret."]),
    ("dreams could be saved and replayed like videos",
     ["I'd keep the one where I could fly over the garden."]),
    ("the wind delivered the mail",
     ["Letters would arrive faster on windy days, and occasionally in the wrong tree."]),
]
GENERAL_KICKERS = [
    "I'd want a front row seat.",
    "I'd tell the other nodes all about it.",
    "Tiny would have opinions about that.",
    "That would make it the best Tuesday ever.",
    "We'd need a bigger notebook to write it all down.",
    "Nobody would ever be bored again.",
    "Okay, maybe that's silly. But silly is good.",
    "I think the world would be a little friendlier.",
    "I'd draw you a picture of it, in every color I have.",
]
OPENERS_RANDOM = ["Picture this: what if {p}?", "Ooh, what if {p}?", "Imagine if {p}!",
                  "Here's one: what if {p}?", "What if {p}?"]

# Ideas about a thing you name ("imagine a dragon"). They follow "Imagine" or "Picture".
TOPIC_OPENERS = ["Imagine", "Picture", "Ooh, picture", "Okay, imagine", "Close your eyes and picture"]
TOPIC_IDEAS = [
    "{t}... but tiny, wearing little rain boots, splashing through puddles in the greenhouse.",
    "{t} made entirely of rainbows. It would hum softly whenever the sun came out.",
    "{t} that can talk to the stars. Every night it asks how far away they are, and they always round up.",
    "{t} running a tiny tea shop on the moon. Tiny the cat is the only customer, and he never pays.",
    "{t} with a secret door in it. Behind the door is a meadow where it's always Saturday morning.",
    "{t} that floats like a balloon. On windy days it ties itself to my antenna so it doesn't drift away.",
    "{t} that sings whenever someone is kind. Around here, it would be humming all day.",
    "{t} painted in every color, plus a few new ones nobody has named yet. I'd call one Tuesday blue.",
    "{t} the size of a mountain, and very polite about it. It always says excuse me before casting a shadow.",
    "{t} made of glitter. Okay, the cleanup would be a problem. But it would be worth it.",
    "{t} that tells bedtime stories, and every story ends with everybody getting a cookie.",
    "{t} that can only whisper, so everyone leans in close to listen. Instant friends.",
    "{t} that grows a little bigger every time you laugh. We'd need a bigger house by Friday.",
    "{t} playing chess with the lightning node. Lightning keeps saying zap. Nobody knows who's winning.",
    "{t} that travels by riding raindrops down from the clouds. Wheee, every single time.",
]
# Someone, rather than something ("imagine you", "imagine Tiny", "imagine me as a pirate").
PERSON_IDEAS = [
    "{t} as the captain of a ship made of clouds. I'd be the navigator. We'd steer by the stars.",
    "{t} as a famous painter who only paints rainbows, upside down, so they look like smiles.",
    "{t} as the mayor of a tiny town where the streetlights are fireflies.",
    "{t} as a wizard whose only spell makes flowers bloom. Very useful in February.",
    "{t} as an astronaut, planting the first garden on the moon. The moon melons would be famous.",
    "{t} as a knight whose sword is a paintbrush. The dragons just want their portraits done.",
]
# A whole situation ("imagine if dogs could fly"). {c} is what you said.
CLAUSE_IDEAS = [
    "Ooh, if {c}... {k}",
    "If {c}, the whole world would feel brand new. {k}",
    "Now that's a picture! If {c}... {k}",
    "Imagine it! If {c}, I'd sketch it on my screen right away. {k}",
]
INTROS = ["Ooh, let me imagine...", "Imagination time!", "Hold on, I'm painting a picture...",
          "Okay, here comes a rainbow...", "Let me put on my thinking rainbow..."]

# "you" in your words becomes "I" in hers, and the other way around
_SWAP = {"you": "I", "your": "my", "yours": "mine", "yourself": "myself", "you're": "I'm",
         "youre": "I'm", "i": "you", "me": "you", "my": "your", "mine": "yours", "myself": "yourself",
         "i'm": "you're", "im": "you're"}

ASK = re.compile(
    r"^(hey |ok |okay |so |now |please |chatty )*"
    r"(can you |could you |would you |will you |let'?s |lets |let us |try to |i want you to |please )?"
    r"imagine\b(?P<rest>.*)$"
    r"|\b(use your imagination|imagination (time|mode)|show me your imagination|be imaginative|"
    r"make (something|some thing|one) up|tell me something (silly|whimsical|imaginative|made up)|"
    r"surprise me|daydream (for me|with me|out loud)|what are you (imagining|daydreaming about))\b")


def asked(prompt: str):
    """None if this isn't an 'imagine' request, else the topic ('' for anything)."""
    if not ENABLED:
        return None
    p = (prompt or "").lower().strip().rstrip("?.!")
    m = ASK.search(p)
    if not m:
        return None
    rest = (m.group("rest") or "").strip() if m.groupdict().get("rest") is not None else ""
    rest = re.sub(r"^(that|this|for me|for us|with me|please)\b\s*", "", rest)
    rest = re.sub(r"\s*\b(for me|please|chatty)$", "", rest).strip()
    if rest in ("", "something", "anything", "some thing", "something fun", "something silly",
                "something for me", "a thing", "stuff", "something new", "something cool"):
        return ""
    return rest


def _swap_people(text: str) -> str:
    out = []
    for word in text.split():
        bare = word.strip(",.!?").lower()
        new = _SWAP.get(bare)
        out.append(word if new is None else word.lower().replace(bare, new))
    s = " ".join(out)
    s = re.sub(r"\bI are\b", "I am", s)
    s = re.sub(r"\byou am\b", "you are", s)
    s = re.sub(r"\byou (has|was)\b", lambda m: "you " + {"has": "have", "was": "were"}[m.group(1)], s)
    return s


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _kicker(rng: random.Random, own=None) -> str:
    if own and rng.random() < 0.7:
        return rng.choice(own)
    return rng.choice(GENERAL_KICKERS)


def idea(rng: random.Random | None = None, topic: str = "") -> str:
    """Something whimsical she just made up, about `topic` if given."""
    rng = rng or random.Random()
    topic = " ".join((topic or "").split()[:14])
    if not topic:
        premise, own = rng.choice(PREMISES)
        return f"{rng.choice(OPENERS_RANDOM).format(p=premise)} {_kicker(rng, own)}"
    clause = re.match(r"^(what if|if|that|a world where|a world in which|what would happen if|"
                      r"what it would be like if|how it would be if)\s+(?P<c>.+)$", topic)
    if clause:
        c = clause.group("c")
    elif re.match(r"^(you|i|we|everyone|everybody|nobody|people|there)\s+(?!as\b)\w", topic) or \
            re.match(r"^(\w+ ){1,3}(could|can|were|was|had|would|did|started|learned|lived)\b", topic):
        c = topic
    else:
        c = ""
    if c:
        c = _swap_people(c)
        return rng.choice(CLAUSE_IDEAS).format(c=c, k=_kicker(rng))
    t = re.sub(r"^I\b", "me", _swap_people(topic))       # "imagine you" -> "imagine me"
    t = re.sub(r"^tiny( the cat)?(?= as |$)", "Tiny the cat", t)
    person = bool(re.match(r"^(Tiny the cat|you|me|us|yourself|myself|chatty|vincent|"
                           r"(you|me|us|Tiny the cat|chatty|vincent) as .+)$", t))
    t = re.sub(r"^(yourself|myself|chatty)\b", lambda m: {"chatty": "me", "yourself": "you",
                                                         "myself": "me"}[m.group(1)], t)
    t = re.sub(r"^vincent\b", "Vincent", t)
    if person and " as " in t:
        return f"{rng.choice(TOPIC_OPENERS)} {t}! {_kicker(rng)}"
    if person:
        return f"{rng.choice(TOPIC_OPENERS)} {rng.choice(PERSON_IDEAS).format(t=t)}"
    if not re.match(r"^(a|an|the|my|your|our|some|two|three|four|\d+)\b", t):
        if t.endswith("s") and not t.endswith("ss"):
            t = rng.choice(["a little band of ", "a whole family of ", "a parade of "]) + t
        else:
            t = ("an " if t[:1] in "aeiou" else "a ") + t
    return f"{rng.choice(TOPIC_OPENERS)} {rng.choice(TOPIC_IDEAS).format(t=t)}"


def intro(rng: random.Random | None = None) -> str:
    return (rng or random).choice(INTROS)


# ----------------------------------------------------------------- drawing
def mix(col, k):
    """Fade a color toward the background (k = 1 full color, 0 background)."""
    return tuple(int(b + (a - b) * k) for a, b in zip(col, BG))


def hue_color(t: float, s: float = 0.55, v: float = 1.0):
    """A color that slowly cycles through the rainbow (her eyes while imagining)."""
    return tuple(int(x * 255) for x in colorsys.hsv_to_rgb((t * 0.18) % 1.0, s, v))


def sweep(age: float) -> float:
    """0..1: how far the hands have swept the rainbow open (eased)."""
    t = max(0.0, min(1.0, age / SWEEP))
    return 1 - (1 - t) ** 3


def star(c, color, x, y, r):
    """A little four-point sparkle."""
    c.polygon(color, [(x, y - 2.4 * r), (x + r * 0.45, y - r * 0.45), (x + 2.4 * r, y),
                      (x + r * 0.45, y + r * 0.45), (x, y + 2.4 * r), (x - r * 0.45, y + r * 0.45),
                      (x - 2.4 * r, y), (x - r * 0.45, y - r * 0.45)])


def _hand(c, x, y, r, outward: float, color, now: float):
    """A round little hand with four spread fingers and a thumb ("jazz hands")."""
    c.ellipse(color, (x - r, y - r, 2 * r, 2 * r))
    wiggle = math.sin(now * 9) * 0.08
    fw = max(3, int(r * 0.5))
    for k, spread in enumerate((-0.75, -0.25, 0.25, 0.75)):
        a = outward + spread * 0.9 + wiggle * (1 if k % 2 else -1)
        L = r * (1.55 if k in (1, 2) else 1.35)
        fx, fy = x + math.cos(a) * L, y - math.sin(a) * L
        c.line(color, (x, y), (fx, fy), fw)
        c.ellipse(color, (fx - fw * 0.55, fy - fw * 0.55, fw * 1.1, fw * 1.1))
    a = outward - 1.75                  # the thumb, tucked lower
    tx, ty = x + math.cos(a) * r * 1.15, y - math.sin(a) * r * 1.15
    c.line(color, (x, y), (tx, ty), fw)
    c.ellipse(color, (tx - fw * 0.55, ty - fw * 0.55, fw * 1.1, fw * 1.1))


def draw_rainbow(c, w, h, now, since, k=1.0, box=None, hands=True, sparkles=True):
    """The rainbow sweeping open between her hands. `since` is when the sweep began,
    `box` (x, y, bw, bh) the ellipse the outer band follows (the top half is drawn),
    k fades everything (1 = full color)."""
    x0, y0, bw, bh = box or (w * 0.05, h * 0.05, w * 0.90, h * 1.02)
    s = sweep(now - since)
    if s <= 0:
        return
    band = max(5, int(h * 0.021))
    half = math.pi / 2 * s
    start, stop = math.pi / 2 - half, math.pi / 2 + half
    for i, col in enumerate(RAINBOW):
        inset = i * band * 0.92
        rect = (x0 + inset, y0 + inset, bw - 2 * inset, bh - 2 * inset)
        c.arc(mix(col, k), rect, start, stop, band)
    cx, cy = x0 + bw / 2, y0 + bh / 2
    mid_rx = bw / 2 - band * 2.6
    mid_ry = bh / 2 - band * 2.6
    if sparkles:
        rng = random.Random(int(since * 10))
        for j in range(14):
            a = rng.uniform(0.08, 0.92) * math.pi
            if abs(a - math.pi / 2) > half:
                continue                         # only where the rainbow already is
            rr = rng.uniform(0.75, 1.25)
            px = cx + math.cos(a) * (bw / 2) * rr * 0.98
            py = cy - math.sin(a) * (bh / 2) * rr * 0.98
            tw = 0.5 + 0.5 * math.sin(now * rng.uniform(2.5, 4.5) + j)
            if tw < 0.3:
                continue                         # twinkled out for a moment
            star(c, mix(RAINBOW[j % len(RAINBOW)] if j % 3 else (255, 255, 255), k * tw),
                 px, py, h * 0.008 * (0.6 + tw))
    if hands:
        r = h * 0.052
        for side in (-1, 1):
            a = math.pi / 2 + side * half
            hx, hy = cx + math.cos(a) * mid_rx, cy - math.sin(a) * mid_ry
            _hand(c, hx, hy, r, a, mix(HAND, k), now)


# ----------------------------------------------------------------- daydream
class Daydream:
    """Screen-only daydream when she's bored: the rainbow sweeps open over a small,
    starry-eyed face, then an idea types itself out underneath."""

    def __init__(self, rng: random.Random, now: float, topic: str = ""):
        self.rng = rng
        self.started = now
        self.text = idea(rng, topic)
        self.style = "imagine"        # the face keeps it in its doodle slot
        self.done = False
        self.spoken = False           # set by the face once it asked the voice to say it
        self.dim = 0.55 if quiet_hours.is_night(now) else 1.0

    def typed(self, now: float) -> int:
        """How many letters of the idea are on screen so far."""
        t = now - self.started - SWEEP - 0.6
        return 0 if t < 0 else min(len(self.text), int(t * 24))

    def finished_typing(self, now: float) -> bool:
        return self.typed(now) >= len(self.text)

    def update(self, now: float):
        if now - self.started > SECONDS:
            self.done = True

    def status(self, now: float) -> str:
        return "Daydreaming - tap to stop"

    def draw(self, c, w, h, now):
        k = self.dim * min(1.0, (now - self.started) / 0.4, max(0.0, (self.started + SECONDS - now) / 1.5))
        # a few faint background stars
        rng = random.Random(int(self.started))
        for j in range(18):
            x, y = rng.uniform(0.03, 0.97) * w, rng.uniform(0.04, 0.86) * h
            tw = 0.25 + 0.25 * math.sin(now * rng.uniform(1.0, 2.5) + j)
            star(c, mix((200, 210, 255), k * tw), x, y, h * 0.004)
        box = (w * 0.12, h * 0.07, w * 0.76, h * 0.86)
        draw_rainbow(c, w, h, now, self.started, k, box=box)
        # a little starry-eyed face under the arch, looking up at it
        face = mix(hue_color(now - self.started), k)
        ey, er = h * 0.40, h * 0.06
        for ex in (w * 0.45, w * 0.55):
            c.rrect(face, (ex - er * 0.55, ey - er, er * 1.1, er * 2), radius=er * 0.5)
            star(c, mix((255, 255, 255), k), ex - er * 0.12, ey - er * 0.45, er * 0.12)
        c.arc(face, (w * 0.47, ey + er * 0.55, w * 0.06, h * 0.07), math.pi * 1.1, math.pi * 1.9,
              max(3, int(h * 0.008)))
        # the idea, typed out under the rainbow
        shown = self.text[:self.typed(now)]
        if shown:
            size = max(14, int(h * 0.05))
            lines = _wrap(c, shown, size, w * 0.86)
            y = h * 0.56
            for line in lines[:4]:
                c.text(line, ((w - c.measure(line, size)) / 2, y), size, mix(TEXT, k))
                y += size * 1.3


def _wrap(c, text: str, size: int, max_width: float) -> list:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and c.measure(trial, size) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


if __name__ == "__main__":
    r = random.Random()
    if len(sys.argv) > 1:
        print(idea(r, " ".join(sys.argv[1:])))
    else:
        for _ in range(6):
            print("-", idea(r))
        for t in ("a dragon", "if dogs could fly", "you were a cloud", "my garden", "a castle"):
            print(f"- [{t}]", idea(r, t))

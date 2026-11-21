"""
Who's the Trickster? A little mystery game on Chatty's face.

The nodes (Lightning, Rain, Greenhouse, the Word Clock) walk around a tiny map of
the yard doing their chores: counting raindrops at the rain gauge, watering the
tomatoes, winding the clock, sorting Chatty's letters at the mailbox. One of
them is secretly the trickster. The trickster only plays kind, harmless pranks
(the golden rule): hides the rain gauge's raindrops in a teacup, puts party
hats on the tomatoes, ties a balloon to the lightning rod...

Each prank goes into Chatty's notebook with who was seen nearby. After a few
pranks (or when the chores are all done, or when you call one) Chatty rings her
bell for a tea meeting: everyone says where they were (the trickster fibs a
little), then everybody votes. You can vote too, by tapping a character, from
the remote panel, or by voice ("Hey Chatty, I vote Rain"). Whoever it was takes
a bow, nobody is ever in trouble, and everyone gets a gold star.

Chatty plays all the characters herself: nothing is sent to the real nodes
(they stay read-only), and nothing is spoken; it all happens on her screen.

How it starts:
  - when she's bored she sometimes hosts one (CHATTY_TRICKSTER_SHARE)
  - "Hey Chatty, who's the trickster?" / "play the mystery game"
  - the remote panel ("Start a mystery")
  - face message `trickster`; `trickster:meeting` rings the bell,
    `trickster:vote:<node>` votes.
A tap hides it (except on the bell, which calls the meeting, and on a character
while voting, which votes). Talking to her just pauses it.
"What's the trickster score?" tells how many mysteries were solved
(~/.local/share/chatty/trickster.json).

Settings (in /etc/chatty/secrets.env):
  CHATTY_TRICKSTER=0             no mystery game
  CHATTY_TRICKSTER_SHARE=0.15    when bored, how often she picks it
  CHATTY_TRICKSTER_VOTE=25       seconds to wait for your vote (when you started it)
"""
from __future__ import annotations

import json
import storage  # safe JSON saves (atomic, owner-only)
import math
import os
import random
import re
from typing import Optional

try:
    import chess_match
    import quiet_hours
except ImportError:  # running from another folder
    from . import chess_match, quiet_hours  # type: ignore

ENABLED = os.getenv("CHATTY_TRICKSTER", "1") != "0"
SHARE = float(os.getenv("CHATTY_TRICKSTER_SHARE", "0.15"))
VOTE_SECONDS = float(os.getenv("CHATTY_TRICKSTER_VOTE", "25"))
AUTO_VOTE_SECONDS = 9.0     # when nobody asked for the game, she doesn't wait long
FPS = 15
SCORES = os.path.expanduser(os.getenv("CHATTY_TRICKSTER_SCORES", "~/.local/share/chatty/trickster.json"))
FORGET_AFTER = 600          # a game paused (she's talking) longer than this is dropped

NAMES = ("lightning", "rain", "greenhouse", "wordclock")
PRANKS = 3
CHORES_GOAL = 32
SPEED = 0.2                 # map widths per second
NEAR = 0.2                  # "seen nearby" distance (map units)

INTRO = 5.0
GATHER = 3.0
OPENING = 4.0
ALIBI = 3.6
REVEAL = 4.0
OUTRO = 7.0

BG = (8, 10, 14)
YARD = (16, 22, 26)
PATH = (34, 44, 50)
TEXT = (210, 220, 228)
SOFT = (130, 140, 158)
GOLD = (255, 204, 64)
FACE = (225, 240, 236)
PAPER = (22, 26, 36)
CONFETTI = ((255, 120, 160), (255, 204, 64), (120, 200, 255), (130, 220, 160), (190, 160, 255))

# the yard: where the chores (and the pranks) happen, in map units (0..1)
STATIONS = {
    "rain":  dict(name="rain gauge", pos=(0.15, 0.32),
                  chores=["counting raindrops", "polishing the rain gauge"],
                  prank="Someone hid the rain gauge's raindrops in a teacup!", short="Teacup raindrops", nick="teacup prank"),
    "green": dict(name="greenhouse", pos=(0.85, 0.32),
                  chores=["watering the tomatoes", "opening the greenhouse windows"],
                  prank="Someone put tiny party hats on the tomatoes!", short="Hats on the tomatoes", nick="party hat prank"),
    "rod":   dict(name="lightning rod", pos=(0.15, 0.84),
                  chores=["checking the lightning rod", "listening for thunder"],
                  prank="Someone tied a balloon to the lightning rod!", short="Balloon on the rod", nick="balloon prank"),
    "clock": dict(name="clock tower", pos=(0.85, 0.84),
                  chores=["winding the clock", "dusting the clock hands"],
                  prank="Someone drew a smiley face on the clock!", short="Smiley on the clock", nick="smiley prank"),
    "mail":  dict(name="mailbox", pos=(0.5, 0.58),
                  chores=["sorting Chatty's letters", "tidying the mailbox"],
                  prank="Someone left a paper flower in Chatty's mailbox!", short="Mailbox flower", nick="flower prank"),
}
SLOTS = [(-0.1, 0.06), (0.1, 0.06), (-0.1, -0.08), (0.1, -0.08)]   # where each one stands at a spot
PATHS = [("rain", "green"), ("green", "clock"), ("clock", "rod"), ("rod", "rain"),
         ("rain", "mail"), ("green", "mail"), ("clock", "mail"), ("rod", "mail")]

# each character's own little voice
LINES = {
    "lightning": dict(caught=["Zap! You caught me! I just wanted to see you smile.",
                              "Crackle... okay, it was me! Wasn't it fun?"],
                      innocent=["Not me! I was busy charging up.", "Zzz-not me! I promise!"],
                      fib=["Me? I was just... watching the clouds. For science."]),
    "rain": dict(caught=["Drip... okay, it was me. I'll put everything back, promise!",
                         "Pitter-patter, you got me! I'll tidy up."],
                 innocent=["Not me! I was drizzling quietly.", "Drip, drop, not me!"],
                 fib=["I was just... resting my clouds. Nowhere near anything."]),
    "greenhouse": dict(caught=["Guilty! I couldn't resist. Didn't it look festive?",
                               "It was me! A little something to make you smile."],
                       innocent=["Not me! My hands are full of soil.", "Not me! I was with my seedlings."],
                       fib=["Who, me? I was talking to my seedlings. They'll vouch for me."]),
    "wordclock": dict(caught=["It is... confession o'clock. It was me!",
                              "Tick, tock, you caught me. Right on time!"],
                      innocent=["Not me! I'm always on time, never on mischief.", "It is not me o'clock."],
                      fib=["I was keeping time, as always. Tick, tock, nothing to see."]),
}


def title(name: str) -> str:
    return chess_match.person(name)["title"]


def color(name: str):
    return chess_match.person(name)["color"]


def node_key(text: str) -> str:
    """'the rain node' -> 'rain', 'word clock' -> 'wordclock', '' if it isn't one."""
    t = (text or "").lower()
    for name, pat in (("lightning", "lightning"), ("rain", "rain|raindrop"), ("greenhouse", "greenhouse|garden|green"),
                      ("wordclock", "word ?clock|clock")):
        if re.search(r"\b(" + pat + r")\b", t):
            return name
    return ""


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ----- the scoreboard -----

def load_scores() -> dict:
    try:
        with open(SCORES) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record(trickster: str, solved: bool) -> None:
    data = load_scores()
    data["games"] = int(data.get("games", 0)) + 1
    data["solved"] = int(data.get("solved", 0)) + (1 if solved else 0)
    who = data.setdefault("tricksters", {})
    who[trickster] = int(who.get(trickster, 0)) + 1
    try:
        storage.save_json(SCORES, data)
    except OSError:
        pass


def score_text() -> str:
    data = load_scores()
    games = int(data.get("games", 0))
    if not games:
        return ("We haven't played Who's the Trickster yet. Say \"who's the trickster?\" "
                "and watch my screen!")
    solved = int(data.get("solved", 0))
    line = (f"We've played {games} {'mystery' if games == 1 else 'mysteries'} "
            f"and solved {solved} of them.")
    tricks = data.get("tricksters") or {}
    if tricks:
        top = max(sorted(tricks), key=lambda n: tricks[n])
        n = tricks[top]
        line += (f" {title(top)} has been the trickster {'once' if n == 1 else f'{n} times'}."
                 + (" Sneaky!" if n > 1 else ""))
    return line


# ----- one character on the map -----

class Walker:
    def __init__(self, name: str, at: str, rng: random.Random, slot=(0.0, 0.0)):
        self.name = name
        self.station = at
        self.slot = slot
        self.pos = (STATIONS[at]["pos"][0] + slot[0], STATIONS[at]["pos"][1] + slot[1])
        self.dest = at
        self.mode = "chore"        # walk | chore | gather | meet
        self.until = rng.uniform(1.0, 3.0)
        self.chore = rng.choice(STATIONS[at]["chores"])
        self.pranking = False
        self.facing = 1
        self.progress = 0.0


# ----- the game -----

class Mystery:
    def __init__(self, rng: random.Random, now: float, human: bool = False, names=None):
        self.rng = rng
        self.human = human                  # someone asked for it, so wait for their vote
        self.names = [n for n in (names or NAMES)][:4]
        self.trickster = rng.choice(self.names)
        spots = list(STATIONS)
        rng.shuffle(spots)
        self.walkers = {n: Walker(n, spots[i % len(spots)], rng, SLOTS[i % len(SLOTS)])
                        for i, n in enumerate(self.names)}
        self.t = 0.0                        # game time: only runs while it's on screen
        self.last_now = now
        self.phase = "intro"                # intro, play, gather, opening, alibi, vote, reveal, outro
        self.phase_at = 0.0
        self.done = False
        self.clues = []                     # dict(station, near, t, pos)
        self.pranked = set()
        self.next_prank = rng.uniform(9, 13)
        self.chores = 0
        self.meeting_by = None              # "chatty" or "you"
        self.claims = {}                    # name -> station they say they were at
        self.alibis = []                    # (name, line) in speaking order
        self.alibi_i = -1
        self.ballots = {}                   # voter -> suspect (nodes, "chatty", "you")
        self.ballot_order = []
        self.you = None                     # your vote
        self.accused = None
        self.solved = False
        self.speaker, self.message, self.message_at = "chatty", "", 0.0
        self.mood = "happy"
        self.tiny = None                    # Tiny the cat strolls through now and then
        self.tiny_at = rng.uniform(15, 40) if rng.random() < 0.3 else None
        self.confetti = []
        self.dim = 0.6 if quiet_hours.is_night(now) else 1.0
        self._say("chatty", rng.choice([
            "Everybody's doing their chores. But one of us is a trickster... Watch closely!",
            "Chore time in the yard! Somebody here likes pranks. Can you spot who?",
            "Who's the trickster? Keep an eye on everyone. I'll take notes!"]))

    # ----- words -----
    def _say(self, who: str, text: str):
        self.speaker, self.message, self.message_at = who, text, self.t

    def _phase(self, name: str):
        self.phase, self.phase_at = name, self.t

    # ----- outside events -----
    def call_meeting(self, by: str = "you") -> bool:
        if self.phase not in ("intro", "play"):
            return False
        self.meeting_by = by
        if by == "you":
            line = ("A meeting already? Nothing's been pranked yet... but okay! Tea meeting!"
                    if not self.clues else "Ding ding! You rang the bell. Tea meeting, everyone!")
        elif self.chores >= CHORES_GOAL and len(self.clues) < PRANKS:
            line = "All the chores are done! Tea meeting: who's been pranking?"
        else:
            line = "Ding ding! Three pranks is plenty. Tea meeting at the mailbox!"
        self._say("chatty", line)
        for w in self.walkers.values():
            w.mode, w.dest, w.pranking = "gather", "mail", False
        self._phase("gather")
        return True

    def vote(self, suspect: str, by: str = "you") -> bool:
        """Your vote (tap, panel or voice). Before the vote it rings the bell first."""
        suspect = node_key(suspect) if suspect not in self.names else suspect
        if suspect not in self.names:
            return False
        if self.phase in ("intro", "play"):
            self.call_meeting("you")
        if self.phase in ("reveal", "outro") or self.you:
            return False
        self.you = suspect
        if self.phase == "vote":
            self._say("chatty", f"Your vote is in: {title(suspect)}!")
        return True

    # ----- clues and suspicion -----
    def near(self, station: str) -> list:
        spot = STATIONS[station]["pos"]
        return sorted(n for n, w in self.walkers.items() if _dist(w.pos, spot) <= NEAR)

    def _contradicts(self, name: str) -> bool:
        """Seen near the last prank, but says they were somewhere else."""
        if not self.clues or name not in self.claims:
            return False
        last = self.clues[-1]
        return name in last["near"] and self.claims[name] != last["station"]

    def suspicion(self, name: str) -> float:
        return sum(1 for c in self.clues if name in c["near"]) + (1.5 if self._contradicts(name) else 0)

    def best_guess(self, exclude: str = "") -> str:
        options = [n for n in self.names if n != exclude]
        top = max(self.suspicion(n) for n in options)
        return self.rng.choice([n for n in options if self.suspicion(n) == top])

    def notebook_line(self) -> str:
        """What Chatty thinks so far (for the panel and the meeting)."""
        if not self.clues:
            return "No pranks yet. Everyone's an angel... so far."
        sure = [n for n in self.names if all(n in c["near"] for c in self.clues)]
        if len(sure) == 1:
            return f"{title(sure[0])} was near every prank. Hmm!"
        if sure:
            return "Near every prank: " + ", ".join(title(n) for n in sure) + "."
        return "Nobody was near every prank. Tricky!"

    # ----- the clock -----
    def update(self, now: float):
        dt = max(0.0, min(0.25, now - self.last_now))
        self.last_now = now
        if self.done:
            return
        self.t += dt
        t = self.t
        self._move(dt)
        self._update_confetti(dt)
        if self.tiny is not None:
            self.tiny += dt * 0.09
            if self.tiny > 1.15:
                self.tiny = None
        elif self.tiny_at is not None and t >= self.tiny_at and self.phase == "play":
            self.tiny, self.tiny_at = -0.1, None
            self._say("chatty", "Tiny wandered through. Tiny is never the trickster. Probably.")

        if self.phase == "intro" and t - self.phase_at >= INTRO:
            self._phase("play")
        elif self.phase == "play":
            if len(self.clues) >= PRANKS and t - self.clues[-1]["t"] > 5:
                self.call_meeting("chatty")
            elif self.chores >= CHORES_GOAL and t - self.message_at > 2:
                self.call_meeting("chatty")
            elif t > 95:
                self.call_meeting("chatty")
        elif self.phase == "gather" and t - self.phase_at >= GATHER:
            self._start_meeting()
        elif self.phase == "opening" and t - self.phase_at >= OPENING:
            self._next_alibi()
        elif self.phase == "alibi" and t - self.phase_at >= ALIBI:
            self._next_alibi()
        elif self.phase == "vote":
            self._update_vote()
        elif self.phase == "reveal" and t - self.phase_at >= REVEAL:
            self._outro()
        elif self.phase == "outro" and t - self.phase_at >= OUTRO:
            self.done = True

    def _move(self, dt: float):
        for w in self.walkers.values():
            if w.mode in ("walk", "gather"):
                spot = STATIONS[w.dest]["pos"]
                spot = (spot[0] + w.slot[0], spot[1] + w.slot[1])
                if w.mode == "gather":      # stand in a little circle around the mailbox
                    k = self.names.index(w.name)
                    a = k * math.pi / 2 + math.pi / 4
                    spot = STATIONS[w.dest]["pos"]
                    spot = (spot[0] + 0.12 * math.cos(a), spot[1] + 0.16 * math.sin(a))
                d = _dist(w.pos, spot)
                step = SPEED * dt
                if d > 1e-6:
                    w.facing = 1 if spot[0] >= w.pos[0] else -1
                if d <= step:
                    w.pos = spot
                    if w.mode == "walk":
                        self._arrive(w)
                    else:
                        w.mode = "meet"
                else:
                    w.pos = (w.pos[0] + (spot[0] - w.pos[0]) * step / d,
                             w.pos[1] + (spot[1] - w.pos[1]) * step / d)
            elif w.mode == "chore" and self.phase in ("intro", "play"):
                w.progress = min(1.0, w.progress + dt / max(0.1, w.until))
                if w.progress >= 1.0:
                    if self.phase == "play":
                        self.chores += 1
                    self._next_errand(w)

    def _arrive(self, w: Walker):
        w.station = w.dest
        if w.pranking:
            w.pranking = False
            self._prank(w.station)
        w.mode, w.progress = "chore", 0.0
        w.until = self.rng.uniform(3.5, 6.5)
        w.chore = self.rng.choice(STATIONS[w.station]["chores"])

    def _next_errand(self, w: Walker):
        if (w.name == self.trickster and self.phase == "play" and self.t >= self.next_prank
                and len(self.pranked) < PRANKS):
            w.dest, w.pranking = self._prank_target(w), True
        else:
            w.dest = self.rng.choice([s for s in STATIONS if s != w.station])
        w.mode = "walk"
        if w.dest == w.station:          # pranking right where it stands
            self._arrive(w)

    def _prank_target(self, w: Walker) -> str:
        """An unpranked spot, preferring one where somebody else is busy (cover)."""
        left = [s for s in STATIONS if s not in self.pranked]
        busy = [s for s in left if any(o.name != w.name and o.mode == "chore" and o.station == s
                                       for o in self.walkers.values())]
        return self.rng.choice(busy or left)

    def _prank(self, station: str):
        self.pranked.add(station)
        clue = dict(station=station, near=self.near(station), t=self.t,
                    pos={n: w.pos for n, w in self.walkers.items()})
        self.clues.append(clue)
        self.next_prank = self.t + self.rng.uniform(12, 18)
        who = ", ".join(title(n) for n in clue["near"])
        self._say("chatty", STATIONS[station]["prank"] + f" Seen nearby: {who}.")
        self.mood = "puzzled"

    # ----- the meeting -----
    def _start_meeting(self):
        for w in self.walkers.values():
            w.mode = "meet"
        last = self.clues[-1] if self.clues else None
        for n, w in self.walkers.items():
            if last is None:
                spot = min(STATIONS, key=lambda s: _dist(STATIONS[s]["pos"], w.pos))
            elif n == self.trickster:          # a little fib: "I was nowhere near it"
                far = [s for s in STATIONS if _dist(STATIONS[s]["pos"], STATIONS[last["station"]]["pos"]) > NEAR]
                spot = self.rng.choice(far)
            else:
                p = last["pos"][n]
                spot = min(STATIONS, key=lambda s: _dist(STATIONS[s]["pos"], p))
            self.claims[n] = spot
        order = list(self.names)
        self.rng.shuffle(order)
        what = STATIONS[last["station"]]["nick"] if last else ""
        for n in order:
            st = STATIONS[self.claims[n]]
            chore = self.rng.choice(st["chores"])
            if last is None:
                line = f"I was {chore} at the {st['name']}. Did anything even happen?"
            elif n == self.trickster:
                if self.rng.random() < 0.6:
                    line = f"During the {what}? I was {chore} at the {st['name']}. Far away!"
                else:                          # vague: says nowhere in particular
                    line = self.rng.choice(LINES[n]["fib"])
                    del self.claims[n]
            elif self.claims[n] == last["station"]:
                line = f"I was {chore} at the {st['name']}, right there! But I didn't see who did it."
            else:
                line = f"During the {what}, I was {chore} at the {st['name']}."
            self.alibis.append((n, line))
        n = len(self.clues)
        self._say("chatty", ("Tea meeting! " + (f"{n} prank{'s' if n != 1 else ''} so far. " if n else "")
                             + "Let's hear from everyone. Where were you?"))
        self.mood = "happy"
        self._phase("opening")

    def _next_alibi(self):
        self.alibi_i += 1
        if self.alibi_i < len(self.alibis):
            who, line = self.alibis[self.alibi_i]
            self._say(who, line)
            self._phase("alibi")
            return
        # time to vote: the nodes decide now, and show their votes one by one
        order = list(self.names)
        self.rng.shuffle(order)
        for n in order:
            if n != self.trickster and self.rng.random() < 0.3:
                pick = self.rng.choice([o for o in self.names if o != n])
            else:
                pick = self.best_guess(exclude=n)
            self.ballots[n] = pick
        self.ballot_order = order
        self._say("chatty", f"Time to vote! You picked {title(self.you)}. Let's see the others..." if self.you
                  else "Time to vote! Tap who you think the trickster is.")
        self.mood = "thinking"
        self._phase("vote")

    def shown_ballots(self) -> list:
        """The node votes that are on screen so far: [(voter, suspect)]."""
        if self.phase != "vote":
            return [(v, self.ballots[v]) for v in self.ballot_order] if self.ballots else []
        k = int(max(0.0, self.t - self.phase_at - 2.0) / 1.6)
        return [(v, self.ballots[v]) for v in self.ballot_order[:k]]

    def vote_left(self) -> float:
        wait = VOTE_SECONDS if self.human else AUTO_VOTE_SECONDS
        return max(0.0, wait - (self.t - self.phase_at))

    def _update_vote(self):
        all_shown = len(self.shown_ballots()) >= len(self.ballot_order)
        if all_shown and (self.you or self.vote_left() <= 0):
            self._tally()

    def _tally(self):
        mine = self.you or self.best_guess()
        self.ballots["chatty"] = mine
        if self.you:
            self.ballots["you"] = self.you
        counts = {}
        for s in self.ballots.values():
            counts[s] = counts.get(s, 0) + 1
        top = max(counts.values())
        leaders = [n for n in self.names if counts.get(n) == top]
        self.accused = self.you if self.you in leaders else mine if mine in leaders else self.rng.choice(leaders)
        self.solved = self.accused == self.trickster
        if self.solved:
            self._say(self.trickster, self.rng.choice(LINES[self.trickster]["caught"]))
            self._burst()
            self.mood = "proud"
        else:
            self._say(self.accused, self.rng.choice(LINES[self.accused]["innocent"]))
            self.mood = "puzzled"
        record(self.trickster, self.solved)
        self._phase("reveal")

    def _outro(self):
        t = title(self.trickster)
        if self.solved:
            lines = ["Mystery solved! Nobody's in trouble. Everyone gets a gold star!",
                     f"Well spotted! {t} makes the tea today. Pranks are only allowed if they make someone smile.",
                     "Case closed! That's the golden rule of tricksters: every prank has to be kind."]
            self._say("chatty", self.rng.choice(lines))
        else:
            self._say(self.trickster, self.rng.choice([
                f"Hee hee! It was me, {t}, all along! Sorry, {title(self.accused)}!",
                f"Psst... it was me, {t}! I'll put everything back."]))
            self._burst(small=True)
        self.mood = "happy"
        self._phase("outro")

    # ----- confetti -----
    def _burst(self, small: bool = False):
        for _ in range(25 if small else 60):
            self.confetti.append([self.rng.uniform(0.05, 0.95), self.rng.uniform(-0.4, 0.0),
                                  self.rng.uniform(0.12, 0.3), self.rng.uniform(0, 6.28),
                                  self.rng.choice(CONFETTI)])

    def _update_confetti(self, dt: float):
        for p in self.confetti:
            p[1] += p[2] * dt
            p[3] += dt * 4
        self.confetti = [p for p in self.confetti if p[1] < 1.1]

    # ----- taps -----
    def bell_box(self, w, h):
        x0, y0, mw, mh = self.map_box(w, h)
        r = h * 0.055
        return x0 + mw + w * 0.02 + r * 0.2, y0 + h * 0.76 - 2.2 * r, r

    def tap(self, pos, w, h) -> Optional[bool]:
        """True: used (a vote, or the bell); False: not used; None: hide the game."""
        x, y = pos
        if self.phase in ("intro", "play"):
            bx, by, r = self.bell_box(w, h)
            if bx - r * 0.5 <= x <= w * 0.98 and by - r <= y <= by + r * 1.4:
                self.call_meeting("you")
                return True
            return None
        if self.phase == "vote" and not self.you:
            for n, (cx, cy, r) in self.seats(w, h).items():
                if abs(x - cx) <= r * 1.5 and abs(y - cy) <= r * 1.8:
                    return self.vote(n)
            return True
        if self.phase == "outro":
            return None
        return True          # mid-meeting: taps don't wake her or end it

    def status(self) -> str:
        if self.phase in ("intro", "play"):
            return "Who's the trickster? Tap the bell for a meeting"
        if self.phase == "vote":
            if self.you:
                return "Counting votes"
            return f"Tap who you think it is ({int(self.vote_left() + 0.99)})"
        if self.phase in ("reveal", "outro"):
            return "Mystery solved!" if self.solved else "The trickster got away!"
        return "Tea meeting"

    def panel_info(self) -> dict:
        return {"phase": self.phase, "chores": self.chores, "chores_goal": CHORES_GOAL,
                "clues": [{"what": STATIONS[c["station"]]["short"], "near": [title(n) for n in c["near"]]}
                          for c in self.clues],
                "thinks": self.notebook_line(), "can_vote": self.phase not in ("reveal", "outro") and not self.you,
                "you": title(self.you) if self.you else "",
                "accused": title(self.accused) if self.accused else "",
                "trickster": title(self.trickster) if self.phase in ("reveal", "outro") else ""}

    # ----- drawing -----
    @staticmethod
    def map_box(w, h):
        return w * 0.02, h * 0.1, w * 0.64, h * 0.64

    def _mix(self, col, a=1.0):
        k = self.dim * a
        return tuple(int(b + (x - b) * k) for x, b in zip(col, BG))

    def draw(self, c, w, h, now):
        if self.phase in ("intro", "play", "gather"):
            self._draw_yard(c, w, h, now)
        else:
            self._draw_meeting(c, w, h, now)
        for x, y, _, a, col in self.confetti:
            s = h * 0.012
            c.rrect(self._mix(col), (x * w, y * h, s * (1.2 + math.sin(a)), s), radius=1)

    def _xy(self, p, w, h):
        x0, y0, mw, mh = self.map_box(w, h)
        return x0 + p[0] * mw, y0 + p[1] * mh

    def _draw_yard(self, c, w, h, now):
        m = self._mix
        x0, y0, mw, mh = self.map_box(w, h)
        c.rrect(m(YARD), (x0, y0, mw, mh), radius=h * 0.03)
        lw = max(3, int(h * 0.012))
        for a, b in PATHS:
            c.line(m(PATH), self._xy(STATIONS[a]["pos"], w, h), self._xy(STATIONS[b]["pos"], w, h), lw)
        r = h * 0.06
        for key, st in STATIONS.items():
            cx, cy = self._xy(st["pos"], w, h)
            draw_station(c, key, cx, cy, r, m, key in self.pranked, now)
        if self.tiny is not None:
            draw_tiny(c, x0 + self.tiny * mw, y0 + mh * 0.95, h * 0.035, m, now)
        for n in sorted(self.walkers, key=lambda n: self.walkers[n].pos[1]):
            wk = self.walkers[n]
            cx, cy = self._xy(wk.pos, w, h)
            moving = wk.mode in ("walk", "gather")
            hop = abs(math.sin(now * 7 + hash(n) % 7)) * h * 0.012 if moving else 0
            cy -= r * 0.75
            draw_character(c, n, cx, cy - hop, h * 0.04, m, look=wk.facing * (0.6 if moving else 0.2),
                           shadow_y=cy + h * 0.04)
            if wk.mode == "chore" and self.phase in ("intro", "play"):
                rr = h * 0.014
                c.arc(m(SOFT, 0.5), (cx - rr, cy - h * 0.07 - rr, 2 * rr, 2 * rr), 0, 6.283, 2)
                c.arc(m(color(n)), (cx - rr, cy - h * 0.07 - rr, 2 * rr, 2 * rr),
                      math.pi / 2, math.pi / 2 + 6.283 * wk.progress, 2)
        # Chatty, the host, and what's happening
        self._header(c, w, h, now, "Who's the Trickster?")
        if self.message:
            size = max(13, int(h * 0.04))
            lines = chess_match._wrap(c, self.message, size, mw - w * 0.02)[:2]
            ytxt = y0 + mh + h * 0.02
            for line in lines:
                c.text(line, (x0 + mw / 2 - c.measure(line, size) / 2, ytxt), size,
                       m(TEXT if self.speaker == "chatty" else color(self.speaker)))
                ytxt += size * 1.3
        self._notebook(c, w, h, now)

    def _header(self, c, w, h, now, label):
        m = self._mix
        r = h * 0.035
        draw_chatty(c, w * 0.04, h * 0.05, r, m, self.mood, now)
        size = max(15, int(h * 0.05))
        c.text(label, (w * 0.04 + r * 1.6, h * 0.05 - size * 0.55), size, m(GOLD))

    def _notebook(self, c, w, h, now):
        m = self._mix
        x0, y0, mw, mh = self.map_box(w, h)
        left, right = x0 + mw + w * 0.02, w * 0.98
        c.rrect(m(PAPER), (left, y0, right - left, h * 0.76), radius=h * 0.03)
        size = max(13, int(h * 0.04))
        small = max(12, int(h * 0.034))
        pad = w * 0.012
        c.text("Chatty's notebook", (left + pad, y0 + h * 0.015), size, m(TEXT))
        y = y0 + h * 0.075
        if not self.clues:
            for line in chess_match._wrap(c, "No pranks yet. Watch who goes where!", small, right - left - 2 * pad):
                c.text(line, (left + pad, y), small, m(SOFT))
                y += small * 1.3
        for k, clue in enumerate(self.clues):
            st = STATIONS[clue["station"]]
            c.text(f"{k + 1}. {st['short']}", (left + pad, y), small, m(GOLD))
            y += small * 1.25
            x = left + pad * 2
            c.text("near:", (x, y), small, m(SOFT))
            x += c.measure("near: ", small)
            for n in clue["near"]:
                draw_character(c, n, x + small * 0.6, y + small * 0.5, small * 0.6, m, blink=True)
                x += small * 1.6
            y += small * 1.6
        # chores bar
        by = y0 + h * 0.76 - h * 0.2
        label = f"Chores {min(self.chores, CHORES_GOAL)}/{CHORES_GOAL}"
        c.text(label, (left + pad, by), small, m(SOFT))
        bw, bh = right - left - 2 * pad, h * 0.014
        c.rrect(m(PATH), (left + pad, by + small * 1.25, bw, bh), radius=bh / 2)
        frac = min(1.0, self.chores / CHORES_GOAL)
        if frac:
            c.rrect(m((130, 210, 120)), (left + pad, by + small * 1.25, bw * frac, bh), radius=bh / 2)
        # the bell: tap it to call a tea meeting
        bx, bby, r = self.bell_box(w, h)
        ring = math.sin(now * 12) * 0.25 if self.phase == "play" and int(now) % 6 == 0 else 0
        draw_bell(c, bx + r * 0.6, bby + r * 0.3, r * 0.55, m(GOLD), ring)
        c.text("Ring for a", (bx + r * 1.4, bby - small * 0.5), small, m(SOFT))
        c.text("tea meeting", (bx + r * 1.4, bby + small * 0.75), small, m(SOFT))

    def seats(self, w, h) -> dict:
        """Where each character sits at the meeting: name -> (x, y, r)."""
        n = len(self.names)
        r = h * 0.075
        return {name: (w * (0.5 + (k - (n - 1) / 2) * 0.22), h * 0.47, r) for k, name in enumerate(self.names)}

    def _draw_meeting(self, c, w, h, now):
        m = self._mix
        self._header(c, w, h, now, "Tea meeting")
        draw_bell(c, w * 0.94, h * 0.06, h * 0.03, m(GOLD), math.sin(now * 10) * 0.2 if self.phase == "opening" else 0)
        # the clues, in a row at the top
        small = max(12, int(h * 0.034))
        if self.clues:
            parts = [STATIONS[cl["station"]]["short"] for cl in self.clues]
            line = "  ·  ".join(parts)
            c.text(line, (w / 2 - c.measure(line, small) / 2, h * 0.13), small, m(SOFT))
        if self.phase in ("opening", "alibi", "vote"):
            note = "Chatty's notebook: " + self.notebook_line()
            c.text(note, (w / 2 - c.measure(note, small) / 2, h * 0.19), small, m(GOLD, 0.8))
        # the table
        c.ellipse(m(PAPER), (w * 0.08, h * 0.5, w * 0.84, h * 0.2))
        shown = self.shown_ballots()
        for name, (cx, cy, r) in self.seats(w, h).items():
            speaking = self.phase == "alibi" and self.speaker == name
            out = self.phase in ("reveal", "outro") and name == self.accused
            caught = self.phase in ("reveal", "outro") and name == self.trickster and \
                (self.solved or self.phase == "outro")
            hop = abs(math.sin(now * 6)) * r * 0.25 if (speaking or caught) else 0
            if caught or (self.phase == "vote" and self.you == name):
                glow = 0.3 + 0.12 * math.sin(now * 4)
                c.ellipse(m(GOLD if caught else color(name), glow), (cx - r * 1.5, cy - r * 1.5, r * 3, r * 3))
            draw_character(c, name, cx, cy - hop - (r * 0.2 if out else 0), r, m,
                           look=math.sin(now * 0.7 + cx) * 0.4, sparkle=caught, now=now)
            lab = title(name)
            c.text(lab, (cx - c.measure(lab, small) / 2, cy + r * 1.25), small, m(color(name)))
            # votes for this one: a dot in each voter's color
            votes = [v for v, s in shown if s == name]
            if self.phase in ("reveal", "outro"):
                votes = [v for v, s in self.ballots.items() if s == name]
            dot = h * 0.022
            vx = cx - (len(votes) * dot * 1.4) / 2
            for v in votes:
                col = FACE if v in ("chatty", "you") else color(v)
                c.ellipse(m(col), (vx, cy + r * 1.25 + small * 1.4, dot, dot),
                          width=2 if v == "you" else 0)
                vx += dot * 1.4
        # what's being said
        if self.message:
            size = max(14, int(h * 0.046))
            lines = chess_match._wrap(c, self.message, size, w * 0.86)[:2]
            y = h * 0.74
            for line in lines:
                col = TEXT if self.speaker == "chatty" else color(self.speaker)
                c.text(line, (w / 2 - c.measure(line, size) / 2, y), size, m(col))
                y += size * 1.3


# ----- little drawings -----

def draw_character(c, name, cx, cy, r, mix, look=0.0, shadow_y=None, blink=False, sparkle=False, now=0.0):
    """A node as a character: its badge (bolt, drop, leaf, clock) with googly eyes."""
    col = mix(color(name))
    if shadow_y is not None:
        c.ellipse(mix((0, 0, 0), 0.6), (cx - r * 0.8, shadow_y - r * 0.18, r * 1.6, r * 0.36))
    icon = chess_match.person(name).get("icon", "dot")
    chess_match.draw_icon(c, icon, cx, cy, r, col)
    er = r * (0.26 if not blink else 0.3)
    ey = cy - r * (0.05 if icon != "drop" else -0.15)
    for side in (-1, 1):
        ex = cx + side * r * 0.3
        c.ellipse(mix(FACE), (ex - er, ey - er, 2 * er, 2 * er))
        pr = er * 0.5
        c.ellipse(mix(BG), (ex - pr + look * er * 0.45, ey - pr, 2 * pr, 2 * pr))
    if sparkle:
        for k in range(4):
            a = now * 2 + k * math.pi / 2
            sx, sy = cx + math.cos(a) * r * 1.5, cy + math.sin(a) * r * 1.3
            s = r * 0.18
            c.polygon(mix(GOLD), [(sx, sy - s), (sx + s * 0.3, sy), (sx, sy + s), (sx - s * 0.3, sy)])


def draw_chatty(c, cx, cy, r, mix, mood, now):
    """Chatty's own little face, the host."""
    c.rrect(mix((24, 30, 40)), (cx - r * 1.1, cy - r, r * 2.2, r * 2), radius=r * 0.6)
    ew, eh = r * 0.34, r * (0.45 if mood == "thinking" else 0.8)
    for side in (-1, 1):
        c.rrect(mix(FACE), (cx + side * r * 0.42 - ew / 2, cy - r * 0.2 - eh / 2, ew, eh), radius=ew * 0.45)
    if mood == "puzzled":
        c.line(mix(FACE), (cx - r * 0.25, cy + r * 0.5), (cx + r * 0.25, cy + r * 0.4), 2)
    else:
        c.arc(mix(FACE), (cx - r * 0.35, cy + r * 0.1, r * 0.7, r * 0.5), math.pi * 1.1, math.pi * 1.9, 2)


def draw_bell(c, cx, cy, r, col, swing=0.0):
    s, co = math.sin(swing), math.cos(swing)
    pts = [(-0.7, 0.6), (-0.6, 0.1), (-0.45, -0.45), (0, -0.75), (0.45, -0.45), (0.6, 0.1), (0.7, 0.6)]
    rot = [(cx + (u * co - v * s) * r * 1.4, cy + (u * s + v * co) * r * 1.4) for u, v in pts]
    c.polygon(col, rot)
    kx, ky = cx + (0 * co - 0.75 * s) * r * 1.4, cy + (0 * s + 0.75 * co) * r * 1.4
    c.ellipse(col, (kx - r * 0.22, ky - r * 0.22, r * 0.44, r * 0.44))


def draw_tiny(c, x, y, r, mix, now):
    """Tiny, Vincent's tuxedo cat, strolling by."""
    black, white = mix((26, 26, 30)), mix((235, 235, 235))
    edge = mix((90, 96, 110))
    step = math.sin(now * 8) * r * 0.15
    c.ellipse(edge, (x - r * 1.25, y - r * 0.65, r * 2.5, r * 1.3))
    c.ellipse(black, (x - r * 1.2, y - r * 0.6, r * 2.4, r * 1.2))
    for k, dx in enumerate((-0.8, -0.4, 0.4, 0.8)):
        c.line(black, (x + dx * r, y + r * 0.3), (x + dx * r + (step if k % 2 else -step), y + r * 0.9), max(2, int(r * 0.25)))
    hx, hy = x + r * 1.25, y - r * 0.55
    c.ellipse(edge, (hx - r * 0.65, hy - r * 0.6, r * 1.3, r * 1.2))
    c.ellipse(black, (hx - r * 0.6, hy - r * 0.55, r * 1.2, r * 1.1))
    for side in (-1, 1):
        c.polygon(black, [(hx + side * r * 0.5, hy - r * 0.2), (hx + side * r * 0.45, hy - r * 0.95),
                          (hx + side * r * 0.1, hy - r * 0.45)])
        c.ellipse(mix((206, 228, 92)), (hx + side * r * 0.25 - r * 0.1, hy - r * 0.15, r * 0.2, r * 0.18))
    c.ellipse(white, (hx - r * 0.18, hy + r * 0.15, r * 0.36, r * 0.3))
    c.line(black, (x - r * 1.1, y - r * 0.2), (x - r * 1.6, y - r * 0.9 + step), max(2, int(r * 0.2)))


def draw_station(c, key, cx, cy, r, mix, pranked, now):
    lw = max(2, int(r * 0.08))
    stone = mix((70, 80, 96))
    c.ellipse(mix((24, 32, 36)), (cx - r * 1.1, cy - r * 0.35, r * 2.2, r * 0.7))
    if key == "rain":                    # a tall gauge with marks (and a teacup, if pranked)
        c.rrect(mix((120, 180, 255), 0.35), (cx - r * 0.25, cy - r * 1.3, r * 0.5, r * 1.3), radius=r * 0.1)
        if not pranked:
            c.rrect(mix((120, 180, 255)), (cx - r * 0.22, cy - r * 0.6, r * 0.44, r * 0.58), radius=r * 0.08)
        for k in range(4):
            c.line(stone, (cx - r * 0.25, cy - r * (0.3 + k * 0.25)), (cx - r * 0.05, cy - r * (0.3 + k * 0.25)), 1)
        if pranked:
            tx, ty = cx + r * 0.65, cy - r * 0.25
            c.rrect(mix(FACE), (tx - r * 0.3, ty - r * 0.2, r * 0.6, r * 0.4), radius=r * 0.15)
            c.arc(mix(FACE), (tx + r * 0.2, ty - r * 0.15, r * 0.25, r * 0.25), -1.6, 1.6, lw)
            for k in range(3):
                c.ellipse(mix((120, 180, 255)), (tx - r * 0.2 + k * r * 0.15, ty - r * 0.35, r * 0.12, r * 0.15))
    elif key == "green":                 # a little glass house with tomato plants
        glass = mix((130, 210, 120), 0.35)
        c.polygon(glass, [(cx - r, cy), (cx - r, cy - r * 0.8), (cx, cy - r * 1.35), (cx + r, cy - r * 0.8), (cx + r, cy)])
        c.line(mix((130, 210, 120)), (cx, cy - r * 1.35), (cx, cy), lw)
        for k in (-1, 1):
            tx, ty = cx + k * r * 0.5, cy - r * 0.35
            c.ellipse(mix((235, 90, 90)), (tx - r * 0.18, ty - r * 0.18, r * 0.36, r * 0.36))
            if pranked:
                c.polygon(mix(GOLD), [(tx - r * 0.15, ty - r * 0.15), (tx + r * 0.15, ty - r * 0.15), (tx, ty - r * 0.6)])
                c.ellipse(mix((255, 120, 160)), (tx - r * 0.06, ty - r * 0.68, r * 0.12, r * 0.12))
    elif key == "rod":                   # a pole with a point (and a balloon, if pranked)
        c.line(stone, (cx, cy), (cx, cy - r * 1.3), lw)
        c.polygon(mix((255, 214, 90)), [(cx - r * 0.12, cy - r * 1.3), (cx + r * 0.12, cy - r * 1.3), (cx, cy - r * 1.6)])
        if pranked:
            bx, by = cx + r * 0.6 + math.sin(now * 1.5) * r * 0.08, cy - r * 1.75
            c.line(mix(SOFT), (cx, cy - r * 1.1), (bx, by + r * 0.3), 1)
            c.ellipse(mix((255, 120, 160)), (bx - r * 0.28, by - r * 0.35, r * 0.56, r * 0.66))
    elif key == "clock":                 # a tower with a clock face (smiling, if pranked)
        c.rrect(stone, (cx - r * 0.45, cy - r * 1.4, r * 0.9, r * 1.4), radius=r * 0.1)
        fx, fy, fr = cx, cy - r * 1.0, r * 0.33
        c.ellipse(mix(FACE), (fx - fr, fy - fr, 2 * fr, 2 * fr))
        if pranked:
            c.ellipse(mix(BG), (fx - fr * 0.45, fy - fr * 0.35, fr * 0.22, fr * 0.22))
            c.ellipse(mix(BG), (fx + fr * 0.25, fy - fr * 0.35, fr * 0.22, fr * 0.22))
            c.arc(mix(BG), (fx - fr * 0.5, fy - fr * 0.3, fr, fr * 0.8), math.pi * 1.15, math.pi * 1.85, max(1, lw // 2))
        else:
            c.line(mix(BG), (fx, fy), (fx, fy - fr * 0.7), max(1, lw // 2))
            c.line(mix(BG), (fx, fy), (fx + fr * 0.5, fy), max(1, lw // 2))
    elif key == "mail":                  # Chatty's mailbox (the message door) with an antenna
        c.line(stone, (cx, cy), (cx, cy - r * 0.6), lw)
        c.rrect(mix((130, 220, 200), 0.7), (cx - r * 0.5, cy - r * 1.05, r * 1.0, r * 0.5), radius=r * 0.2)
        c.line(mix(SOFT), (cx + r * 0.35, cy - r * 1.05), (cx + r * 0.35, cy - r * 1.5), 1)
        c.ellipse(mix(GOLD), (cx + r * 0.29, cy - r * 1.58, r * 0.12, r * 0.12))
        if pranked:
            fx, fy = cx - r * 0.2, cy - r * 1.25
            for k in range(5):
                a = k * 2 * math.pi / 5
                c.ellipse(mix((255, 150, 190)), (fx + math.cos(a) * r * 0.14 - r * 0.1, fy + math.sin(a) * r * 0.14 - r * 0.1,
                                                 r * 0.2, r * 0.2))
            c.ellipse(mix(GOLD), (fx - r * 0.07, fy - r * 0.07, r * 0.14, r * 0.14))
    if pranked:                          # a twinkle where a prank happened
        s = r * 0.18 * (0.7 + 0.3 * math.sin(now * 5))
        sx, sy = cx - r * 0.9, cy - r * 1.2
        c.polygon(mix(GOLD), [(sx, sy - s), (sx + s * 0.3, sy), (sx, sy + s), (sx - s * 0.3, sy)])
        c.polygon(mix(GOLD), [(sx - s, sy), (sx, sy - s * 0.3), (sx + s, sy), (sx, sy + s * 0.3)])

"""
Chatty's face: expressions and animation, independent of the screen library.

FaceModel.update() advances the animation; FaceModel.draw(canvas) draws one
frame using a small canvas interface (see chatty_face.py for the pygame one).
Keeping this separate lets the same face be previewed without pygame.
"""
from __future__ import annotations

import math
import random
import time

try:
    import dreams
    import games
    import nodes
    import pondering
except ImportError:  # running from another folder
    from . import dreams, games, nodes, pondering  # type: ignore
import os

# colors per state (eye/mouth color)
PALETTE = {
    "idle":      (225, 240, 236),
    "listening": (77, 217, 240),
    "thinking":  (180, 140, 255),
    "speaking":  (255, 200, 87),
    "puzzled":   (255, 159, 67),
    "sleepy":    (92, 124, 186),
    "resting":   (40, 52, 78),    # put to bed: dim and calm
    "mischief":      (255, 84, 140),  # cheeky hot pink
    "mischief_talk": (255, 84, 140),
    "love":          (255, 128, 178),  # soft valentine pink
    "love_talk":     (255, 128, 178),
}
BACKGROUND = (8, 10, 14)

# per-state expression targets
#   open: eye openness (1 = fully open), size: eye scale,
#   gaze: (x, y) where eyes look, -1..1, mouth: shape name
EXPRESSIONS = {
    "idle":      dict(open=1.0, size=1.0, gaze=(0.0, 0.0), mouth="smile"),
    "listening": dict(open=1.08, size=1.06, gaze=(0.0, -0.05), mouth="small_o"),
    "thinking":  dict(open=0.82, size=1.0, gaze=(0.55, -0.6), mouth="flat"),
    "speaking":  dict(open=1.0, size=1.0, gaze=(0.0, 0.0), mouth="talk"),
    "puzzled":   dict(open=1.0, size=1.0, gaze=(-0.3, -0.2), mouth="tilt"),
    "sleepy":    dict(open=0.07, size=1.0, gaze=(0.0, 0.25), mouth="small_smile"),
    "resting":   dict(open=0.05, size=0.95, gaze=(0.0, 0.3), mouth="small_smile"),
    # sly sideways look, half-lidded eyes, lopsided smirk (and the odd wink)
    "mischief":      dict(open=0.55, size=1.0, gaze=(0.55, 0.1), mouth="smirk"),
    "mischief_talk": dict(open=0.6, size=1.0, gaze=(0.35, 0.05), mouth="talk"),
    # happy closed eyes (^ ^), rosy cheeks, a kiss, and little hearts floating up
    "love":          dict(open=1.0, size=1.0, gaze=(0.0, 0.0), mouth="kiss"),
    "love_talk":     dict(open=1.0, size=1.0, gaze=(0.0, 0.0), mouth="talk"),
}
LOVE_STATES = ("love", "love_talk")

IDLE_TO_SLEEPY_SECONDS = 600  # (night) doze off after 10 quiet minutes
# She's less sleepy during the day: plays instead of dozing.
SLEEPY_AFTER_DAY = float(os.getenv("CHATTY_SLEEPY_AFTER_DAY", "1800"))      # 8am-10pm
SLEEPY_AFTER_NIGHT = float(os.getenv("CHATTY_SLEEPY_AFTER_NIGHT", str(IDLE_TO_SLEEPY_SECONDS)))
GAMES = os.getenv("CHATTY_GAMES", "1") != "0"
BORED_AFTER = float(os.getenv("CHATTY_BORED_AFTER", "180"))  # idle this long -> plays a game
# Pondering: now and then she wonders about another node (greenhouse, rain) and asks it.
CURIOUS = os.getenv("CHATTY_CURIOSITY", "1") != "0"
PONDER_EVERY = float(os.getenv("CHATTY_PONDER_EVERY", "1500"))   # ~25 min (randomized)
# Say worrying readings out loud (dry soil, very hot), daytime only, at most every few hours.
PONDER_SPEAK = os.getenv("CHATTY_PONDER_SPEAK", "1") != "0"
SPEAK_GAP = float(os.getenv("CHATTY_PONDER_SPEAK_GAP", str(3 * 3600)))


def sleepy_after(t: float) -> float:
    hour = time.localtime(t).tm_hour
    return SLEEPY_AFTER_DAY if 8 <= hour < 22 else SLEEPY_AFTER_NIGHT

# Status line at the bottom of the screen (plain ASCII: the Pi's default font is basic)
STATUS = {
    "idle":          ("Say \"Hey Chatty\" or tap me", False),
    "listening":     ("Listening", True),     # True = animated dots
    "thinking":      ("Thinking", True),
    "speaking":      ("Speaking", False),
    "mischief_talk": ("Speaking", False),
    "mischief":      ("", False),
    "love_talk":     ("Speaking", False),
    "love":          ("", False),
    "puzzled":       ("Hmm...", False),
    "sleepy":        ("Dozing - tap to wake", False),
    "resting":       ("Resting - tap to wake", False),
}
CAPTION_COLOR = (210, 220, 228)

# Recording indicator (top-left), shown only while Chatty is awake:
#   "full"    red pulsing dot + REC: the conversation's words are being logged
#   "private" grey PRIVATE: privacy mode, nothing is being saved
#   "stats"   grey STATS ONLY: timing/statistics logged, no words
#   "off"     nothing (logging disabled)
REC_RED = (235, 64, 64)
QUIET_STATES = ("idle", "sleepy", "resting")

# Blush and hearts
BLUSH = (255, 92, 140)
HEART = (255, 70, 120)
HEART_EVERY = 0.7          # a new heart this often (seconds) in the love face
HEART_LIFE = 2.6           # how long each heart floats before it fades away

# Spooky mode: only on Halloween and Friday the 13th (CHATTY_FORCE_SPOOKY=1 to test).
# The cheeky face turns into a glowing red "evil robot" glare, just for fun.
SPOOKY_COLOR = (255, 48, 24)


def is_spooky_day(t: float | None = None) -> bool:
    import os
    if os.getenv("CHATTY_FORCE_SPOOKY") == "1":
        return True
    d = time.localtime(t or time.time())
    return (d.tm_mon == 10 and d.tm_mday == 31) or (d.tm_mday == 13 and d.tm_wday == 4)


def is_valentines_day(t: float | None = None) -> bool:
    """February 14th (or CHATTY_FORCE_VALENTINE=1 to test): a rosy idle face."""
    import os
    if os.getenv("CHATTY_FORCE_VALENTINE") == "1":
        return True
    d = time.localtime(t or time.time())
    return d.tm_mon == 2 and d.tm_mday == 14


def heart_points(cx: float, cy: float, size: float, n: int = 36):
    """Outline of a heart centered at (cx, cy), about `size` pixels wide."""
    k = size / 34.0
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * k, cy - y * k))
    return pts


def _lerp(a, b, t):
    return a + (b - a) * t


def _lerp_color(c1, c2, t):
    return tuple(int(_lerp(a, b, t)) for a, b in zip(c1, c2))


class FaceModel:
    def __init__(self, width: int, height: int, rng: random.Random | None = None):
        self.w, self.h = width, height
        self.rng = rng or random.Random()
        self.state = "idle"
        self.last_activity = time.time()

        exp = EXPRESSIONS["idle"]
        self.color = PALETTE["idle"]
        self.open = exp["open"]
        self.size = exp["size"]
        self.gaze = list(exp["gaze"])
        self.level = 0.0          # mouth openness while talking, 0..1
        self.target_level = 0.0
        self.caption = ""         # what Chatty heard (shown at the top)
        self.rec_mode = "off"     # recording indicator, see REC_RED above
        self.dream_mix = 0.0      # 0 = face, 0.5 = blank, 1 = dream cloud
        self.game = None          # tic-tac-toe in progress, if any
        self.next_game_at = 0.0
        self.ponder = None        # wondering about / asking another node, if any
        self.next_ponder_at = time.time() + self.rng.uniform(300, 600)
        self.ponder_turn = 0      # which node she wonders about next
        self.last_spoken = {}     # node -> when she last said something about it
        self.outbox = []          # messages for the voice node ("notify:...")
        self.asleep_since = 0.0
        self._was_asleep = False
        self.dream_item = None
        self.dream_started = 0.0
        self.listen_until = 0.0   # listening timer bar
        self.listen_total = 0.0
        self.love_since = 0.0     # when the love face started (hearts float from then)

        self.blink = 0.0          # 0 = no blink, 1 = fully closed
        self.next_blink = time.time() + self.rng.uniform(2, 5)
        self.blink_started = 0.0

        self.wink = 0.0           # 0 = open, 1 = left eye fully winked
        self.next_wink = 0.0
        self.drift = [0.0, 0.0]   # idle eye wandering
        self.next_drift = time.time() + self.rng.uniform(2, 4)
        self.drift_target = [0.0, 0.0]

    # ----- inputs -----
    def set_state(self, state: str, now: float | None = None):
        if state not in EXPRESSIONS:
            return
        now = now or time.time()
        if state in LOVE_STATES and self.state not in LOVE_STATES:
            self.love_since = now
        self.state = state
        self.last_activity = now
        if state != "idle" and self.game:
            self.game = None          # a real conversation takes priority over playing
        if state != "idle" and self.ponder:
            self.ponder = None        # ...and over pondering
        if state != "speaking":
            self.target_level = 0.0
        if state != "listening":
            self.listen_until = 0.0
        if state in ("idle", "sleepy", "resting"):
            self.caption = ""

    def set_rec(self, mode: str):
        self.rec_mode = mode if mode in ("full", "private", "stats", "off") else "off"

    # ----- games -----
    def start_game(self, human: bool, now: float | None = None):
        if not GAMES:
            return
        now = now or time.time()
        if self.state != "idle":
            self.set_state("idle", now)
        self.game = games.TicTacToe(human, self.rng, now)

    # ----- pondering -----
    def start_ponder(self, node: str | None = None, now: float | None = None) -> bool:
        now = now or time.time()
        names = nodes.enabled()
        if node not in names:
            if not names:
                return False
            node = names[self.ponder_turn % len(names)]
            self.ponder_turn += 1
        if self.state != "idle":
            self.set_state("idle", now)
        self.game = None
        self.ponder = pondering.Ponder(node, self.rng, now)
        return True

    def _finish_ponder(self, now: float):
        r = self.ponder.reading
        self.ponder = None
        self.next_ponder_at = now + PONDER_EVERY * self.rng.uniform(0.7, 1.3)
        self.next_game_at = max(self.next_game_at, now + 60)
        if not (r and r.ok and r.spoken and PONDER_SPEAK):
            return
        hour = time.localtime(now).tm_hour
        if 9 <= hour < 21 and now - self.last_spoken.get(r.node, 0) > SPEAK_GAP:
            self.last_spoken[r.node] = now
            self.outbox.append("notify:" + r.spoken)

    def handle_tap(self, pos, now: float | None = None) -> bool:
        """A tap on the screen. True if the game used it (so it shouldn't wake the voice)."""
        now = now or time.time()
        if self.game and self.state == "idle":
            cell = self.game.cell_at(self.w, self.h, pos)
            if cell is not None:
                self.game.tap(cell, now)
                self.last_activity = now
                return True
        return False

    def set_caption(self, text: str):
        self.caption = (text or "").strip()

    def set_listen(self, seconds: float, now: float | None = None):
        """Show a shrinking bar: how long Chatty will keep listening."""
        now = now or time.time()
        self.listen_total = max(0.1, seconds)
        self.listen_until = now + seconds

    def set_level(self, level: float):
        self.target_level = max(0.0, min(1.0, level))

    # ----- animation -----
    def busy(self) -> bool:
        """True when something is moving and the screen needs a high frame rate."""
        now = time.time()
        asleep = self.state in ("sleepy", "resting")
        if self.ponder and self.state == "idle":
            return True   # thought bubble and signal waves are animated
        return (self.state in ("speaking", "listening", "thinking", "mischief", "mischief_talk", "puzzled",
                                "love", "love_talk")
                or (not asleep and (self.blink > 0 or self.next_blink - now < 0.3))  # smooth blinks
                or (self.state == "resting" and self.open > 0.08)  # still closing its eyes
                or abs(self.level - self.target_level) > 0.01)

    def update(self, dt: float, now: float | None = None):
        now = now or time.time()

        # bored? wonder about the other nodes, or play a game (she'd rather do that than doze)
        if self.ponder:
            self.ponder.update(now)
            if self.ponder.done:
                self._finish_ponder(now)
        elif self.game:
            self.game.update(now)
            if self.game.done:
                human = self.game.human
                self.game = None
                if human:
                    self.last_activity = now        # you just played with her
                elif self.rng.random() < 0.4:
                    self.game = games.TicTacToe(False, self.rng, now)   # one more!
                self.next_game_at = now + self.rng.uniform(120, 300)
        elif (self.state == "idle" and now - self.last_activity > BORED_AFTER
              and now - self.last_activity < sleepy_after(now)):
            if CURIOUS and now >= self.next_ponder_at and nodes.enabled():
                self.start_ponder(now=now)
            elif GAMES and now >= self.next_game_at:
                self.game = games.TicTacToe(False, self.rng, now)

        if (self.state == "idle" and not self.game and not self.ponder
                and now - self.last_activity > sleepy_after(now)):
            self.state = "sleepy"

        # dreams: a while after falling asleep, the face fades into a dream cloud
        asleep = self.state in ("sleepy", "resting")
        if asleep and not self._was_asleep:
            self.asleep_since = now
        self._was_asleep = asleep
        if not asleep:
            self.dream_mix, self.dream_item = 0.0, None   # wake up instantly
        elif dreams.ENABLED and now - self.asleep_since > dreams.DELAY:
            self.dream_mix = min(1.0, self.dream_mix + dt / 4.0)  # ~2 s face out, ~2 s dream in
            if self.dream_mix >= 0.5 and (self.dream_item is None or
                                          now - self.dream_started > dreams.ITEM_SECONDS):
                self.dream_item = dreams.pick(self.rng, self.dream_item)
                self.dream_started = now

        exp = dict(EXPRESSIONS[self.state])
        target_color = PALETTE[self.state]
        if self.state in ("mischief", "mischief_talk") and is_spooky_day(now):
            target_color = SPOOKY_COLOR
            exp["open"] = 0.38          # narrow, glowing glare
            exp["gaze"] = (0.0, 0.0)    # staring right at you
        # falling asleep is slow and gentle (~2 s); everything else is quick
        ease = min(1.0, dt * (1.2 if self.state == "resting" else 8))
        self.color = _lerp_color(self.color, target_color, ease)
        self.open = _lerp(self.open, exp["open"], ease)
        self.size = _lerp(self.size, exp["size"], ease)

        # wandering gaze when idle; slow circling while thinking
        if self.state == "idle":
            if now > self.next_drift:
                self.drift_target = [self.rng.uniform(-0.5, 0.5), self.rng.uniform(-0.25, 0.25)]
                if self.rng.random() < 0.4:
                    self.drift_target = [0.0, 0.0]
                self.next_drift = now + self.rng.uniform(1.5, 4.5)
        elif self.state == "thinking":
            a = now * 1.6
            self.drift_target = [0.18 * math.cos(a), 0.12 * math.sin(a)]
        else:
            self.drift_target = [0.0, 0.0]
        for i in range(2):
            self.drift[i] = _lerp(self.drift[i], self.drift_target[i], min(1.0, dt * 6))
            self.gaze[i] = _lerp(self.gaze[i], exp["gaze"][i], ease)

        # cheeky wink: a quick left-eye wink every few seconds
        if self.state in ("mischief", "mischief_talk"):
            if self.next_wink == 0.0:
                self.next_wink = now + 0.6
            t = (now - self.next_wink) / 0.45
            if 0 <= t < 1:
                self.wink = math.sin(t * math.pi)
            elif t >= 1:
                self.wink = 0.0
                self.next_wink = now + self.rng.uniform(2.5, 4.5)
        else:
            self.wink = 0.0
            self.next_wink = 0.0

        # blinking (not while asleep, and not with happy closed eyes)
        if self.state not in ("sleepy", "resting") + LOVE_STATES:
            if self.blink_started == 0.0 and now > self.next_blink:
                self.blink_started = now
            if self.blink_started:
                t = (now - self.blink_started) / 0.16  # 160 ms blink
                self.blink = 1 - abs(1 - 2 * t) if t < 1 else 0.0
                if t >= 1:
                    self.blink_started = 0.0
                    gap = self.rng.uniform(2.5, 6.0)
                    if self.rng.random() < 0.15:
                        gap = 0.25  # occasional double blink
                    self.next_blink = now + gap
        else:
            self.blink = 0.0

        # mouth follows the voice: open fast, close a bit slower
        rate = 25 if self.target_level > self.level else 12
        self.level = _lerp(self.level, self.target_level, min(1.0, dt * rate))

    # ----- drawing -----
    def draw(self, c, now: float | None = None):
        now = now or time.time()
        w, h = self.w, self.h
        c.fill(BACKGROUND)

        if self.ponder and self.state == "idle":
            self.ponder.draw(c, w, h, now)
            self._status(c, now)
            return
        if self.game and self.state == "idle":
            self.game.draw(c, w, h, now)
            self._status(c, now)
            return

        if self.dream_mix > 0:
            if self.dream_mix >= 0.5:
                self._draw_dream(c, now)
                self._status(c, now)
                return
            # first half of the transition: the sleeping face fades out
            saved = self.color
            self.color = _lerp_color(BACKGROUND, saved, 1 - 2 * self.dream_mix)
            try:
                self._draw_face(c, now)
            finally:
                self.color = saved
            return
        self._draw_face(c, now)

    def _draw_dream(self, c, now):
        w, h = self.w, self.h
        k = min(1.0, 2 * self.dream_mix - 1)          # cloud fades in
        night = self.state == "resting"
        cloud = _lerp_color(BACKGROUND, (18, 22, 38) if night else (26, 32, 54), k)
        dreams.draw_cloud(c, w, h, now, cloud)
        dreams.draw_sleeper(c, w, h, now, _lerp_color(BACKGROUND, self.color, k), cloud)
        if self.dream_item:
            t = now - self.dream_started
            envelope = max(0.0, min(1.0, t / 2.5, (dreams.ITEM_SECONDS - t) / 2.5))
            dreams.draw_item(c, w, h, now, self.dream_item, self.dream_started,
                             k * envelope, 1.0 if night else 0.0, cloud)

    def _draw_face(self, c, now):
        w, h = self.w, self.h

        bob = math.sin(now * 1.3) * h * 0.006  # gentle "breathing"
        gx = (self.gaze[0] + self.drift[0]) * w * 0.035
        gy = (self.gaze[1] + self.drift[1]) * h * 0.05

        eye_w = w * 0.14 * self.size
        eye_h = h * 0.34 * self.size
        cy = h * 0.42 + bob + gy
        openness = max(0.04, self.open * (1 - self.blink))

        love = self.state in LOVE_STATES
        valentine = self.state == "idle" and is_valentines_day(now)
        if love or valentine:
            self._blush(c, cy, eye_w, eye_h, strong=love)

        for side, cx in (("left", w * 0.34), ("right", w * 0.66)):
            ex = cx + gx
            if love:
                # happy closed eye: an upside-down U, like ^
                aw, ah = eye_w * 1.05, eye_h * 0.5
                c.arc(self.color, (ex - aw / 2, cy - ah * 0.2, aw, ah), math.pi * 0.06, math.pi * 0.94,
                      max(7, int(h * 0.032)))
                continue
            this_open = openness
            if self.state == "puzzled" and side == "right":
                this_open *= 0.55
            if side == "left" and self.wink > 0:
                this_open *= max(0.06, 1 - self.wink)
            eh = max(eye_h * this_open, h * 0.018)
            rect = (ex - eye_w / 2, cy - eh / 2, eye_w, eh)
            c.rrect(self.color, rect, radius=min(eye_w, eh) * 0.45)
            # small highlight makes the eyes feel alive
            if eh > eye_h * 0.4:
                r = eye_w * 0.11
                hx, hy = ex - eye_w * 0.2, cy - eh * 0.28
                c.ellipse(_lerp_color(self.color, (255, 255, 255), 0.75),
                          (hx - r, hy - r, 2 * r, 2 * r))

        # puzzled: raised brow over the squinting eye
        if self.state == "puzzled":
            bx = w * 0.66 + gx
            by = cy - eye_h * 0.47
            c.line(self.color, (bx - eye_w * 0.6, by + h * 0.02), (bx + eye_w * 0.6, by - h * 0.03), 8)

        # mischief: left brow dips toward the middle, right brow arches up
        if self.state in ("mischief", "mischief_talk"):
            lx, rx = w * 0.34 + gx, w * 0.66 + gx
            by = cy - eye_h * 0.33
            c.line(self.color, (lx - eye_w * 0.55, by - h * 0.035), (lx + eye_w * 0.55, by + h * 0.015), 8)
            c.line(self.color, (rx - eye_w * 0.55, by - h * 0.02), (rx + eye_w * 0.55, by - h * 0.06), 8)

        self._mouth(c, cx=w / 2 + gx * 0.5, cy=h * 0.76 + bob)
        if love:
            self._hearts(c, now, mouth=(w / 2 + gx * 0.5, h * 0.76 + bob))

        self._status(c, now)

        if self.state in ("sleepy", "resting"):
            for i, size in enumerate((20, 28, 36)):
                t = (now * 0.5 + i * 0.33) % 1.0
                x = w * 0.74 + i * w * 0.035 + t * w * 0.02
                y = h * 0.22 - i * h * 0.07 - t * h * 0.04
                c.text("z", (x, y), int(size * h / 480), _lerp_color(BACKGROUND, self.color, 1 - t))

    def _blush(self, c, cy, eye_w, eye_h, strong: bool):
        """Rosy cheeks just below and outside each eye."""
        w, h = self.w, self.h
        amount = 0.6 if strong else 0.3
        col = _lerp_color(BACKGROUND, BLUSH, amount)
        bw, bh = eye_w * 0.95, h * 0.07
        if strong:
            by = cy + eye_h * 0.36                              # under the closed ^ ^ eyes
        else:
            by = cy + eye_h * self.size * self.open * 0.5 + h * 0.06   # just below open eyes
        for cx in (w * 0.34 - eye_w * 0.55, w * 0.66 + eye_w * 0.55):
            c.ellipse(col, (cx - bw / 2, by - bh / 2, bw, bh))

    def _hearts(self, c, now, mouth):
        """Little hearts drift up and to the right from the kiss, then fade."""
        w, h = self.w, self.h
        t0 = self.love_since or now
        newest = int((now - t0) / HEART_EVERY)
        for i in range(max(0, newest - 4), newest + 1):
            age = now - t0 - i * HEART_EVERY
            if age < 0 or age > HEART_LIFE:
                continue
            k = age / HEART_LIFE
            sway = math.sin(age * 3.0 + i) * w * 0.012
            x = mouth[0] + w * 0.1 + k * w * 0.32 + sway + (i % 3) * w * 0.015
            y = mouth[1] - h * 0.03 - k * h * 0.42
            grow = min(1.0, age / 0.35)                      # pop in
            fade = 1.0 - max(0.0, (k - 0.6) / 0.4)           # fade out near the end
            size = w * (0.035 + 0.012 * (i % 2)) * grow
            c.polygon(_lerp_color(BACKGROUND, HEART, fade), heart_points(x, y, size))

    def _status(self, c, now):
        """Status line + listening timer at the bottom, caption at the top."""
        w, h = self.w, self.h
        label, dots = STATUS.get(self.state, ("", False))
        if self.dream_mix >= 0.5:
            label = "Dreaming - tap to wake"
        elif self.ponder and self.state == "idle":
            label = self.ponder.status()
            dots = self.ponder.phase in ("wonder", "asking")
        elif self.game and self.state == "idle":
            g = self.game
            if g.human and not g.result:
                label = "Your turn - tap a square" if g.turn == "X" else "Chatty is thinking"
            else:
                label = "Playing tic-tac-toe - tap a square to join" if not g.human else "Good game!"
        size = max(14, int(h * 0.055))
        if label:
            if dots:
                label += "." * (int(now * 2.5) % 4)
                width = c.measure(label.rstrip(".") + "...", size)  # keep it from jiggling
            else:
                width = c.measure(label, size)
            quiet = self.state in ("idle", "sleepy", "resting")
            color = (112, 122, 138) if quiet else self.color  # soft grey when nothing's happening
            c.text(label, ((w - width) / 2, h * 0.895), size, color)

        # listening timer: a bar that shrinks as time runs out
        if self.state == "listening" and self.listen_until:
            frac = max(0.0, min(1.0, (self.listen_until - now) / self.listen_total))
            bw, bh = w * 0.5, max(4, h * 0.012)
            x0, y0 = (w - bw) / 2, h * 0.965
            c.rrect(_lerp_color(BACKGROUND, self.color, 0.25), (x0, y0, bw, bh), radius=bh / 2)
            if frac > 0:
                c.rrect(self.color, (x0, y0, bw * frac, bh), radius=bh / 2)

        # recording indicator, top-left, only while awake
        if self.state not in QUIET_STATES and self.rec_mode != "off":
            size = max(14, int(h * 0.05))
            x, y = w * 0.025, h * 0.035
            if self.rec_mode == "full":
                pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(now * 4))
                r = size * 0.32
                c.ellipse(_lerp_color(BACKGROUND, REC_RED, pulse),
                          (x, y + size * 0.36 - r, 2 * r, 2 * r))
                c.text("REC", (x + 2 * r + size * 0.3, y), size, REC_RED)
            else:
                label = "PRIVATE" if self.rec_mode == "private" else "STATS ONLY"
                c.text(label, (x, y), size, (112, 122, 138))

        # caption: the words Chatty heard (kept clear of the corner indicator)
        if self.caption:
            csize = max(14, int(h * 0.05))
            text = '"' + self.caption + '"'
            while c.measure(text, csize) > w * 0.70 and len(text) > 8:
                text = '"...' + text[5:]  # keep the newest words visible
            c.text(text, ((w - c.measure(text, csize)) / 2, h * 0.035), csize, CAPTION_COLOR)

    def _mouth(self, c, cx, cy):
        w, h = self.w, self.h
        col = self.color
        shape = EXPRESSIONS[self.state]["mouth"]
        thick = max(4, int(h * 0.016))
        if shape == "talk":
            mw = w * (0.07 + 0.06 * self.level)
            mh = h * (0.025 + 0.17 * self.level)
            c.rrect(col, (cx - mw / 2, cy - mh / 2, mw, mh), radius=min(mw, mh) * 0.5)
        elif shape == "small_o":
            r = h * 0.035
            c.ellipse(col, (cx - r, cy - r, 2 * r, 2 * r), width=thick)
        elif shape == "flat":
            c.line(col, (cx - w * 0.045, cy), (cx + w * 0.045, cy), thick)
        elif shape == "tilt":
            c.line(col, (cx - w * 0.05, cy + h * 0.015), (cx + w * 0.05, cy - h * 0.02), thick)
        elif shape == "smirk":
            # flat on the left, curling up on the right
            p1 = (cx - w * 0.06, cy + h * 0.005)
            p2 = (cx + w * 0.025, cy + h * 0.012)
            p3 = (cx + w * 0.07, cy - h * 0.035)
            c.line(col, p1, p2, thick)
            c.line(col, p2, p3, thick)
        elif shape == "kiss":
            # puckered lips: a little sideways "3", leaning toward the hearts
            r = h * 0.04
            x0 = cx - r * 0.4
            for dy in (-r, r):
                c.arc(col, (x0 - r, cy + dy - r, 2 * r, 2 * r), -math.pi * 0.5, math.pi * 0.5, thick)
        elif shape == "small_smile":
            c.arc(col, (cx - w * 0.035, cy - h * 0.05, w * 0.07, h * 0.06), math.pi * 1.15, math.pi * 1.85, thick)
        else:  # smile
            c.arc(col, (cx - w * 0.07, cy - h * 0.1, w * 0.14, h * 0.12), math.pi * 1.1, math.pi * 1.9, thick)

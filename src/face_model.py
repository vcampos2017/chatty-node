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
}

IDLE_TO_SLEEPY_SECONDS = 600  # doze off after 10 quiet minutes

# Status line at the bottom of the screen (plain ASCII: the Pi's default font is basic)
STATUS = {
    "idle":          ("Say \"Hey Chatty\" or tap me", False),
    "listening":     ("Listening", True),     # True = animated dots
    "thinking":      ("Thinking", True),
    "speaking":      ("Speaking", False),
    "mischief_talk": ("Speaking", False),
    "mischief":      ("", False),
    "puzzled":       ("Hmm...", False),
    "sleepy":        ("Dozing - tap to wake", False),
    "resting":       ("Resting - tap to wake", False),
}
CAPTION_COLOR = (210, 220, 228)

# Spooky mode: only on Halloween and Friday the 13th (CHATTY_FORCE_SPOOKY=1 to test).
# The cheeky face turns into a glowing red "evil robot" glare, just for fun.
SPOOKY_COLOR = (255, 48, 24)


def is_spooky_day(t: float | None = None) -> bool:
    import os
    if os.getenv("CHATTY_FORCE_SPOOKY") == "1":
        return True
    d = time.localtime(t or time.time())
    return (d.tm_mon == 10 and d.tm_mday == 31) or (d.tm_mday == 13 and d.tm_wday == 4)


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
        self.listen_until = 0.0   # listening timer bar
        self.listen_total = 0.0

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
        self.state = state
        self.last_activity = now or time.time()
        if state != "speaking":
            self.target_level = 0.0
        if state != "listening":
            self.listen_until = 0.0
        if state in ("idle", "sleepy", "resting"):
            self.caption = ""

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
        return (self.state in ("speaking", "listening", "thinking", "mischief", "mischief_talk", "puzzled")
                or (not asleep and (self.blink > 0 or self.next_blink - now < 0.3))  # smooth blinks
                or (self.state == "resting" and self.open > 0.08)  # still closing its eyes
                or abs(self.level - self.target_level) > 0.01)

    def update(self, dt: float, now: float | None = None):
        now = now or time.time()

        if self.state == "idle" and now - self.last_activity > IDLE_TO_SLEEPY_SECONDS:
            self.state = "sleepy"

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

        # blinking (not while asleep)
        if self.state not in ("sleepy", "resting"):
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

        bob = math.sin(now * 1.3) * h * 0.006  # gentle "breathing"
        gx = (self.gaze[0] + self.drift[0]) * w * 0.035
        gy = (self.gaze[1] + self.drift[1]) * h * 0.05

        eye_w = w * 0.14 * self.size
        eye_h = h * 0.34 * self.size
        cy = h * 0.42 + bob + gy
        openness = max(0.04, self.open * (1 - self.blink))

        for side, cx in (("left", w * 0.34), ("right", w * 0.66)):
            ex = cx + gx
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

        self._status(c, now)

        if self.state in ("sleepy", "resting"):
            for i, size in enumerate((20, 28, 36)):
                t = (now * 0.5 + i * 0.33) % 1.0
                x = w * 0.74 + i * w * 0.035 + t * w * 0.02
                y = h * 0.22 - i * h * 0.07 - t * h * 0.04
                c.text("z", (x, y), int(size * h / 480), _lerp_color(BACKGROUND, self.color, 1 - t))

    def _status(self, c, now):
        """Status line + listening timer at the bottom, caption at the top."""
        w, h = self.w, self.h
        label, dots = STATUS.get(self.state, ("", False))
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

        # caption: the words Chatty heard
        if self.caption:
            csize = max(14, int(h * 0.05))
            text = '"' + self.caption + '"'
            while c.measure(text, csize) > w * 0.92 and len(text) > 8:
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
        elif shape == "small_smile":
            c.arc(col, (cx - w * 0.035, cy - h * 0.05, w * 0.07, h * 0.06), math.pi * 1.15, math.pi * 1.85, thick)
        else:  # smile
            c.arc(col, (cx - w * 0.07, cy - h * 0.1, w * 0.14, h * 0.12), math.pi * 1.1, math.pi * 1.9, thick)

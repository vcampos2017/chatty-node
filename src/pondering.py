"""
Pondering: now and then, when Chatty is idle, she wonders about one of the other
nodes, asks it, and shows what she learned.

    1. wonder  - she looks up, thinking: "What's the soil moisture in the greenhouse?"
    2. asking  - little signal waves go out while she asks the node (in the background,
                 so the face never freezes; nodes are read-only, see nodes.py)
    3. answer  - a card with the reading and her reaction ("Nice and damp. Happy plants.")
                 or, if nobody answers, "Maybe the greenhouse is napping."

If something is worrying (very dry soil, very hot), she can also say it out loud once
(see face_model: CHATTY_PONDER_SPEAK).

Drawing uses the same small canvas interface as face_model.
"""
from __future__ import annotations

import math
import random
import threading
from typing import Callable, Optional

try:
    import dreams
    import nodes
except ImportError:  # running from another folder
    from . import dreams, nodes  # type: ignore

WONDER_SECONDS = 4.5
MIN_ASK_SECONDS = 2.5      # show the "asking" waves at least this long
ASK_TIMEOUT = 12.0         # give up waiting after this long
ANSWER_SECONDS = 9.0
OFFLINE_SECONDS = 6.0

BG = (8, 10, 14)
BUBBLE = (26, 32, 54)
TEXT = (210, 220, 228)
SOFT = (150, 160, 180)
THINK = (180, 140, 255)
FACE = (225, 240, 236)
WORRY = (255, 159, 67)
SKY = (130, 200, 255)
MINT = dreams.MINT
GOLD = dreams.GOLD


class Ponder:
    def __init__(self, node: str, rng: random.Random, now: float,
                 reader: Optional[Callable[[str], "nodes.Reading"]] = None):
        self.node = node
        self.info = nodes.NODES[node]
        self.rng = rng
        self.reader = reader or nodes.read
        self.question = rng.choice(self.info["questions"])
        self.phase = "wonder"
        self.phase_started = now
        self.started = now
        self.reading: Optional[nodes.Reading] = None
        self._result: Optional[nodes.Reading] = None
        self._thread: Optional[threading.Thread] = None
        self.done = False

    # ----- running -----
    def _ask(self):
        self._result = self.reader(self.node)

    def update(self, now: float):
        t = now - self.phase_started
        if self.phase == "wonder" and t >= WONDER_SECONDS:
            self.phase, self.phase_started = "asking", now
            self._thread = threading.Thread(target=self._ask, daemon=True)
            self._thread.start()
        elif self.phase == "asking":
            if self._result is not None and t >= MIN_ASK_SECONDS:
                self.reading = self._result
                self.phase, self.phase_started = "answer", now
            elif t >= ASK_TIMEOUT:
                self.reading = nodes.Reading(self.node, False, mood="puzzled",
                                             comment="No answer. Maybe it's napping.")
                self.phase, self.phase_started = "answer", now
        elif self.phase == "answer":
            hold = ANSWER_SECONDS if self.reading and self.reading.ok else OFFLINE_SECONDS
            if t >= hold:
                self.done = True

    @property
    def mood(self) -> str:
        if self.phase != "answer" or not self.reading:
            return "wonder"
        return self.reading.mood

    def status(self) -> str:
        if self.phase == "wonder":
            return "Wondering"
        if self.phase == "asking":
            return self.info["asking"].rstrip(".")
        r = self.reading
        if r and r.ok:
            return f"{self.info['title']}: {r.big} {r.label}"
        return f"{self.info['title']} is offline"

    # ----- drawing -----
    def draw(self, c, w, h, now, fade: float = 1.0):
        mix = lambda col, k=1.0: dreams._mix(BG, col, fade * k)
        t = now - self.phase_started
        intro = min(1.0, (now - self.started) / 0.8)
        self._draw_face(c, w, h, now, mix, intro)

        # thought bubble: little circles rising to a big rounded bubble
        bx, by, bw, bh = w * 0.43, h * 0.08, w * 0.53, h * 0.70
        bob = math.sin(now * 0.9) * h * 0.006
        fill = mix(BUBBLE, intro)
        for i, (px, py, pr) in enumerate(((0.34, 0.33, 0.013), (0.375, 0.27, 0.02), (0.415, 0.215, 0.028))):
            rr = h * pr * (1 + 0.1 * math.sin(now * 1.6 + i))
            c.ellipse(fill, (w * px - rr, h * py - rr + bob, 2 * rr, 2 * rr))
        c.rrect(fill, (bx, by + bob, bw, bh), radius=h * 0.09)
        cx, top = bx + bw / 2, by + bob

        if self.phase == "wonder":
            self._draw_wonder(c, cx, top, bw, bh, h, now, mix, t)
        elif self.phase == "asking":
            self._draw_asking(c, cx, top, bw, bh, h, now, mix, t)
        else:
            self._draw_answer(c, cx, top, bw, bh, h, now, mix, t)

    def _draw_face(self, c, w, h, now, mix, k):
        """Chatty, smaller and to the left, looking up at her thought."""
        mood = self.mood
        col = mix(WORRY if mood == "worried" else (THINK if mood == "wonder" else FACE), k)
        fx, fy = w * 0.21, h * 0.50 + math.sin(now * 1.3) * h * 0.006
        ew, eh = w * 0.075, h * 0.20
        look_x = w * 0.018 if mood == "wonder" else 0
        look_y = -h * 0.035 if mood == "wonder" else 0
        if mood == "wonder":  # eyes circle a little while she thinks
            look_x += math.cos(now * 1.6) * w * 0.006
            look_y += math.sin(now * 1.6) * h * 0.008
        for side in (-1, 1):
            ex = fx + side * w * 0.065 + look_x
            open_ = 0.8 if mood == "wonder" else 1.0
            if mood == "puzzled" and side > 0:
                open_ = 0.55
            hh = eh * open_
            c.rrect(col, (ex - ew / 2, fy + look_y - hh / 2, ew, hh), radius=min(ew, hh) * 0.45)
            if hh > eh * 0.4:
                r = ew * 0.11
                hx, hy = ex - ew * 0.2, fy + look_y - hh * 0.28
                c.ellipse(dreams._mix(col, (255, 255, 255), 0.6), (hx - r, hy - r, 2 * r, 2 * r))
        if mood == "puzzled":  # raised brow
            bx = fx + w * 0.065 + look_x
            by = fy + look_y - eh * 0.47
            c.line(col, (bx - ew * 0.6, by + h * 0.02), (bx + ew * 0.6, by - h * 0.03), 6)
        my = fy + h * 0.2
        thick = max(4, int(h * 0.014))
        if mood == "wonder":
            c.line(col, (fx - w * 0.03 + look_x * 0.5, my), (fx + w * 0.03 + look_x * 0.5, my), thick)
        elif mood == "puzzled":
            c.line(col, (fx - w * 0.035, my + h * 0.012), (fx + w * 0.035, my - h * 0.015), thick)
        elif mood == "worried":
            c.arc(col, (fx - w * 0.04, my - h * 0.005, w * 0.08, h * 0.07), math.pi * 0.15, math.pi * 0.85, thick)
        else:
            c.arc(col, (fx - w * 0.05, my - h * 0.07, w * 0.1, h * 0.09), math.pi * 1.1, math.pi * 1.9, thick)

    def _icon(self, c, cx, cy, s, mix, now, k=1.0):
        fade = lambda col: mix(col, k)
        if self.info["icon"] == "sprout":
            dreams._sprout(c, cx, cy - s * 0.2, s * 0.8, fade, now, mix(BUBBLE))
        else:  # rain cloud
            cloud = fade(SOFT)
            c.ellipse(cloud, (cx - s * 0.8, cy - s * 0.45, s * 0.9, s * 0.7))
            c.ellipse(cloud, (cx - s * 0.25, cy - s * 0.75, s * 1.0, s * 0.95))
            c.rrect(cloud, (cx - s * 0.8, cy - s * 0.15, s * 1.6, s * 0.42), radius=s * 0.2)
            for i in range(3):
                d = ((now * 1.2 + i * 0.33) % 1.0)
                dx, dy = cx - s * 0.45 + i * s * 0.45, cy + s * 0.4 + d * s * 0.5
                c.line(fade(SKY), (dx, dy), (dx - s * 0.06, dy + s * 0.18), max(3, int(s * 0.07)))

    def _draw_wonder(self, c, cx, top, bw, bh, h, now, mix, t):
        appear = min(1.0, t / 1.2)
        # a big "?" that bobs and tilts while she wonders
        size = int(h * 0.2)
        qx = cx - size * 0.25 + math.sin(now * 2.0) * h * 0.01
        qy = top + bh * 0.12 + math.sin(now * 1.4) * h * 0.012
        c.text("?", (qx, qy), size, mix(THINK, appear))
        self._wrapped(c, self.question, cx, top + bh * 0.62, bw * 0.86, h, mix(TEXT, appear))

    def _draw_asking(self, c, cx, top, bw, bh, h, now, mix, t):
        s = h * 0.13
        icx, icy = cx, top + bh * 0.4
        # signal waves going out toward the node
        for i in range(3):
            p = (now * 0.9 + i / 3) % 1.0
            r = s * (1.0 + p * 1.1)
            c.arc(mix(THINK, (1 - p) * 0.9), (icx - r, icy - r, 2 * r, 2 * r),
                  math.pi * 0.2, math.pi * 0.8, 3)
            c.arc(mix(THINK, (1 - p) * 0.9), (icx - r, icy - r, 2 * r, 2 * r),
                  math.pi * 1.2, math.pi * 1.8, 3)
        self._icon(c, icx, icy, s, mix, now)
        self._wrapped(c, self.question, cx, top + bh * 0.72, bw * 0.86, h, mix(SOFT), max_lines=2)

    def _draw_answer(self, c, cx, top, bw, bh, h, now, mix, t):
        r = self.reading
        k = min(1.0, t / 0.8)
        title_size = max(14, int(h * 0.05))
        title = self.info["title"]
        c.text(title, (cx - c.measure(title, title_size) / 2, top + bh * 0.06), title_size, mix(SOFT, k))
        s = h * 0.1
        if r and r.ok:
            self._icon(c, cx - bw * 0.27, top + bh * 0.36, s, mix, now, k)
            big_size = int(h * 0.15)
            accent = WORRY if r.mood == "worried" else (MINT if self.info["icon"] == "sprout" else SKY)
            c.text(r.big, (cx - bw * 0.1, top + bh * 0.2), big_size, mix(accent, k))
            lab_size = max(14, int(h * 0.045))
            c.text(r.label, (cx - bw * 0.1, top + bh * 0.2 + big_size * 1.15), lab_size, mix(SOFT, k))
            if r.detail:
                c.text(r.detail, (cx - c.measure(r.detail, lab_size) / 2, top + bh * 0.6), lab_size, mix(TEXT, k))
            self._wrapped(c, r.comment, cx, top + bh * 0.78, bw * 0.86, h, mix(GOLD, k), max_lines=2)
        else:
            self._icon(c, cx, top + bh * 0.38, s, mix, now, k * 0.35)   # faded: no answer
            zs = max(16, int(h * 0.05))
            for i in range(3):   # the node is "asleep": little z's
                p = (now * 0.5 + i * 0.33) % 1.0
                c.text("z", (cx + s * 0.8 + i * h * 0.03, top + bh * 0.36 - i * h * 0.04 - p * h * 0.03),
                       zs + i * 4, mix(SOFT, k * (1 - p)))
            comment = r.comment if r else "No answer."
            self._wrapped(c, comment, cx, top + bh * 0.68, bw * 0.86, h, mix(TEXT, k))

    @staticmethod
    def _wrapped(c, text, cx, y, width, h, color, max_lines=3):
        size = max(16, int(h * 0.058))
        lines = dreams._wrap(c, text, size, width)
        while len(lines) > max_lines and size > 14:
            size -= 2
            lines = dreams._wrap(c, text, size, width)
        lh = size * 1.25
        for i, line in enumerate(lines[:max_lines]):
            c.text(line, (cx - c.measure(line, size) / 2, y + i * lh), size, color)

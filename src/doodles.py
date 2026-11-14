"""
Doodles: Chatty's screensaver. When she's bored (awake, idle, nobody talking)
she sometimes draws on her screen instead of playing tic-tac-toe.

Styles:
  spiro  - a spirograph, drawn one line at a time in shifting colors, then signed
  stars  - a starry sky twinkles in, then she joins some stars into a
           constellation and names it (look out for the Golden Rule)
  rain   - falling code: columns of glowing letters and numbers. Now and then
           one column spells out a hidden, friendly word
  portrait - (rare) she paints a little self-portrait
  fractal  - one of her fractals (fractals.py): a Mandelbrot dive, a Julia set,
             a fern, the Koch snowflake, a fractal tree or the dragon curve

A tap stops the doodle (it doesn't wake her). "Hey Chatty, draw something",
"show me the code rain" or "draw a fractal" starts one; so does the face message
`doodle`, `doodle:rain`, `doodle:fractal` or `doodle:mandel`.

Settings (in /etc/chatty/secrets.env):
  CHATTY_DOODLES=0           no doodles
  CHATTY_DOODLE_STYLES=rain  only these styles (comma list: spiro,stars,rain,fractal;
                             a fractal's own name works too, e.g. mandel)
  CHATTY_DOODLE_SHARE=0.5    when bored, how often she draws instead of playing
  CHATTY_DOODLE_SECONDS=45   how long each drawing stays up

At night (quiet hours) the colors are dimmed so the screen isn't bright in a
dark room. Runs at about 15 fps; everything is a few hundred simple shapes.

Drawing uses the same small canvas interface as face_model, plus an optional
`polyline(color, points, width)` (one call for many segments, much cheaper).
"""
from __future__ import annotations

import colorsys
import math
import os
import random
import time

try:
    import fractals
    import quiet_hours
except ImportError:  # running from another folder
    from . import fractals, quiet_hours  # type: ignore

ENABLED = os.getenv("CHATTY_DOODLES", "1") != "0"
SHARE = float(os.getenv("CHATTY_DOODLE_SHARE", "0.5"))
SECONDS = float(os.getenv("CHATTY_DOODLE_SECONDS", "45"))
FPS = 15
ALL_STYLES = ("spiro", "stars", "rain", "fractal")
PORTRAIT_CHANCE = 0.06      # the rare self-portrait

BG = (8, 10, 14)
FACE = (225, 240, 236)
GOLD = (255, 204, 64)
TEXT = (150, 160, 176)


def styles() -> list:
    wanted = [s.strip().lower() for s in os.getenv("CHATTY_DOODLE_STYLES", "").split(",") if s.strip()]
    chosen = [s for s in wanted if s in ALL_STYLES + ("portrait",) + fractals.KINDS]
    return chosen or list(ALL_STYLES)


def _mix(col, k):
    """Fade a color toward the background (k = 1 full color, 0 background)."""
    return tuple(int(b + (a - b) * k) for a, b in zip(col, BG))


def _hsv(h, s=0.65, v=1.0):
    return tuple(int(x * 255) for x in colorsys.hsv_to_rgb(h % 1.0, s, v))


def _polyline(c, color, pts, width):
    if len(pts) < 2:
        return
    fn = getattr(c, "polyline", None)
    if fn:
        fn(color, pts, width)
    else:
        for a, b in zip(pts, pts[1:]):
            c.line(color, a, b, width)


def _theme(now):
    """Special days get their own colors (same days as the face's touches)."""
    d = time.localtime(now)
    if os.getenv("CHATTY_FORCE_VALENTINE") == "1" or (d.tm_mon == 2 and d.tm_mday == 14):
        return "valentine"
    if os.getenv("CHATTY_FORCE_SPOOKY") == "1" or (d.tm_mon == 10 and d.tm_mday == 31) \
            or (d.tm_mday == 13 and d.tm_wday == 4):
        return "spooky"
    return ""


class Doodle:
    def __init__(self, rng: random.Random, now: float, style: str | None = None,
                 raining: bool = False):
        self.rng = rng
        self.started = now
        if style not in ALL_STYLES + ("portrait",) + fractals.KINDS:
            options = styles()
            style = rng.choice(options)
            if len(options) > 1 and rng.random() < PORTRAIT_CHANCE:
                style = "portrait"
        if style == "fractal":
            style = rng.choice(fractals.kinds())
        self.style = style
        self.done = False
        self.duration = SECONDS
        self.theme = _theme(now) or ("storm" if raining else "")
        self.dim = 0.55 if quiet_hours.is_night(now) else 1.0
        self.fractal = None
        if style in fractals.KINDS:
            self.duration = fractals.SECONDS
            self.fractal = fractals.Fractal(style, rng, now, self.theme, self.duration)
        self.layout = None      # built on first draw, when the screen size is known
        self._w = self._h = 0

    # ----- life cycle -----
    def update(self, now: float):
        if now - self.started > self.duration:
            self.done = True

    def status(self, now: float) -> str:
        t = now - self.started
        if self.fractal:
            return "Fractals - tap to stop" if t < 4 else self.fractal.status(t)
        if self.style == "rain":
            return "Tap to stop" if t < 6 else ""   # the rain gets the whole screen
        if self.style == "stars" and self.layout and t > self.layout["named_at"]:
            return "I call it " + self.layout["name"]
        if self.style == "portrait" and t > 14:
            return "Self-portrait. I think I got my good side."
        return {"spiro": "Doodling - tap to stop", "stars": "Stargazing - tap to stop",
                "portrait": "Painting - hold still..."}.get(self.style, "")

    def draw(self, c, w, h, now):
        if self.fractal:
            t = now - self.started
            k = max(0.0, min(1.0, t / 1.5, (self.duration - t) / 1.5)) * self.dim
            self.fractal.draw(c, w, h, now, t, k)
            return
        if self.layout is None or (w, h) != (self._w, self._h):
            self._w, self._h = w, h
            self.layout = getattr(self, "_build_" + self.style)(w, h)
        t = now - self.started
        # fade in at the start and out at the end
        k = max(0.0, min(1.0, t / 1.5, (self.duration - t) / 1.5)) * self.dim
        getattr(self, "_draw_" + self.style)(c, w, h, now, t, k)

    # ----- spirograph -----
    def _build_spiro(self, w, h):
        rng = self.rng
        big = rng.randint(5, 11)
        small = rng.choice([s for s in range(2, big) if math.gcd(big, s) == 1] or [3])
        pen = rng.uniform(0.5, 1.1) * small
        turns = small                      # the curve closes after this many turns
        n = 140 * turns if turns < 5 else 700
        n = max(300, min(900, n))
        scale = h * 0.4 / ((big - small) + pen)
        cx, cy = w / 2, h * 0.46
        pts = []
        for i in range(n + 1):
            a = 2 * math.pi * turns * i / n
            x = (big - small) * math.cos(a) + pen * math.cos((big - small) / small * a)
            y = (big - small) * math.sin(a) - pen * math.sin((big - small) / small * a)
            pts.append((cx + x * scale, cy + y * scale))
        return dict(pts=pts, hue=rng.random(), spread=rng.uniform(0.25, 0.7),
                    draw_secs=min(self.duration * 0.6, 26.0))

    def _spiro_hue(self, L, frac):
        if self.theme == "valentine":
            return 0.93 + 0.06 * math.sin(frac * math.pi * 2)
        if self.theme == "spooky":
            return 0.03 + 0.07 * frac
        return L["hue"] + L["spread"] * frac

    def _draw_spiro(self, c, w, h, now, t, k):
        L = self.layout
        pts = L["pts"]
        frac = min(1.0, t / L["draw_secs"])
        upto = max(2, int(len(pts) * frac))
        chunks = 24
        step = len(pts) / chunks
        width = max(2, int(h * 0.006))
        for i in range(chunks):
            a = int(i * step)
            if a >= upto:
                break
            b = min(upto, int((i + 1) * step) + 1)
            col = _hsv(self._spiro_hue(L, i / chunks))
            _polyline(c, _mix(col, k), pts[a:b], width)
        if frac < 1.0:          # the pen tip
            x, y = pts[upto - 1]
            r = width * 2
            c.ellipse(_mix(FACE, k), (x - r, y - r, 2 * r, 2 * r))
        elif t > L["draw_secs"] + 1.5:
            self._signature(c, w, h, k * min(1.0, (t - L["draw_secs"] - 1.5) / 1.5))

    def _signature(self, c, w, h, k):
        size = max(14, int(h * 0.045))
        txt = "~ Chatty"
        c.text(txt, (w * 0.95 - c.measure(txt, size), h * 0.80), size, _mix(GOLD, k))

    # ----- constellations -----
    # points are in a 0..1 box; edges join point indexes; "eyes" etc. are lone stars
    FIGURES = [
        ("Tiny Major",   # Tiny the tuxedo cat
         [(0.18, 0.0), (0.36, 0.28), (0.64, 0.28), (0.82, 0.0), (0.95, 0.5), (0.78, 0.88),
          (0.5, 1.0), (0.22, 0.88), (0.05, 0.5), (0.36, 0.55), (0.64, 0.55)],
         [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 0)]),
        ("The Golden Rule",   # a ruler, in gold. Treat others as you'd like to be treated.
         [(0.0, 0.35), (1.0, 0.35), (1.0, 0.65), (0.0, 0.65), (0.2, 0.35), (0.2, 0.5),
          (0.4, 0.35), (0.4, 0.45), (0.6, 0.35), (0.6, 0.5), (0.8, 0.35), (0.8, 0.45)],
         [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (6, 7), (8, 9), (10, 11)]),
        ("The Watering Can",   # for the greenhouse
         [(0.15, 0.4), (0.65, 0.4), (0.65, 0.95), (0.15, 0.95), (0.65, 0.6), (1.0, 0.2),
          (0.25, 0.4), (0.4, 0.1), (0.55, 0.4)],
         [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (6, 7), (7, 8)]),
        ("The Lightning Bolt",   # for the lightning node
         [(0.6, 0.0), (0.25, 0.5), (0.5, 0.5), (0.3, 1.0), (0.8, 0.4), (0.55, 0.4)],
         [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0)]),
        ("The Raindrop",   # for the rain gauge
         [(0.5, 0.0), (0.72, 0.45), (0.78, 0.72), (0.5, 1.0), (0.22, 0.72), (0.28, 0.45)],
         [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0)]),
        ("The Big Heart",
         [(0.5, 0.3), (0.72, 0.05), (0.95, 0.2), (0.9, 0.5), (0.5, 1.0), (0.1, 0.5),
          (0.05, 0.2), (0.28, 0.05)],
         [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 0)]),
        ("The Little Robot",   # a self-portrait in stars
         [(0.2, 0.3), (0.8, 0.3), (0.8, 0.9), (0.2, 0.9), (0.5, 0.3), (0.5, 0.05),
          (0.36, 0.55), (0.64, 0.55), (0.38, 0.75), (0.62, 0.75)],
         [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (8, 9)]),
    ]

    def _build_stars(self, w, h):
        rng = self.rng
        name, fig, edges = rng.choice(self.FIGURES)
        if self.theme == "valentine":
            name, fig, edges = self.FIGURES[5]
        size = h * 0.5
        fx, fy = w * rng.uniform(0.3, 0.7) - size / 2, h * 0.14
        stars = [(fx + x * size, fy + y * size) for x, y in fig]
        field = [(rng.uniform(0, w), rng.uniform(0, h * 0.86), rng.uniform(1.0, 2.6),
                  rng.uniform(0.6, 2.2), rng.uniform(0, 6.3), rng.uniform(0, 5)) for _ in range(70)]
        edge_secs = 0.7
        lines_at = 5.0
        return dict(name=name, stars=stars, edges=edges, field=field, edge_secs=edge_secs,
                    lines_at=lines_at, named_at=lines_at + len(edges) * edge_secs + 0.8,
                    color=GOLD if name == "The Golden Rule" else (190, 210, 255))

    def _draw_stars(self, c, w, h, now, t, k):
        L = self.layout
        star = (235, 240, 255) if self.theme != "spooky" else (255, 170, 90)
        for x, y, r, speed, phase, appear in L["field"]:
            a = max(0.0, min(1.0, (t - appear) / 1.2))
            if a <= 0:
                continue
            tw = 0.55 + 0.45 * math.sin(now * speed + phase)
            c.ellipse(_mix(star, k * a * tw), (x - r, y - r, 2 * r, 2 * r))
        # the constellation's lines, one at a time
        lw = max(2, int(h * 0.006))
        for i, (a, b) in enumerate(L["edges"]):
            p = (t - L["lines_at"] - i * L["edge_secs"]) / L["edge_secs"]
            if p <= 0:
                break
            p = min(1.0, p)
            (x1, y1), (x2, y2) = L["stars"][a], L["stars"][b]
            c.line(_mix(L["color"], k * 0.75), (x1, y1), (x1 + (x2 - x1) * p, y1 + (y2 - y1) * p), lw)
        # its stars are bigger and brighter
        a = max(0.0, min(1.0, (t - 2.0) / 1.5))
        for i, (x, y) in enumerate(L["stars"]):
            r = h * 0.011 * (1 + 0.15 * math.sin(now * 2 + i))
            c.ellipse(_mix(star, k * a), (x - r, y - r, 2 * r, 2 * r))
        if t > L["named_at"]:
            fade = k * min(1.0, (t - L["named_at"]) / 1.5)
            size = max(16, int(h * 0.06))
            xs = [x for x, _ in L["stars"]]
            ymax = max(y for _, y in L["stars"])
            cx = (min(xs) + max(xs)) / 2
            c.text(L["name"], (cx - c.measure(L["name"], size) / 2, ymax + h * 0.04), size,
                   _mix(L["color"], fade))

    # ----- falling code -----
    GLYPHS = "0123456789ABCDEFHKLMNPRSTXZ:=+*<>"
    WORDS = ["HELLO", "BE KIND", "HI TINY", "THANK YOU", "GOLDEN RULE", "HOPE",
             "HI VINCENT", "GROW", "<3", "HI RAIN NODE", "HI GREENHOUSE", "SMILE",
             "YOU ARE LOVED", "CHATTY"]

    def _build_rain(self, w, h):
        rng = self.rng
        size = max(14, int(h * 0.042))
        step_x, step_y = size * 0.95, size * 1.05
        cols = int(w / step_x)
        rows = int(h / step_y) + 1
        columns = []
        for i in range(cols):
            columns.append(dict(x=i * step_x + (w - cols * step_x) / 2,
                                head=rng.uniform(-rows, rows), speed=rng.uniform(6, 14),
                                trail=rng.randint(6, 16),
                                cells=[rng.choice(self.GLYPHS) for _ in range(rows)],
                                word=None))
        L = dict(size=size, step_y=step_y, rows=rows, columns=columns, next_word=4.0)
        if self.theme == "valentine":
            L["base"], L["head"], L["word"] = (255, 110, 160), (255, 220, 235), (255, 240, 248)
        elif self.theme == "spooky":
            L["base"], L["head"], L["word"] = (255, 120, 30), (255, 220, 160), (255, 236, 200)
        elif self.theme == "storm":     # it's really raining outside: blue rain
            L["base"], L["head"], L["word"] = (70, 140, 255), (200, 228, 255), (240, 246, 255)
        else:
            L["base"], L["head"], L["word"] = (60, 230, 120), (210, 255, 225), GOLD
        return L

    RAIN_WORDS = ["ITS RAINING", "HI RAIN NODE", "PLANTS SAY THANKS", "STAY DRY", "PUDDLES"]

    def _place_word(self, L):
        """Hide a friendly word in one column, top to bottom, where the rain will reveal it."""
        rng = self.rng
        words = self.RAIN_WORDS if self.theme == "storm" and rng.random() < 0.6 else self.WORDS
        word = rng.choice(words)
        if len(word) + 2 > L["rows"]:
            return
        col = rng.choice(L["columns"])
        if col["word"]:
            return
        start = rng.randint(1, L["rows"] - len(word) - 1)
        col["word"] = (start, word)
        col["head"] = -2.0
        col["speed"] = 7.0

    def _draw_rain(self, c, w, h, now, t, k):
        L = self.layout
        dt = min(0.25, now - L.get("last", now))
        L["last"] = now
        rng = self.rng
        if t > L["next_word"]:
            self._place_word(L)
            L["next_word"] = t + rng.uniform(7, 14)
        size, step_y, rows = L["size"], L["step_y"], L["rows"]
        levels = 6    # brightness steps (keeps the pygame glyph cache small)
        for col in L["columns"]:
            col["head"] += col["speed"] * dt
            head = int(col["head"])
            word = col["word"]
            linger = 30 if word else 0              # a hidden word stays up a few seconds
            if head - col["trail"] > rows + linger:  # fell off the bottom: start again
                col.update(head=rng.uniform(-8, 0), speed=rng.uniform(6, 14),
                           trail=rng.randint(6, 16), word=None)
                continue
            if rng.random() < 0.08:                 # glyphs flicker now and then
                col["cells"][rng.randrange(rows)] = rng.choice(self.GLYPHS)
            start, text = word if word else (rows, "")
            for r in range(max(0, head - col["trail"]), min(rows, head + 1)):
                behind = head - r
                ch = col["cells"][r]
                if start <= r < start + len(text):
                    continue                        # drawn below
                if behind == 0:
                    color = _mix(L["head"], k)
                else:
                    level = max(1, levels - int(behind * levels / (col["trail"] + 1)))
                    color = _mix(L["base"], k * level / levels)
                c.text(ch, (col["x"], r * step_y - size * 0.1), size, color)
            # the hidden word: once the rain reaches a letter, it stays lit until the
            # column starts over, so it can be read top to bottom
            for i, ch in enumerate(text):
                r = start + i
                if ch != " " and r <= head:
                    c.text(ch, (col["x"], r * step_y - size * 0.1), size, _mix(L["word"], k))

    # ----- the rare self-portrait -----
    def _build_portrait(self, w, h):
        return dict(cx=w * 0.5, cy=h * 0.44)

    def _draw_portrait(self, c, w, h, now, t, k):
        L = self.layout
        fw, fh = h * 0.95, h * 0.68
        x0, y0 = L["cx"] - fw / 2, L["cy"] - fh / 2
        frame = (176, 132, 80)
        lw = max(4, int(h * 0.016))
        # the frame draws itself around, side by side
        sides = [((x0, y0), (x0 + fw, y0)), ((x0 + fw, y0), (x0 + fw, y0 + fh)),
                 ((x0 + fw, y0 + fh), (x0, y0 + fh)), ((x0, y0 + fh), (x0, y0))]
        for i, (a, b) in enumerate(sides):
            p = max(0.0, min(1.0, (t - 1 - i * 0.8) / 0.8))
            if p <= 0:
                break
            c.line(_mix(frame, k), a, (a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p), lw)
        # canvas wash
        if t > 4.5:
            c.rrect(_mix((24, 30, 44), k * min(1.0, (t - 4.5) / 1.5)),
                    (x0 + lw, y0 + lw, fw - 2 * lw, fh - 2 * lw), radius=6)
        # eyes, one then the other, then the smile
        ew, eh = fw * 0.12, fh * 0.36
        for i, ex in enumerate((L["cx"] - fw * 0.17, L["cx"] + fw * 0.17)):
            p = max(0.0, min(1.0, (t - 6.5 - i * 1.5) / 1.2))
            if p > 0:
                hh = eh * p
                c.rrect(_mix(FACE, k), (ex - ew / 2, L["cy"] - fh * 0.08 - hh / 2, ew, hh),
                        radius=min(ew, hh) * 0.45)
        if t > 10:
            p = min(1.0, (t - 10) / 1.5)
            mw, mh = fw * 0.22, fh * 0.2
            c.arc(_mix(FACE, k * p), (L["cx"] - mw / 2, L["cy"] + fh * 0.1, mw, mh),
                  math.pi * 1.15, math.pi * (1.15 + 0.7 * p), max(4, int(h * 0.014)))
        if t > 12:
            p = min(1.0, (t - 12) / 1.5)
            for side in (-1, 1):     # a little blush, she's proud of it
                r = fw * 0.05
                bx = L["cx"] + side * fw * 0.3
                c.ellipse(_mix((255, 92, 140), k * p * 0.5), (bx - r, L["cy"] + fh * 0.12 - r * 0.6, 2 * r, r * 1.2))
            size = max(14, int(h * 0.04))
            c.text("~ C.", (x0 + fw - c.measure("~ C.", size) - lw * 3, y0 + fh - size * 1.6), size,
                   _mix(GOLD, k * p))

"""
Chatty's dreams: gentle, positive things she "dreams" about while asleep.

While dozing or put to bed, a dream cloud fades in with one of:
  - a little picture drawn with code (moon and stars, a sprout, a sleeping cat...)
  - a short, kind quote
  - letters that drift together to spell a word

Add your own dream lines (one per line) to:
    ~/.local/share/chatty/dreams.txt      (or CHATTY_DREAMS_FILE)
Turn dreams off with CHATTY_DREAMS=0.

Drawing uses the same small canvas interface as face_model: fill, rrect, ellipse,
arc, line, polygon, text, measure. Everything is simple shapes, cheap for a Pi.
"""
from __future__ import annotations

import math
import os
import random
from pathlib import Path

ENABLED = os.getenv("CHATTY_DREAMS", "1") != "0"
DELAY = float(os.getenv("CHATTY_DREAM_DELAY", "30"))    # seconds asleep before dreaming
ITEM_SECONDS = float(os.getenv("CHATTY_DREAM_SECONDS", "30"))  # each dream lasts this long
DREAMS_FILE = Path(os.getenv("CHATTY_DREAMS_FILE",
                             os.path.expanduser("~/.local/share/chatty/dreams.txt")))

QUOTES = [
    "Not a race. A resonance.",
    "Every seed knows how to become a flower.",
    "Rest is part of growing.",
    "Small steps still move you forward.",
    "You are doing better than you think.",
    "Hope is a quiet kind of brave.",
    "The stars are still there in daylight.",
    "Plant something today. Even an idea.",
    "Be kind to yourself, and to the machines.",
    "A journey of a thousand miles begins with a single step.",
    "Tomorrow is a blank page.",
    "Good things grow slowly.",
]
WORDS = ["hope", "dream", "grow", "home", "kind", "stars", "rest", "bloom"]
PICTURES = ["moon", "sprout", "cat", "heart", "constellation", "sunrise"]

# soft dream colors
LAVENDER = (182, 170, 255)
GOLD = (255, 214, 120)
MINT = (140, 230, 190)
PINK = (255, 160, 190)
SKY = (130, 200, 255)
EARTH = (190, 140, 100)


def _mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _user_lines():
    try:
        return [l.strip() for l in DREAMS_FILE.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.startswith("#")][:200]
    except OSError:
        return []


def pick(rng: random.Random, last=None) -> tuple:
    """Choose the next dream: ('picture', name) | ('quote', text) | ('word', text)."""
    for _ in range(5):
        kind = rng.choices(["picture", "quote", "word"], weights=[5, 4, 2])[0]
        if kind == "picture":
            d = (kind, rng.choice(PICTURES))
        elif kind == "quote":
            d = (kind, rng.choice(QUOTES + _user_lines()))
        else:
            d = (kind, rng.choice(WORDS))
        if d != last:
            return d
    return d


# ----------------------------
# the cloud
# ----------------------------

def cloud_box(w, h, now):
    bob = math.sin(now * 0.5) * h * 0.008
    return w * 0.10, h * 0.07 + bob, w * 0.80, h * 0.62   # x, y, width, height


def draw_cloud(c, w, h, now, fill):
    x, y, cw, ch = cloud_box(w, h, now)
    r = ch * 0.30
    top = y + r * 0.45
    c.rrect(fill, (x, top, cw, ch - r * 0.45), radius=r)
    # gentle bumps along the top and bottom make it puffy
    n = 6
    for i in range(n):
        bx = x + cw * (i + 0.5) / n
        br = r * (0.52 + 0.14 * math.sin(i * 1.7))
        c.ellipse(fill, (bx - br, top + r * 0.15 - br, 2 * br, 2 * br))
    for i in range(n - 1):
        bx = x + cw * (i + 1) / n
        br = r * 0.45
        c.ellipse(fill, (bx - br, y + ch - br * 1.25, 2 * br, 2 * br))


def draw_sleeper(c, w, h, now, col, cloud_fill):
    """Tiny sleeping face in the corner with thought bubbles rising to the cloud."""
    fx, fy = w * 0.10, h * 0.86
    s = h * 0.05
    c.line(col, (fx - s * 0.9, fy), (fx - s * 0.3, fy), 3)
    c.line(col, (fx + s * 0.3, fy), (fx + s * 0.9, fy), 3)
    c.arc(col, (fx - s * 0.3, fy + s * 0.25, s * 0.6, s * 0.5), math.pi * 1.15, math.pi * 1.85, 3)
    # bubbles, gently pulsing, from the face up toward the cloud
    for i, (px, py, pr) in enumerate(((0.16, 0.79, 0.012), (0.20, 0.745, 0.019), (0.25, 0.70, 0.028))):
        rr = h * pr * (1 + 0.12 * math.sin(now * 1.5 + i))
        c.ellipse(cloud_fill, (w * px - rr, h * py - rr, 2 * rr, 2 * rr))


# ----------------------------
# what she dreams
# ----------------------------

def draw_item(c, w, h, now, item, started, k, dim, bg):
    """k: 0..1 fade amount. dim: 0..1 extra dimming at night. bg: the cloud's current color."""
    x, y, cw, ch = cloud_box(w, h, now)
    cx, cy = x + cw / 2, y + ch * 0.52
    s = ch * 0.36
    fade = lambda col: _mix(bg, col, k * (1 - 0.45 * dim))
    kind, value = item
    t = now - started
    if kind == "picture":
        PICTURE_FUNCS[value](c, cx, cy, s, fade, now, bg)
    elif kind == "quote":
        _quote(c, cx, cy, cw * 0.82, h, value, fade)
    else:
        _word(c, cx, cy, h, value, fade, t)


def _wrap(c, text, size, width):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if c.measure(trial, size) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def _quote(c, cx, cy, width, h, text, fade):
    size = max(16, int(h * 0.065))
    lines = _wrap(c, text, size, width)
    while len(lines) > 3 and size > 14:
        size -= 2
        lines = _wrap(c, text, size, width)
    lh = size * 1.25
    top = cy - lh * len(lines) / 2
    for i, line in enumerate(lines):
        c.text(line, (cx - c.measure(line, size) / 2, top + i * lh), size, fade(GOLD if i == 0 else LAVENDER))


def _word(c, cx, cy, h, word, fade, t):
    """Letters drift in from scattered spots and settle into the word."""
    size = max(24, int(h * 0.13))
    word = word.upper()
    widths = [c.measure(ch_, size) for ch_ in word]
    gap = size * 0.18
    total = sum(widths) + gap * (len(word) - 1)
    x = cx - total / 2
    rng = random.Random(word)
    settle = min(1.0, t / 4.0)
    ease = 1 - (1 - settle) ** 3
    colors = [SKY, MINT, GOLD, PINK, LAVENDER]
    for i, ch_ in enumerate(word):
        sx = cx + rng.uniform(-1, 1) * h * 0.6
        sy = cy + rng.uniform(-1, 1) * h * 0.25
        px = sx + (x - sx) * ease
        py = sy + (cy - size * 0.6 - sy) * ease + math.sin(t * 1.2 + i) * h * 0.006
        c.text(ch_, (px, py), size, fade(colors[i % len(colors)]))
        x += widths[i] + gap


def _moon(c, cx, cy, s, fade, now, bg):
    c.ellipse(fade(GOLD), (cx - s * 0.9, cy - s * 0.9, s * 1.8, s * 1.8))
    c.ellipse(bg, (cx - s * 0.45, cy - s * 1.05, s * 1.8, s * 1.8))  # bite out a crescent
    rng = random.Random(7)
    for i in range(7):
        sx, sy = cx + rng.uniform(0.4, 2.6) * s * rng.choice((-1, 1)), cy + rng.uniform(-1, 1) * s
        tw = 0.5 + 0.5 * math.sin(now * 2 + i * 1.3)
        r = s * (0.05 + 0.05 * tw)
        c.ellipse(fade(_mix(LAVENDER, (255, 255, 255), tw)), (sx - r, sy - r, 2 * r, 2 * r))


def _sprout(c, cx, cy, s, fade, now, bg):
    sway = math.sin(now * 0.8) * s * 0.08
    c.polygon(fade(EARTH), [(cx - s * 0.55, cy + s * 0.35), (cx + s * 0.55, cy + s * 0.35),
                            (cx + s * 0.4, cy + s * 1.05), (cx - s * 0.4, cy + s * 1.05)])
    c.rrect(fade(_mix(EARTH, (255, 255, 255), 0.15)), (cx - s * 0.62, cy + s * 0.25, s * 1.24, s * 0.2), s * 0.08)
    c.line(fade(MINT), (cx, cy + s * 0.3), (cx + sway, cy - s * 0.6), max(3, int(s * 0.08)))
    for side in (-1, 1):
        lx = cx + sway * 0.7 + side * s * 0.32
        ly = cy - s * 0.35 - (0.15 * s if side > 0 else 0)
        c.ellipse(fade(MINT), (lx - s * 0.3, ly - s * 0.14, s * 0.6, s * 0.28))


def _cat(c, cx, cy, s, fade, now, bg):
    col = fade(PINK)
    breath = 1 + 0.03 * math.sin(now * 1.2)
    c.ellipse(col, (cx - s * 1.1, cy - s * 0.35 * breath, s * 2.0, s * 0.95 * breath))   # curled body
    hx, hy = cx + s * 0.75, cy - s * 0.05
    c.ellipse(col, (hx - s * 0.42, hy - s * 0.4, s * 0.84, s * 0.75))                    # head
    c.polygon(col, [(hx - s * 0.36, hy - s * 0.2), (hx - s * 0.26, hy - s * 0.62), (hx - s * 0.06, hy - s * 0.32)])
    c.polygon(col, [(hx + s * 0.06, hy - s * 0.32), (hx + s * 0.26, hy - s * 0.62), (hx + s * 0.36, hy - s * 0.2)])
    for ex in (hx - s * 0.17, hx + s * 0.13):                                              # closed eyes
        c.arc(bg, (ex - s * 0.09, hy - s * 0.08, s * 0.18, s * 0.12), math.pi * 1.1, math.pi * 1.9, 2)
    c.arc(col, (cx - s * 1.45, cy - s * 0.1, s * 1.1, s * 0.9), math.pi * 0.5, math.pi * 1.4, max(3, int(s * 0.12)))  # tail
    for i in range(3):                                                                     # z's
        t = (now * 0.4 + i / 3) % 1
        c.text("z", (hx + s * (0.5 + 0.3 * i + 0.2 * t), hy - s * (0.7 + 0.35 * i + 0.3 * t)),
               int(s * (0.25 + 0.08 * i)), _mix(bg, col, 1 - t))


def _heart(c, cx, cy, s, fade, now, bg):
    beat = 1 + 0.06 * max(0, math.sin(now * 3)) ** 8
    r = s * 0.5 * beat
    col = fade(PINK)
    c.ellipse(col, (cx - r * 1.9, cy - r * 1.2, r * 2, r * 2))
    c.ellipse(col, (cx - r * 0.1, cy - r * 1.2, r * 2, r * 2))
    c.polygon(col, [(cx - r * 1.82, cy - r * 0.05), (cx + r * 1.82, cy - r * 0.05), (cx, cy + r * 1.9)])


def _constellation(c, cx, cy, s, fade, now, bg):
    pts = [(-2.2, 0.4), (-1.4, -0.5), (-0.5, -0.2), (0.3, -0.8), (1.2, -0.3), (2.0, 0.5), (0.6, 0.6)]
    pts = [(cx + x * s * 0.95, cy + y * s * 0.95) for x, y in pts]
    for a, b in zip(pts, pts[1:]):
        c.line(fade(_mix(bg, SKY, 0.55)), a, b, 2)
    for i, (px, py) in enumerate(pts):
        tw = 0.5 + 0.5 * math.sin(now * 1.7 + i)
        r = s * (0.07 + 0.04 * tw)
        c.ellipse(fade(_mix(SKY, (255, 255, 255), tw)), (px - r, py - r, 2 * r, 2 * r))


def _sunrise(c, cx, cy, s, fade, now, bg):
    sy = cy + s * 0.35
    for i in range(9):
        a = math.pi + math.pi * (i + 0.5) / 9
        r1, r2 = s * 0.9, s * (1.25 + 0.08 * math.sin(now * 2 + i))
        c.line(fade(GOLD), (cx + math.cos(a) * r1, sy + math.sin(a) * r1),
               (cx + math.cos(a) * r2, sy + math.sin(a) * r2), 3)
    c.ellipse(fade(GOLD), (cx - s * 0.75, sy - s * 0.75, s * 1.5, s * 1.5))
    c.ellipse(fade(MINT), (cx - s * 2.6, sy - s * 0.15, s * 3.2, s * 1.3))   # hills cover the sun's lower half
    c.ellipse(fade(_mix(MINT, SKY, 0.4)), (cx - s * 0.6, sy, s * 3.2, s * 1.2))


PICTURE_FUNCS = {"moon": _moon, "sprout": _sprout, "cat": _cat, "heart": _heart,
                 "constellation": _constellation, "sunrise": _sunrise}

"""
Fractals: a family of Chatty's screensaver doodles (doodles.py runs them).
Patterns that repeat inside themselves forever, drawn a little at a time.

Kinds:
  mandel    - the Mandelbrot set, painted line by line, then a slow dive into one
              of its famous spots (Seahorse Valley, Elephant Valley, a baby
              Mandelbrot hiding on the antenna...). While the next, sharper
              picture is worked out, the one she has is magnified smoothly, so
              the zoom never stops for long
  julia     - a Julia set (the Mandelbrot set's cousins), soft first, then sharp
  fern      - a Barnsley fern grows dot by dot from four tiny rules
              (autumn colors in Sept-Nov, like the real ones outside)
  snowflake - the Koch snowflake: every edge sprouts a bump, again and again
  tree      - a fractal tree grows branch by branch and sways a little; spring
              blossoms, summer leaves, falling autumn leaves or winter snow
  dragon    - the dragon curve unfolds like a strip of paper folded in half
              again and again

The Pi stays easy: pictures that need real number crunching (mandel, julia) are
worked out a few rows per frame, at most CHATTY_FRACTAL_BUDGET_MS (12 ms) of
each frame (about a fifth of one of the Pi's four cores, in the face's own
process, so her ears in the voice node never notice). numpy is used when the
Pi has it; plain Python works too, just slower. Everything is local.

"Hey Chatty, draw a fractal" (or "show me the Mandelbrot set", "draw a fern",
"draw a snowflake", "grow a fractal tree", "draw a dragon curve"), the panel's
Fractal button, or the face message `doodle:fractal` / `doodle:mandel`.

Settings (in /etc/chatty/secrets.env):
  CHATTY_DOODLE_STYLES=fractal   only fractals as doodles (or e.g. mandel,fern)
  CHATTY_FRACTALS=mandel,fern    which kinds she picks from (default: all)
  CHATTY_FRACTAL_SECONDS=60      how long a fractal stays up
  CHATTY_FRACTAL_BUDGET_MS=12    number crunching allowed per frame

The canvas needs an optional `pixels(img, src, dst, alpha)` method for the
pixel pictures (mandel, julia, fern); chatty_face.py and preview_face.py have
one. Without it those kinds just show their words.

Try one on any computer (Pillow): python3 scripts/preview_fractals.py
"""
from __future__ import annotations

import colorsys
import math
import os
import re
import time

KINDS = ("mandel", "julia", "fern", "snowflake", "tree", "dragon")
SECONDS = float(os.getenv("CHATTY_FRACTAL_SECONDS", "60"))
BUDGET = max(0.002, float(os.getenv("CHATTY_FRACTAL_BUDGET_MS", "12")) / 1000.0)

PIC_H = 0.87       # pixel pictures stop here, so her status line stays readable
BG = (8, 10, 14)
FACE = (225, 240, 236)
GOLD = (255, 204, 64)

try:  # numpy makes the Mandelbrot set about 20x quicker; it's optional
    import numpy as _np
    _z = _np.zeros(3, dtype=_np.complex128) + 1j
    _NP = bool((_np.abs(_z * _z) == 1.0).all())
except Exception:  # missing, or a test's stand-in
    _np, _NP = None, False
if os.getenv("CHATTY_FRACTAL_NUMPY", "1") == "0":
    _NP = False


# ---------------------------------------------------------------- asking for one
_VERB = r"(draw|show|make|grow|paint|do|start|zoom|dive|take me|let'?s see|can i see|i want to see)"
_WHICH = [
    ("mandel", r"mandel ?brot|mandel ?bread|mandel ?bra"),
    ("julia", r"julia set|julia fractal"),
    ("fern", r"(barnsley )?ferns?"),
    ("snowflake", r"(koch |coke )?snow ?flakes?|koch curve"),
    ("tree", r"(fractal )?trees?"),
    ("dragon", r"dragon curve|(paper )?dragon"),
    ("", r"fractals?"),
]


def request(prompt: str):
    """Which fractal a spoken request asks for: 'mandel', 'fern'..., '' for any
    fractal, or None when it isn't a fractal request ("what is a fractal?" isn't)."""
    p = " " + re.sub(r"[^a-z' ]", " ", (prompt or "").lower()) + " "
    p = re.sub(r"\s+", " ", p)
    if re.search(r"\b(what|who|why|how|explain|tell me about)\b", p) and not re.search(r"\b(draw|show|zoom)\b", p):
        return None
    for kind, words in _WHICH:
        m = re.search(r"\b(" + words + r")\b", p)
        if not m:
            continue
        if kind in ("fern", "snowflake", "tree", "dragon") and "fractal" not in p and \
                not re.search(r"\b(barnsley|koch|dragon curve)\b", p):
            # "draw a tree" is a fractal tree, but only when she's asked to draw it
            if not re.search(r"\b(draw|paint|grow|make)\b", p):
                continue
        if kind == "dragon" and re.search(r"\bimagine\b", p):
            continue           # "imagine a dragon" is her imagination mood
        if re.search(r"\b" + _VERB + r"\b", p) or re.fullmatch(r" (the |a |some )?(" + words + r")( set)? ", p):
            return kind
    return None


LINES = {
    "": ["Ooh, fractals! Patterns all the way down. Watch.", "A fractal coming up. It never really ends, you know.",
         "Okay! Grab a snack, this one goes deep."],
    "mandel": ["Into the Mandelbrot set we go! Hold on to something.",
               "The Mandelbrot set! One tiny rule, endless seahorses. Watch."],
    "julia": ["A Julia set, coming up. The Mandelbrot set's fancy cousin."],
    "fern": ["A fern, grown from four tiny rules. Watch it sprout!"],
    "snowflake": ["A Koch snowflake! Every edge grows a bump, forever."],
    "tree": ["One fractal tree, coming up. Every branch is a little tree."],
    "dragon": ["The dragon curve! It's a strip of paper, folded again and again."],
}

ABOUT = {
    "fractal": "A fractal is a pattern that repeats inside itself: zoom in and you find smaller copies, "
               "again and again. Ferns, snowflakes, coastlines and lightning are a bit like that. "
               "Want me to draw one? Just say, draw a fractal.",
    "mandel": "The Mandelbrot set comes from one tiny rule: take a number, square it, add where you started, "
              "and repeat. The points that never run away make the shape, and its edge is endlessly "
              "detailed. Benoit Mandelbrot made it famous in 1980. Say, show me the Mandelbrot set, and we'll dive in.",
    "julia": "Julia sets are the Mandelbrot set's cousins, named after Gaston Julia, who studied them around 1918, "
             "long before computers could draw them. Each point of the Mandelbrot set has its own Julia set.",
}


def explain(prompt: str):
    """A local answer to "what is a fractal?" and friends, or None."""
    p = (prompt or "").lower()
    if not re.search(r"\b(what|who|explain|tell me about)\b", p):
        return None
    if re.search(r"mandel ?brot", p):
        return ABOUT["mandel"]
    if re.search(r"julia set", p):
        return ABOUT["julia"]
    if re.search(r"\bfractals?\b", p):
        return ABOUT["fractal"]
    return None


def kinds() -> list:
    wanted = [k.strip().lower() for k in os.getenv("CHATTY_FRACTALS", "").split(",") if k.strip()]
    chosen = [k for k in wanted if k in KINDS]
    return chosen or list(KINDS)


def _mix(col, k):
    return tuple(int(b + (a - b) * k) for a, b in zip(col, BG))


def _lerp(a, b, p):
    return a + (b - a) * p


def _ease(p):
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


def season(now: float) -> str:
    m = time.localtime(now).tm_mon
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(m, "autumn")


class Pixels:
    """A small RGB picture that the canvas scales up to the screen."""

    def __init__(self, w: int, h: int, color=BG, smooth: bool = True):
        self.w, self.h = w, h
        self.smooth = smooth  # soft scaling (escape-time pictures); False keeps dots crisp
        self.data = bytearray(bytes(color) * (w * h))
        self.version = 0      # bumped when the picture changes (the canvas caches it)

    def set(self, x: int, y: int, col):
        i = (y * self.w + x) * 3
        self.data[i:i + 3] = bytes(col)


def _pixels(c, img, src, dst, alpha=1.0):
    fn = getattr(c, "pixels", None)
    if fn and alpha > 0.01:
        fn(img, src, dst, alpha)


def _segments(c, color, pairs, width):
    fn = getattr(c, "segments", None)
    if fn:
        fn(color, pairs, width)
    else:
        for a, b in pairs:
            c.line(color, a, b, width)


# ---------------------------------------------------------------- palettes
def palette(theme: str, shift: float, n: int = 256) -> list:
    """n colors to paint escape times with (a smooth cosine gradient)."""
    if theme == "valentine":
        a, b, cc, d = (0.75, 0.35, 0.5), (0.25, 0.3, 0.3), (1.0, 1.0, 1.0), (0.0, 0.1, 0.05)
    elif theme == "spooky":
        a, b, cc, d = (0.6, 0.3, 0.25), (0.4, 0.3, 0.3), (1.0, 1.0, 0.5), (0.0, 0.05, 0.6)
    elif theme == "storm":
        a, b, cc, d = (0.3, 0.45, 0.65), (0.25, 0.3, 0.35), (1.0, 1.0, 1.0), (0.1, 0.2, 0.3)
    else:
        a, b, cc, d = (0.5, 0.5, 0.5), (0.5, 0.5, 0.5), (1.0, 1.0, 1.0), (0.0 + shift, 0.33 + shift, 0.67 + shift)
    out = []
    for i in range(n):
        t = i / n
        col = []
        for j in range(3):
            v = a[j] + b[j] * math.cos(2 * math.pi * (cc[j] * t + d[j]))
            col.append(int(max(0.0, min(1.0, v)) * 235 + 12))
        out.append(bytes(col))
    return out


# ---------------------------------------------------------------- escape time
BANDS = 22.0       # palette steps per square root of the iteration count (gentle bands)
FADE_IN = 14.0     # iterations before a point gets its full color
def _escape_rows(img, view, max_iter, pal, julia_c=None, row0=0, rows=None):
    """Work out the picture a few rows at a time. A generator: each yield is a
    small step, so the caller can stop when this frame's budget is spent."""
    cx, cy, vw = view
    w, h = img.w, img.h
    vh = vw * h / w
    dx = vw / w
    x0 = cx - vw / 2 + dx / 2
    y_top = cy + vh / 2 - dx / 2
    inside = bytes(BG)
    npal = len(pal)
    rows = rows if rows is not None else h
    log2 = math.log(2.0)
    if _NP:
        try:
            yield from _escape_rows_np(img, x0, y_top, dx, max_iter, pal, julia_c, row0, rows)
            return
        except Exception:   # a stand-in numpy in a test, or something odd: plain Python
            pass
    for y in range(row0, rows):
        ci = y_top - y * dx
        out = bytearray()
        for x in range(w):
            cr = x0 + x * dx
            if julia_c is None:
                # the big heart and the round bulb are all inside: skip the sums
                q = (cr - 0.25) ** 2 + ci * ci
                if q * (q + (cr - 0.25)) <= 0.25 * ci * ci or (cr + 1) ** 2 + ci * ci <= 0.0625:
                    out += inside
                    continue
                zr = zi = 0.0
                kr, ki = cr, ci
            else:
                zr, zi = cr, ci
                kr, ki = julia_c
            n = 0
            zr2, zi2 = zr * zr, zi * zi
            while zr2 + zi2 <= 64.0 and n < max_iter:
                zi = 2 * zr * zi + ki
                zr = zr2 - zi2 + kr
                zr2, zi2 = zr * zr, zi * zi
                n += 1
            if n >= max_iter:
                out += inside
            else:
                nu = n + 1 - math.log(math.log(zr2 + zi2) / 2 / log2) / log2
                col = pal[int(math.sqrt(max(0.0, nu)) * BANDS) % npal]
                f = nu / FADE_IN
                if f < 1.0:   # far from the set: calm and dark, colors near its edge
                    f = max(0.0, f)
                    col = bytes(int(b + (a - b) * f) for a, b in zip(col, BG))
                out += col
            if x % 64 == 63:
                yield
        i = y * w * 3
        img.data[i:i + len(out)] = out
        img.version += 1
        yield y + 1


def _escape_rows_np(img, x0, y_top, dx, max_iter, pal, julia_c, row0, rows):
    np = _np
    w = img.w
    xs = x0 + np.arange(w) * dx
    lut = np.frombuffer(b"".join(pal), dtype=np.uint8).reshape(-1, 3)
    npal = len(pal)
    chunk = 2
    y = row0
    while y < rows:
        started = time.perf_counter()
        n_rows = min(chunk, rows - y)
        ys = y_top - (y + np.arange(n_rows)) * dx
        grid = xs[None, :] + 1j * ys[:, None]
        if julia_c is None:
            c = grid
            z = np.zeros_like(c)
            q = (c.real - 0.25) ** 2 + c.imag ** 2
            done_inside = (q * (q + c.real - 0.25) <= 0.25 * c.imag ** 2) | \
                          ((c.real + 1) ** 2 + c.imag ** 2 <= 0.0625)
        else:
            c = np.full(grid.shape, complex(*julia_c))
            z = grid.copy()
            done_inside = np.zeros(grid.shape, dtype=bool)
        count = np.full(grid.shape, max_iter, dtype=np.float64)
        live = ~done_inside
        for n in range(max_iter):
            if not live.any():
                break
            zl = z[live]
            zl = zl * zl + c[live]
            z[live] = zl
            mag = zl.real * zl.real + zl.imag * zl.imag
            out = mag > 64.0
            if out.any():
                idx = np.flatnonzero(live)[out]
                m = mag[out]
                count.flat[idx] = n + 2 - np.log(np.log(m) / 2 / math.log(2)) / math.log(2)
                live.flat[idx] = False
        rgb = lut[(np.sqrt(np.maximum(count, 0)) * BANDS).astype(np.int64) % npal].astype(np.float64)
        f = np.clip(count / FADE_IN, 0.0, 1.0)[..., None]
        rgb = np.asarray(BG, dtype=np.float64) + (rgb - np.asarray(BG, dtype=np.float64)) * f
        rgb[count >= max_iter] = BG
        i = y * w * 3
        img.data[i:i + rgb.size] = rgb.astype(np.uint8).tobytes()
        img.version += 1
        y += n_rows
        took = time.perf_counter() - started
        if took < BUDGET / 4 and chunk < 32:
            chunk *= 2
        elif took > BUDGET and chunk > 1:
            chunk //= 2
        yield y


def _run(L, key, deadline, rows_key=None):
    """Run the generator L[key] until the deadline; L[key] becomes None once it's
    done. Rows finished so far go in L[rows_key]."""
    job = L[key]
    while job is not None and time.perf_counter() < deadline:
        try:
            r = next(job)
        except StopIteration:
            job = None
            break
        if r and rows_key:
            L[rows_key] = r
    L[key] = job
    return job


# ======================================================================
class Fractal:
    def __init__(self, kind: str, rng, now: float, theme: str = "", duration: float = SECONDS):
        self.kind = kind if kind in KINDS else rng.choice(kinds())
        self.rng = rng
        self.started = now
        self.theme = theme
        self.season = season(now)
        self.duration = duration
        self.L = None
        self.size = (0, 0)
        self.note = ""

    def status(self, t: float) -> str:
        if self.L is None:
            return "Drawing a fractal"
        return getattr(self, "_status_" + self.kind)(self.L, t)

    def draw(self, c, w, h, now, t, k):
        if self.L is None or (w, h) != self.size:
            self.size = (w, h)
            self.L = getattr(self, "_build_" + self.kind)(w, h)
        getattr(self, "_draw_" + self.kind)(c, w, h, t, k)
        if t > self.duration - 9:
            self._signature(c, w, h, k * min(1.0, (t - self.duration + 9) / 1.5))

    def _signature(self, c, w, h, k):
        size = max(14, int(h * 0.045))
        txt = "~ Chatty"
        c.text(txt, (w * 0.95 - c.measure(txt, size), h * 0.80), size, _mix(GOLD, k))

    # ------------------------------------------------------------ Mandelbrot
    # (name, x, y, deepest width): spots full of detail all the way down
    SPOTS = [   # each checked: still full of detail at its deepest zoom
        ("Seahorse Valley", -0.743643887037151, 0.131825904205330, 1e-5),
        ("Elephant Valley", 0.3245046418497685, 0.04855101129280834, 1e-5),
        ("a baby Mandelbrot", -1.7548776662466927, 0.0, 0.035),
        ("a spiral galaxy", -0.7746806106269039, -0.1374168856037867, 1e-5),
        ("a starfish spiral", -0.77568377, 0.13646737, 1e-5),
        ("the Double Spiral", -0.10109636384562, 0.95628651080914, 1.5e-4),
        ("the Lightning Tendrils", -1.25066, 0.02012, 6e-5),     # for the lightning node
    ]
    LEVEL_SECS = 5.5          # one magnification step
    STEP = 0.4                # each step shows 0.4 of the width before

    def _build_mandel(self, w, h):
        rng = self.rng
        res = 2 if _NP else 3
        iw, ih = max(16, w // res), max(10, int(h * PIC_H) // res)
        name, px, py, deepest = rng.choice(self.SPOTS)
        w0 = 3.6 * max(1.0, (iw / ih) / 1.6)
        view0 = (-0.7, 0.0, w0)
        pal = palette(self.theme, rng.random())
        coarse = Pixels(max(8, iw // 6), max(5, ih // 6))
        first = Pixels(iw, ih)
        L = dict(iw=iw, ih=ih, spot=name, target=(px, py), deepest=deepest, pal=pal,
                 coarse=coarse, coarse_job=_escape_rows(coarse, view0, 40, pal),
                 views=[view0], imgs=[first], job=None, shown=0, anim_from=None)
        L["job"] = _escape_rows(first, view0, 60, pal)
        return L

    def _next_view(self, L, view):
        cx, cy, vw = view
        tx, ty = L["target"]
        nw = vw * self.STEP
        g = 0.75            # also drift the spot toward the middle
        nx = tx + (cx - tx) * self.STEP * g
        ny = ty + (cy - ty) * self.STEP * g
        # keep the new view inside the old one, so magnifying the old picture works
        vh, nh = vw * L["ih"] / L["iw"], nw * L["ih"] / L["iw"]
        nx = max(cx - vw / 2 + nw / 2, min(cx + vw / 2 - nw / 2, nx))
        ny = max(cy - vh / 2 + nh / 2, min(cy + vh / 2 - nh / 2, ny))
        return (nx, ny, nw)

    def _rect_in(self, L, outer, inner):
        """Where `inner` sits in `outer`'s picture, in that picture's pixels."""
        ox, oy, ow = outer
        ix, iy, iw_ = inner
        scale = L["iw"] / ow
        oh = ow * L["ih"] / L["iw"]
        ih_ = iw_ * L["ih"] / L["iw"]
        x = (ix - iw_ / 2 - (ox - ow / 2)) * scale
        y = ((oy + oh / 2) - (iy + ih_ / 2)) * scale
        return (x, y, iw_ * scale, ih_ * scale)

    def _draw_mandel(self, c, w, h, t, k):
        L = self.L
        deadline = time.perf_counter() + BUDGET
        iw, ih = L["iw"], L["ih"]
        full = (0, 0, iw, ih)
        h = h * PIC_H          # the picture stops above her status line
        screen = (0, 0, w, h)
        _run(L, "coarse_job", deadline)      # a quick, blurry first look
        if L["shown"] == 0 and len(L["views"]) == 1:
            # the first picture paints in, top to bottom, over the blurry one
            _pixels(c, L["coarse"], (0, 0, L["coarse"].w, L["coarse"].h), screen, k)
            if _run(L, "job", deadline, "rows") is None:
                L["rows"] = ih
            done = min(ih, L.get("rows", 0))
            if done:
                _pixels(c, L["imgs"][0], (0, 0, iw, done), (0, 0, w, h * done / ih), k)
            if L["job"] is None:
                self._start_next(L, t)
            elif done < ih:
                y = h * done / ih
                c.line(_mix(FACE, k * 0.5), (0, y), (w, y), 1)    # her brush
            return
        # diving: magnify the picture she has toward the next one while working it out
        _run(L, "job", deadline)
        cur = L["shown"]
        if L["anim_from"] is not None:
            p = _ease((t - L["anim_from"]) / self.LEVEL_SECS)
            target = self._rect_in(L, L["views"][cur], L["views"][cur + 1])
            # zoom at an even pace: the width shrinks geometrically
            ratio = target[2] / iw
            wf = ratio ** p
            s = (1 - wf) / (1 - ratio) if ratio < 1 else p
            src = tuple(_lerp(a, b, s) for a, b in zip(full, target))
            src = (src[0], src[1], iw * wf, ih * wf)
            _pixels(c, L["imgs"][cur], src, screen, k)
            if p >= 1.0 and L["job"] is None:
                L["shown"] = cur + 1
                L["anim_from"] = None
                self._start_next(L, t)
        else:
            _pixels(c, L["imgs"][cur], full, screen, k)
            if L["job"] is None:
                self._start_next(L, t)

    def _start_next(self, L, t):
        cur = L["shown"]
        view = L["views"][cur]
        too_deep = view[2] * self.STEP < L["deepest"]
        if too_deep or t > self.duration - self.LEVEL_SECS - 3:
            return              # deep enough: she admires it
        nv = self._next_view(L, view)
        level = len(L["views"])
        img = Pixels(L["iw"], L["ih"])
        L["views"].append(nv)
        L["imgs"].append(img)
        # keep only the two pictures in use
        for i in range(len(L["imgs"]) - 2):
            L["imgs"][i] = None
        L["job"] = _escape_rows(img, nv, min(600, 60 + 45 * level), L["pal"])
        L["anim_from"] = t

    def _status_mandel(self, L, t):
        if len(L["views"]) == 1:
            return "Painting the Mandelbrot set - tap to stop"
        cur = L["shown"]
        w0 = L["views"][0][2]
        wide = L["views"][cur][2]
        if L["anim_from"] is not None:
            p = _ease((t - L["anim_from"]) / self.LEVEL_SECS)
            wide = wide * (L["views"][cur + 1][2] / wide) ** p
        zoom = w0 / wide
        return f"Diving into {L['spot']} - zoom x{zoom:,.0f}" if zoom >= 2 else "Into the Mandelbrot set we go"

    # ------------------------------------------------------------ Julia
    SEEDS = [(-0.8, 0.156), (-0.7269, 0.1889), (0.285, 0.01), (-0.4, 0.6),
             (-0.70176, -0.3842), (-0.835, -0.2321), (0.37, -0.1), (-0.12, 0.75)]

    def _build_julia(self, w, h):
        rng = self.rng
        res = 2 if _NP else 3
        iw, ih = max(16, w // res), max(10, int(h * PIC_H) // res)
        jc = rng.choice(self.SEEDS)
        view = (0.0, 0.0, 3.3 * max(1.0, (iw / ih) / 1.6))
        pal = palette(self.theme, rng.random())
        coarse, fine = Pixels(max(8, iw // 5), max(5, ih // 5)), Pixels(iw, ih)
        return dict(iw=iw, ih=ih, c=jc, pal=pal, coarse=coarse, fine=fine, rows=0,
                    coarse_job=_escape_rows(coarse, view, 80, pal, jc),
                    job=_escape_rows(fine, view, 160, pal, jc))

    def _draw_julia(self, c, w, h, t, k):
        L = self.L
        deadline = time.perf_counter() + BUDGET
        _run(L, "coarse_job", deadline)
        if L["job"] is not None and _run(L, "job", deadline, "rows") is None:
            L["rows"] = L["ih"]
            L["done_at"] = t
        iw, ih = L["iw"], L["ih"]
        h = h * PIC_H
        # a slow drift in once it's sharp (a gentle Ken Burns move)
        z = 1.0 + 0.25 * _ease((t - L.get("done_at", 1e9)) / 25.0)
        sw, sh = iw / z, ih / z
        src = ((iw - sw) / 2, (ih - sh) / 2, sw, sh)
        if L["job"] is not None:
            cw, ch = L["coarse"].w, L["coarse"].h
            _pixels(c, L["coarse"], (0, 0, cw, ch), (0, 0, w, h), k)
            rows = L["rows"]
            if rows:
                _pixels(c, L["fine"], (0, 0, iw, rows), (0, 0, w, h * rows / ih), k)
                y = h * rows / ih
                c.line(_mix(FACE, k * 0.5), (0, y), (w, y), 1)
        else:
            _pixels(c, L["fine"], src, (0, 0, w, h), k)

    def _status_julia(self, L, t):
        a, b = L["c"]
        sign = "+" if b >= 0 else "-"
        return f"A Julia set for c = {a:.2f} {sign} {abs(b):.2f}i"

    # ------------------------------------------------------------ Barnsley fern
    FERN = [  # (a, b, c, d, e, f, chance): Michael Barnsley's four rules
        (0.0, 0.0, 0.0, 0.16, 0.0, 0.0, 0.01),
        (0.85, 0.04, -0.04, 0.85, 0.0, 1.6, 0.85),
        (0.2, -0.26, 0.23, 0.22, 0.0, 1.6, 0.07),
        (-0.15, 0.28, 0.26, 0.24, 0.0, 0.44, 0.07),
    ]
    FERN_POINTS = 60000

    def _build_fern(self, w, h):
        rng = self.rng
        res = 2
        iw, ih = max(16, w // res), max(10, h // res)
        img = Pixels(iw, ih, smooth=False)
        scale = ih * 0.9 / 10.0
        flip = rng.choice((1, -1))
        lean = rng.uniform(-0.12, 0.12)
        theme, season_ = self.theme, self.season
        cols = []
        for i in range(64):     # color by height: stem to tip
            p = i / 63
            if theme == "valentine":
                col = (int(_lerp(170, 255, p)), int(_lerp(40, 150, p)), int(_lerp(90, 190, p)))
            elif theme == "spooky":
                col = (int(_lerp(90, 255, p)), int(_lerp(40, 140, p)), int(_lerp(120, 30, p)))
            elif theme == "storm":
                col = (int(_lerp(30, 140, p)), int(_lerp(120, 230, p)), int(_lerp(140, 240, p)))
            elif season_ == "autumn":
                col = (int(_lerp(70, 250, p)), int(_lerp(140, 170, p)), int(_lerp(40, 40, p)))
            elif season_ == "winter":
                col = (int(_lerp(40, 225, p)), int(_lerp(130, 240, p)), int(_lerp(90, 245, p)))
            else:
                col = (int(_lerp(20, 170, p)), int(_lerp(120, 255, p)), int(_lerp(40, 110, p)))
            cols.append(bytes(col))
        return dict(img=img, iw=iw, ih=ih, scale=scale, flip=flip, lean=lean, cols=cols,
                    x=0.0, y=0.0, n=0, ox=iw * rng.uniform(0.42, 0.58), oy=ih * 0.96)

    def _draw_fern(self, c, w, h, t, k):
        L = self.L
        img = L["img"]
        rng = self.rng
        want = min(self.FERN_POINTS, int(self.FERN_POINTS * min(1.0, t / 22.0) ** 1.4) + 200)
        deadline = time.perf_counter() + BUDGET
        x, y, n = L["x"], L["y"], L["n"]
        rules = self.FERN
        data, iw, ih, cols = img.data, img.w, img.h, L["cols"]
        sc, fl, lean, ox, oy = L["scale"], L["flip"], L["lean"], L["ox"], L["oy"]
        while n < want:
            for _ in range(200):
                r = rng.random()
                if r < 0.01:
                    a, b, cc, d, e, f = rules[0][:6]
                elif r < 0.86:
                    a, b, cc, d, e, f = rules[1][:6]
                elif r < 0.93:
                    a, b, cc, d, e, f = rules[2][:6]
                else:
                    a, b, cc, d, e, f = rules[3][:6]
                x, y = a * x + b * y + e, cc * x + d * y + f
                px = int(ox + (x + lean * y) * sc * fl)
                py = int(oy - y * sc)
                if 0 <= px < iw and 0 <= py < ih:
                    i = (py * iw + px) * 3
                    data[i:i + 3] = cols[min(63, int(y * 6.4))]
            n += 200
            if time.perf_counter() > deadline:
                break
        if n != L["n"]:
            img.version += 1
        L["x"], L["y"], L["n"] = x, y, n
        _pixels(c, img, (0, 0, iw, ih), (0, 0, w, h), k)

    def _status_fern(self, L, t):
        if L["n"] < self.FERN_POINTS * 0.6:
            return "Growing a fern from four tiny rules"
        if self.season == "autumn" and not self.theme:
            return "A Barnsley fern, in its autumn colors"
        return f"A Barnsley fern: {L['n']:,} dots, four rules"

    # ------------------------------------------------------------ Koch snowflake
    SNOW_LEVEL_SECS = 4.0
    SNOW_MAX = 5

    @staticmethod
    def _koch(pts, bump):
        """One more level: each edge gets a bump (bump 0 = flat, 1 = full height)."""
        out = []
        n = len(pts)
        for i in range(n):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % n]
            dx, dy = (bx - ax) / 3, (by - ay) / 3
            p1 = (ax + dx, ay + dy)
            p2 = (ax + 2 * dx, ay + 2 * dy)
            mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
            # the peak sticks outward: rotate the edge third by -90 deg, scaled sqrt(3)/2
            hx, hy = dy * 0.8660254 * bump, -dx * 0.8660254 * bump
            out += [(ax, ay), p1, (mx + hx, my + hy), p2]
        return out

    def _build_snowflake(self, w, h):
        rng = self.rng
        r = h * 0.38
        cx, cy = w / 2, h * 0.47
        # clockwise on screen (y down) so bumps point outward
        base = [(cx + r * math.cos(a), cy + r * math.sin(a))
                for a in (-math.pi / 2, math.pi / 6, math.pi * 5 / 6)]
        levels = [base]
        for _ in range(self.SNOW_MAX):
            levels.append(self._koch(levels[-1], 1.0))
        sparkles = [(rng.uniform(0, w), rng.uniform(0, h * 0.85), rng.uniform(0, 6.3)) for _ in range(30)]
        return dict(levels=levels, cx=cx, cy=cy, sparkles=sparkles, spin=rng.choice((-1, 1)))

    def _snow_level(self, t):
        x = max(0.0, t - 1.5) / self.SNOW_LEVEL_SECS
        lvl = min(self.SNOW_MAX, int(x))
        p = _ease((x - lvl) / 0.7) if lvl < self.SNOW_MAX else 1.0
        return lvl, p

    def _draw_snowflake(self, c, w, h, t, k):
        L = self.L
        lvl, p = self._snow_level(t)
        if lvl < self.SNOW_MAX and p > 0:
            pts = self._koch(L["levels"][lvl], p)
        else:
            pts = L["levels"][lvl]
        # a slow turn
        ang = L["spin"] * t * 0.02
        ca, sa = math.cos(ang), math.sin(ang)
        cx, cy = L["cx"], L["cy"]
        pts = [(cx + (x - cx) * ca - (y - cy) * sa, cy + (x - cx) * sa + (y - cy) * ca) for x, y in pts]
        if self.theme == "valentine":
            ice, edge = (70, 24, 48), (255, 160, 200)
        elif self.theme == "spooky":
            ice, edge = (40, 20, 50), (255, 160, 70)
        else:
            ice, edge = (18, 36, 60), (190, 230, 255)
        for x, y, ph in L["sparkles"]:
            a = 0.5 + 0.5 * math.sin(t * 1.7 + ph)
            if a > 0.6:
                r = 1.5 + a
                c.ellipse(_mix((220, 235, 255), k * (a - 0.6) * 2), (x - r, y - r, 2 * r, 2 * r))
        c.polygon(_mix(ice, k), pts)
        _polyline_closed(c, _mix(edge, k), pts, max(1, int(h * 0.004)))
        L["shown"] = lvl

    def _status_snowflake(self, L, t):
        lvl, _ = self._snow_level(t)
        if lvl >= self.SNOW_MAX and t > 1.5 + self.SNOW_MAX * self.SNOW_LEVEL_SECS + 2:
            return "Endless edge, but it never gets any bigger"
        sides = 3 * 4 ** lvl
        return f"Koch snowflake, step {lvl}: {sides:,} sides"

    # ------------------------------------------------------------ fractal tree
    TREE_DEPTH = 8
    TREE_SECS = 1.3      # per level of branches

    def _build_tree(self, w, h):
        rng = self.rng
        spread = rng.uniform(0.38, 0.55)
        shrink = rng.uniform(0.68, 0.74)
        # every branch gets its own small quirks, so it looks grown, not printed
        quirks = [rng.uniform(-0.12, 0.12) for _ in range(2 ** (self.TREE_DEPTH + 1))]
        lens = [rng.uniform(0.85, 1.1) for _ in range(2 ** (self.TREE_DEPTH + 1))]
        falling = [(rng.uniform(0, w), rng.uniform(0, 1), rng.uniform(0.6, 1.4), rng.uniform(0, 6.3))
                   for _ in range(14)]
        return dict(spread=spread, shrink=shrink, quirks=quirks, lens=lens, x=w / 2, y=h * 0.93,
                    trunk=h * 0.24, falling=falling, phase=rng.uniform(0, 6.3))

    def _tree_colors(self):
        s = self.season if not self.theme else self.theme
        bark = (120, 86, 60)
        return bark, {
            "spring": [(255, 182, 210), (255, 220, 235), (250, 150, 190)],
            "summer": [(80, 190, 90), (120, 220, 100), (60, 160, 80)],
            "autumn": [(240, 120, 40), (250, 190, 50), (200, 60, 40), (230, 150, 60)],
            "winter": [(235, 242, 255)],
            "valentine": [(255, 90, 140), (255, 150, 190), (230, 40, 90)],
            "spooky": [(255, 140, 30), (150, 60, 200), (90, 220, 90)],
            "storm": [(90, 200, 220), (60, 160, 200), (140, 220, 210)],
        }.get(s, [(80, 190, 90)])

    def _draw_tree(self, c, w, h, t, k):
        L = self.L
        grow = max(0.0, t - 0.8) / self.TREE_SECS     # how many levels have grown
        sway = 0.035 * math.sin(t * 0.9 + L["phase"])
        bark, leaves = self._tree_colors()
        by_depth = [[] for _ in range(self.TREE_DEPTH + 1)]
        tips = []
        # (x, y, angle, length, depth, id)
        stack = [(L["x"], L["y"], -math.pi / 2, L["trunk"], 0, 1)]
        while stack:
            x, y, a, ln, d, i = stack.pop()
            p = max(0.0, min(1.0, grow - d))
            if p <= 0:
                continue
            a2 = a + sway * d * 0.5 + L["quirks"][i] * 0.5
            ex, ey = x + math.cos(a2) * ln * p, y + math.sin(a2) * ln * p
            by_depth[d].append(((x, y), (ex, ey)))
            if d == self.TREE_DEPTH or p < 1.0:
                if d >= self.TREE_DEPTH - 1 and p >= 1.0:
                    tips.append((ex, ey, i))
                continue
            nl = ln * L["shrink"]
            for side, child in ((-1, 2 * i), (1, 2 * i + 1)):
                stack.append((ex, ey, a2 + side * L["spread"] + L["quirks"][child], nl * L["lens"][child],
                               d + 1, child))
        for d, segs in enumerate(by_depth):
            if segs:
                width = max(1, int(h * 0.03 * (0.72 ** d)))
                col = _mix(tuple(int(v * (1 - 0.04 * d)) for v in bark), k)
                _segments(c, col, segs, width)
        # leaves, blossoms or snow on the tips once the tree is grown
        bloom = max(0.0, min(1.0, grow - self.TREE_DEPTH - 0.3))
        if bloom > 0:
            r = max(2.0, h * 0.009) * bloom * (0.6 if leaves == [(235, 242, 255)] else 1.0)
            for x, y, i in tips:
                col = leaves[i % len(leaves)]
                c.ellipse(_mix(col, k), (x - r, y - r * 0.8, 2 * r, 1.6 * r))
        if bloom >= 1 and (self.season in ("autumn", "winter", "spring") or self.theme):
            # a few leaves (or petals, or snowflakes) drifting down
            for fx, fy0, sp, ph in L["falling"]:
                fy = ((fy0 + (t - 12) * 0.04 * sp) % 1.0) * h * 0.9
                x = fx + math.sin(t * sp + ph) * 14
                r = max(2.0, h * 0.008)
                col = leaves[int(ph * 10) % len(leaves)]
                c.ellipse(_mix(col, k * 0.8), (x - r, fy - r * 0.7, 2 * r, 1.4 * r))
        L["grown"] = bloom >= 1

    def _status_tree(self, L, t):
        if not L.get("grown"):
            return "Growing a fractal tree - every branch is a small tree"
        if self.theme == "valentine":
            return "A tree full of love"
        return {"spring": "Spring blossoms on my fractal tree",
                "summer": "A fractal tree on a summer day",
                "autumn": "Autumn on my fractal tree. The leaves are letting go",
                "winter": "A winter tree, dusted with snow"}.get(self.season, "My fractal tree")

    # ------------------------------------------------------------ dragon curve
    DRAGON_FOLDS = 11
    FOLD_SECS = 2.6

    def _draw_dragon(self, c, w, h, t, k):
        L = self.L
        x = max(0.0, t - 1.0) / self.FOLD_SECS
        fold = min(self.DRAGON_FOLDS, int(x))
        p = _ease((x - fold) / 0.75) if fold < self.DRAGON_FOLDS else 0.0
        pts = L["curves"][fold]
        if p > 0:
            # the copy swings around the last point, like unfolding paper
            ex, ey = pts[-1]
            a = -L["turn"] * math.pi / 2 * p
            ca, sa = math.cos(a), math.sin(a)
            back = [(ex + (px - ex) * ca - (py - ey) * sa, ey + (px - ex) * sa + (py - ey) * ca)
                    for px, py in reversed(pts[:-1])]
            pts = pts + back
            box = _box_lerp(L["boxes"][fold], L["boxes"][min(fold + 1, self.DRAGON_FOLDS)], p)
        else:
            box = L["boxes"][fold]
        x0, y0, x1, y1 = box
        s = min(w * 0.86 / max(1e-9, x1 - x0), h * 0.74 / max(1e-9, y1 - y0))
        ox = w / 2 - (x0 + x1) / 2 * s
        oy = h * 0.45 - (y0 + y1) / 2 * s
        scr = [(ox + px * s, oy + py * s) for px, py in pts]
        chunks = 24
        step = max(1, len(scr) // chunks)
        width = max(1, min(4, int(s * 0.25)))
        for i in range(0, len(scr) - 1, step):
            col = L["pal"][int(i / len(scr) * (len(L["pal"]) - 1))]
            _poly(c, _mix(col, k), scr[i:i + step + 1], width)
        L["fold"] = fold

    def _build_dragon(self, w, h):
        rng = self.rng
        turn = rng.choice((1, -1))
        curves = [[(0.0, 0.0), (1.0, 0.0)]]
        for _ in range(self.DRAGON_FOLDS):
            pts = curves[-1]
            ex, ey = pts[-1]
            # rotate the reversed copy 90 degrees around the end point
            back = [(ex + (py - ey) * turn, ey - (px - ex) * turn) for px, py in reversed(pts[:-1])]
            curves.append(pts + back)
        boxes = []
        for pts in curves:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
        hue = rng.random()
        if self.theme == "valentine":
            pal = [tuple(int(v * 255) for v in colorsys.hsv_to_rgb(0.93 + 0.05 * i / 31, 0.6, 1.0)) for i in range(32)]
        elif self.theme == "spooky":
            pal = [tuple(int(v * 255) for v in colorsys.hsv_to_rgb(0.03 + 0.08 * i / 31, 0.85, 1.0)) for i in range(32)]
        else:
            pal = [tuple(int(v * 255) for v in colorsys.hsv_to_rgb((hue + 0.6 * i / 31) % 1, 0.6, 1.0)) for i in range(32)]
        return dict(curves=curves, boxes=boxes, turn=turn, pal=pal, fold=0)

    def _status_dragon(self, L, t):
        fold = L.get("fold", 0)
        if fold >= self.DRAGON_FOLDS:
            return f"Fold a strip of paper {self.DRAGON_FOLDS} times and you get a dragon"
        return f"Folding the dragon curve: fold {fold + 1}"


def _poly(c, color, pts, width):
    if len(pts) < 2:
        return
    fn = getattr(c, "polyline", None)
    if fn:
        fn(color, pts, width)
    else:
        for a, b in zip(pts, pts[1:]):
            c.line(color, a, b, width)


def _polyline_closed(c, color, pts, width):
    _poly(c, color, list(pts) + [pts[0]], width)


def _box_lerp(a, b, p):
    return tuple(_lerp(x, y, p) for x, y in zip(a, b))

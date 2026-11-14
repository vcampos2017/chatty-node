"""Fractal doodles: every kind draws, stays light on the Pi, and voice requests."""
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_GAMES"] = "0"
os.environ["CHATTY_CHESS"] = "0"
os.environ["CHATTY_TRICKSTER"] = "0"
os.environ["CHATTY_NIGHT_MODE"] = "0"
import doodles  # noqa: E402
import fractals  # noqa: E402
from face_model import FaceModel  # noqa: E402

T = 1_000_000.0


class Recorder:
    """Counts drawing calls; checks every picture shown stays inside itself."""

    def __init__(self):
        self.calls = 0
        self.texts = []
        self.pics = []

    def pixels(self, img, src, dst, alpha=1.0):
        self.calls += 1
        sx, sy, sw, sh = src
        assert sw > 0 and sh > 0
        assert -0.01 <= sx and sx + sw <= img.w + 0.01, (src, img.w)
        assert -0.01 <= sy and sy + sh <= img.h + 0.01, (src, img.h)
        assert len(img.data) == img.w * img.h * 3
        assert 0 <= alpha <= 1
        self.pics.append((img, src, dst))

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls += 1
            if name == "text":
                self.texts.append(args[0])
            return 10
        return call


def _run(kind, seconds=None, fps=4, seed=3):
    d = doodles.Doodle(random.Random(seed), T, kind)
    slowest, frames = 0.0, []
    end = seconds if seconds is not None else d.duration
    for i in range(int(end * fps)):
        c = Recorder()
        started = time.perf_counter()
        d.draw(c, 800, 480, T + i / fps)
        slowest = max(slowest, time.perf_counter() - started)
        assert c.calls < 900, (kind, c.calls)        # cheap for the Pi
        frames.append(c)
    return d, frames, slowest


def test_every_fractal_draws_a_whole_piece_and_signs_it():
    for kind in fractals.KINDS:
        d, frames, slowest = _run(kind)
        assert d.style == kind and d.fractal.kind == kind
        assert slowest < 0.3, (kind, slowest)        # each frame is a small step
        assert "~ Chatty" in frames[-1].texts
        assert d.status(T + d.duration - 5)
        d.update(T + d.duration + 1)
        assert d.done


def test_mandelbrot_paints_then_dives_deeper():
    d, frames, _ = _run("mandel", seconds=45, fps=15)
    L = d.fractal.L
    assert len(L["views"]) >= 3, len(L["views"])          # it went past the first picture
    widths = [v[2] for v in L["views"]]
    assert all(b < a for a, b in zip(widths, widths[1:]))  # always deeper
    status = d.status(T + 44)
    assert "zoom x" in status or "Mandelbrot" in status, status
    # each new view sits inside the one before (so magnifying the old picture works)
    for a, b in zip(L["views"], L["views"][1:]):
        x, y, w, h = d.fractal._rect_in(L, a, b)
        assert x >= -1e-6 and y >= -1e-6 and x + w <= L["iw"] + 1e-6 and y + h <= L["ih"] + 1e-6
    shown = [p for f in frames for p in f.pics]
    assert any(src[2] < p[0].w * 0.9 for p in shown for src in [p[1]])   # it magnified


def test_picture_has_the_set_and_colors():
    img = fractals.Pixels(80, 42)
    for _ in fractals._escape_rows(img, (-0.7, 0.0, 3.6), 60, fractals.palette("", 0.3)):
        pass
    px = [bytes(img.data[i:i + 3]) for i in range(0, len(img.data), 3)]
    inside = px.count(bytes(fractals.BG)) / len(px)
    assert 0.1 < inside < 0.5, inside
    assert len(set(px)) > 20


def test_plain_python_and_numpy_agree():
    if not fractals._NP:
        return
    pal = fractals.palette("", 0.1)
    view = (-0.743, 0.1318, 0.05)
    pics = []
    for use_np in (True, False):
        fractals._NP = use_np
        img = fractals.Pixels(60, 32)
        for _ in fractals._escape_rows(img, view, 120, pal):
            pass
        pics.append(img.data)
    fractals._NP = True
    same = sum(1 for i in range(0, len(pics[0]), 3) if pics[0][i:i + 3] == pics[1][i:i + 3])
    assert same / (len(pics[0]) // 3) > 0.9


def test_julia_status_names_its_number():
    d, _, _ = _run("julia", seconds=20)
    assert "Julia set for c =" in d.status(T + 19)


def test_seasons_and_themes():
    assert fractals.season(time.mktime((2026, 11, 14, 12, 0, 0, 0, 0, -1))) == "autumn"
    assert fractals.season(time.mktime((2026, 4, 2, 12, 0, 0, 0, 0, -1))) == "spring"
    assert fractals.season(time.mktime((2026, 1, 2, 12, 0, 0, 0, 0, -1))) == "winter"
    for theme in ("", "valentine", "spooky", "storm"):
        assert len(fractals.palette(theme, 0.2)) == 256


def test_spoken_requests():
    r = fractals.request
    assert r("draw a fractal") == ""
    assert r("show me a fractal please") == ""
    assert r("fractals") == ""
    assert r("show me the mandelbrot set") == "mandel"
    assert r("zoom into the mandelbrot set") == "mandel"
    assert r("draw a julia set") == "julia"
    assert r("draw a fern") == "fern"
    assert r("grow a barnsley fern") == "fern"
    assert r("draw a snowflake") == "snowflake"
    assert r("draw a koch snowflake") == "snowflake"
    assert r("grow a fractal tree") == "tree"
    assert r("draw a dragon curve") == "dragon"
    # not requests
    assert r("what is a fractal") is None
    assert r("how is my fern doing") is None
    assert r("is it going to snow") is None
    assert r("imagine a dragon") is None
    assert r("draw something") is None
    assert r("the tree fell over") is None


def test_explains_fractals_locally():
    assert "repeats inside itself" in fractals.explain("what is a fractal")
    assert "Mandelbrot" in fractals.explain("what's the mandelbrot set")
    assert "Gaston Julia" in fractals.explain("tell me about julia sets")
    assert fractals.explain("draw a fractal") is None
    assert fractals.explain("what time is it") is None


def test_face_starts_a_fractal_and_a_tap_stops_it():
    face = FaceModel(800, 480, rng=random.Random(2))
    face.last_activity = T
    assert face.start_doodle("fractal", now=T)
    assert face.doodle.style in fractals.KINDS
    assert face.activity() == "doodle:" + face.doodle.style
    face.draw(Recorder(), T + 1)
    assert face.handle_tap((400, 240), now=T + 2) is True
    assert face.doodle is None
    assert face.start_doodle("mandel", now=T)
    assert face.activity() == "doodle:mandel"


def test_style_settings():
    os.environ["CHATTY_DOODLE_STYLES"] = "fractal"
    try:
        for seed in range(5):
            assert doodles.Doodle(random.Random(seed), T).style in fractals.KINDS
        os.environ["CHATTY_DOODLE_STYLES"] = "fern"
        assert doodles.Doodle(random.Random(1), T).style == "fern"
    finally:
        del os.environ["CHATTY_DOODLE_STYLES"]
    os.environ["CHATTY_FRACTALS"] = "tree"
    try:
        assert doodles.Doodle(random.Random(1), T, "fractal").style == "tree"
    finally:
        del os.environ["CHATTY_FRACTALS"]


def test_works_without_a_pixels_canvas():
    class Plain:
        def __getattr__(self, name):
            if name == "pixels":
                raise AttributeError(name)
            return lambda *a, **k: 10
    for kind in fractals.KINDS:
        d = doodles.Doodle(random.Random(1), T, kind)
        for i in range(20):
            d.draw(Plain(), 800, 480, T + i)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

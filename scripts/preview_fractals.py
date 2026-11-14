"""
Preview Chatty's fractal doodles as PNGs (Pillow, no pygame needed).
Usage: python3 scripts/preview_fractals.py [output_dir] [kind ...]

Each kind is drawn the way her face would, frame by frame, and saved a little
before it ends; the Mandelbrot dive also gets a picture from the start. A
contact sheet of all of them goes in fractals-sheet.png.
"""
import os
import random
import sys
import time

from PIL import Image

os.environ.setdefault("CHATTY_NIGHT_MODE", "0")          # full colors, whatever time it is
os.environ.setdefault("CHATTY_FRACTAL_BUDGET_MS", "400")  # no hurry here: not on the Pi
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
import fractals  # noqa: E402
from face_model import FaceModel  # noqa: E402
from preview_face import PILCanvas  # noqa: E402

W, H = 800, 480
T = time.time()     # today's season (the fern and the tree follow it)
FPS = 15


class Null:
    """A canvas that draws nothing (for the frames in between)."""

    def __getattr__(self, name):
        return lambda *a, **k: 10


def frames(kind, at_seconds, seed=7):
    face = FaceModel(W, H, rng=random.Random(seed))
    face.set_rec("off")
    face.next_blink = 1e12
    face.last_activity = T
    face.start_doodle(kind, now=T)
    shots = []
    steps = int(max(at_seconds) * FPS) + 1
    for i in range(steps):
        now = T + i / FPS
        face.update(1 / FPS, now)
        if any(abs(i / FPS - s) < 0.5 / FPS for s in at_seconds):
            c = PILCanvas(W, H)
            face.draw(c, now)
            shots.append(c.image())
        else:
            face.draw(Null(), now)
    return shots


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    kinds = sys.argv[2:] or list(fractals.KINDS)
    os.makedirs(out, exist_ok=True)
    end = fractals.SECONDS - 3
    sheet = []
    for kind in kinds:
        at = [6.0, end] if kind == "mandel" else [end]
        shots = frames(kind, at)
        for s, img in zip(at, shots):
            name = f"fractal-{kind}.png" if s == end else f"fractal-{kind}-start.png"
            img.save(os.path.join(out, name))
            print("wrote", os.path.join(out, name))
        sheet.append(shots[-1])
    if len(sheet) > 1:
        cols = 3
        rows = (len(sheet) + cols - 1) // cols
        tw, th = W // 2, H // 2
        board = Image.new("RGB", (cols * tw, rows * th), (8, 10, 14))
        for i, img in enumerate(sheet):
            board.paste(img.resize((tw, th), Image.LANCZOS), ((i % cols) * tw, (i // cols) * th))
        path = os.path.join(out, "fractals-sheet.png")
        board.save(path)
        print("wrote", path)


if __name__ == "__main__":
    main()

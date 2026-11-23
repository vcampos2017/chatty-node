"""
Preview Chatty's season days as PNGs (Pillow, no pygame): the first day of summer (sunglasses,
the sun and seagulls), the money breeze (Chatty Bucks blowing across her screen), the summer
shuffle at her piano, and the first days of spring, fall and winter. Also writes the Sunny Day
Shuffle as a .wav.
Usage: python3 scripts/preview_seasons.py [output_dir]
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("CHATTY_NIGHT_MODE", "0")    # full colors, whatever time it is
os.environ.pop("CHATTY_FORCE_THANKSGIVING", None)
import piano  # noqa: E402
import seasons  # noqa: E402
from face_model import FaceModel  # noqa: E402
from preview_face import PILCanvas  # noqa: E402

W, H = 800, 480
T = 1_000_000.0


def frame(state, season, seconds=6.0, bills_at=None, song=None):
    os.environ["CHATTY_FORCE_SEASON"] = season
    face = FaceModel(W, H, rng=random.Random(7))
    face.set_rec("off")
    face.next_blink = 1e12
    face.set_state(state, now=T)
    if song:
        face.set_piano(f"{T}:{song}", now=T)
    if bills_at is not None:
        face.set_season("bills", now=T + seconds - bills_at)
    steps = max(1, int(seconds * 30))
    for i in range(steps + 1):
        face.update(1 / 30, T + i * seconds / steps)
    c = PILCanvas(W, H)
    face.draw(c, T + seconds)
    return c.image()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "seasons_preview"
    os.makedirs(out, exist_ok=True)
    shots = [("summer-idle.png", dict(state="idle", season="summer", seconds=6.0)),
             ("summer-money-breeze.png", dict(state="speaking", season="summer", seconds=8.0, bills_at=6.5)),
             ("summer-piano.png", dict(state="piano", season="summer", seconds=7.0, song=seasons.SONG)),
             ("spring.png", dict(state="idle", season="spring", seconds=12.0)),
             ("fall.png", dict(state="idle", season="autumn", seconds=12.0)),
             ("winter.png", dict(state="idle", season="winter", seconds=12.0))]
    for name, kw in shots:
        path = os.path.join(out, name)
        frame(**kw).save(path)
        print("wrote", path)
    print("wrote", piano.write_wav(piano.load(seasons.SONG), os.path.join(out, "sunny-day-shuffle.wav")))

"""
Preview Chatty's Thanksgiving face as PNGs (Pillow, no pygame): her buckled hat and the
autumn leaves, a golden thank-you leaf ("I'm thankful for pie"), and the hat at her piano
during the Harvest Thank-You Waltz. Also writes the waltz as a .wav.
Usage: python3 scripts/preview_thanksgiving.py [output_dir]
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("CHATTY_NIGHT_MODE", "0")    # full colors, whatever time it is
os.environ["CHATTY_FORCE_THANKSGIVING"] = "1"
import piano  # noqa: E402
import thanksgiving  # noqa: E402
from face_model import FaceModel  # noqa: E402
from preview_face import PILCanvas  # noqa: E402

W, H = 800, 480
T = 1_000_000.0


def frame(state, seconds=6.0, thanks=None, song=None):
    face = FaceModel(W, H, rng=random.Random(5))
    face.set_rec("off")
    face.next_blink = 1e12
    face.set_state(state, now=T)
    if song:
        face.set_piano(f"{T}:{song}", now=T)
    if thanks:
        face.add_thanks(thanks, now=T + seconds - 3.0)
    steps = max(1, int(seconds * 30))
    for i in range(steps + 1):
        face.update(1 / 30, T + i * seconds / steps)
    c = PILCanvas(W, H)
    face.draw(c, T + seconds)
    return c.image()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "thanksgiving_preview"
    os.makedirs(out, exist_ok=True)
    shots = [("thanksgiving-idle.png", dict(state="idle", seconds=8.0)),
             ("thanksgiving-thankful.png", dict(state="love_talk", seconds=8.0, thanks="pie")),
             ("thanksgiving-piano.png", dict(state="piano", seconds=9.0, song=thanksgiving.SONG))]
    for name, kw in shots:
        path = os.path.join(out, name)
        frame(**kw).save(path)
        print("wrote", path)
    print("wrote", piano.write_wav(piano.load(thanksgiving.SONG), os.path.join(out, "harvest-waltz.wav")))

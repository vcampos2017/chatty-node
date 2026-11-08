"""
Render "Who's the Trickster?" (src/trickster.py) to PNG without pygame (uses Pillow):
the yard with the nodes at their chores, the tea meeting vote and the reveal.
Usage: python3 scripts/preview_trickster.py [output_dir] [seed]
"""
import os
import random
import sys
import tempfile

os.environ.setdefault("CHATTY_NIGHT_MODE", "0")
os.environ["CHATTY_TRICKSTER_SCORES"] = os.path.join(tempfile.mkdtemp(), "trickster.json")  # not her real score
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from PIL import Image  # noqa: E402

from face_model import FaceModel  # noqa: E402
from preview_face import PILCanvas  # noqa: E402

W, H = 800, 480


def shoot(face, now):
    c = PILCanvas(W, H)
    face.draw(c, now)
    return c.image()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "trickster_preview"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    os.makedirs(out, exist_ok=True)
    face = FaceModel(W, H, rng=random.Random(seed))
    face.next_blink = 1e12
    t = 1000.0
    face.start_mystery(human=True, now=t)
    g = face.mystery
    g.tiny_at = 18.0                      # make sure Tiny strolls through for the picture
    shots = {}
    while not g.done and t < 1400:
        t += 1 / 15
        face.update(1 / 15, t)
        if "yard" not in shots and len(g.clues) == 2 and g.t - g.clues[-1]["t"] > 1.5:
            shots["yard"] = shoot(face, t)
        if "vote" not in shots and g.phase == "vote" and len(g.shown_ballots()) >= 3:
            g.vote(g.trickster)           # you tap the right one
            shots["vote"] = shoot(face, t)
        if "reveal" not in shots and g.phase == "reveal" and g.t - g.phase_at > 1.2:
            shots["reveal"] = shoot(face, t)
    for k, img in shots.items():
        img.save(os.path.join(out, f"trickster-{k}.png"))
    sheet = Image.new("RGB", (W, H * len(shots) + 8 * (len(shots) - 1)), (30, 30, 34))
    for i, k in enumerate(("yard", "vote", "reveal")):
        if k in shots:
            sheet.paste(shots[k], (0, i * (H + 8)))
    sheet.save(os.path.join(out, "trickster-preview.png"))
    print("saved to", out, "- trickster was", g.trickster)


if __name__ == "__main__":
    main()

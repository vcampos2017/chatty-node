"""
Preview Chatty's imagination mood and a daydream as PNGs (Pillow, no pygame).
Usage: python3 scripts/preview_imagine.py [output_dir]
"""
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("CHATTY_NIGHT_MODE", "0")    # full colors, whatever time it is
import imagine  # noqa: E402
from face_model import FaceModel  # noqa: E402
from preview_face import PILCanvas  # noqa: E402

W, H = 800, 480
T = 1_000_000.0


def mood(state, seconds, level=0.0, caption="imagine a dragon"):
    face = FaceModel(W, H, rng=random.Random(5))
    face.set_rec("off")
    face.next_blink = 1e12
    face.set_caption(caption, now=T)
    face.set_state(state, now=T)
    face.set_level(level)
    steps = max(1, int(seconds * 30))
    for i in range(steps):
        face.update(1 / 30, T + i / 30)
    c = PILCanvas(W, H)
    face.draw(c, T + seconds)
    return c.image()


def daydream(seconds, topic=""):
    face = FaceModel(W, H, rng=random.Random(11))
    face.next_blink = 1e12
    face.last_activity = T
    face.start_daydream(topic, now=T)
    for i in range(int(seconds * 15)):
        face.update(1 / 15, T + i / 15)
    c = PILCanvas(W, H)
    face.draw(c, T + seconds)
    return c.image()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "imagine_preview"
    os.makedirs(out, exist_ok=True)
    shots = [("1. hands start the sweep", mood("imagine", 0.25)),
             ("2. the rainbow opens", mood("imagine", 0.6)),
             ("3. Imagine!", mood("imagine", 2.0)),
             ("4. telling you the idea", mood("imagine_talk", 2.5, level=0.6)),
             ("5. bored: a daydream", daydream(4.0)),
             ("6. daydream, typed out", daydream(14.0))]
    tw, th = 400, 240
    sheet = Image.new("RGB", (tw * 3, (th + 30) * 2), (30, 30, 34))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        f = ImageFont.load_default()
    for i, (label, img) in enumerate(shots):
        img.save(os.path.join(out, f"imagine_{i + 1}.png"))
        x, y = (i % 3) * tw, (i // 3) * (th + 30)
        sheet.paste(img.resize((tw - 8, th - 8)), (x + 4, y + 4))
        d.text((x + 10, y + th), label, fill=(200, 200, 200), font=f)
    sheet.save(os.path.join(out, "imagine-preview.png"))
    print("saved to", out)

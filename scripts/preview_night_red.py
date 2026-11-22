"""
Pictures of the red night-vision glow (night_red.py), with Pillow (no pygame).
Usage: python3 scripts/preview_night_red.py [output_dir]
Makes one sheet: her daytime colors, the red glow (idle, talking, sleepy with a
notice), and Red Alert, which always shows in its own colors.
"""
import os
import random
import sys
import time

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import night_red  # noqa: E402
from face_model import FaceModel  # noqa: E402
from preview_face import PILCanvas  # noqa: E402


def shot(state, level=0.0, notice="", caption="", red_alert=False, t=None):
    t = t or time.time()
    face = FaceModel(800, 480, rng=random.Random(3))
    face.next_blink = 1e12
    face.set_state(state, now=t)
    face.set_level(level)
    if notice:
        face.add_notice(notice, now=t)
    if caption:
        face.set_caption(caption, now=t)
    if red_alert:
        face.set_red_alert(f"{int(t + 1800)}::Tornado Warning", now=t)
    for i in range(60):
        face.update(1 / 30, t + i / 30)
    c = PILCanvas(800, 480)
    face.draw(c, t + 2.4)
    return c.image()


def redden(img, brightness=1.0):
    """The glow, and roughly how bright the screen is (the backlight)."""
    try:
        import numpy as np
        a = np.array(img.convert("RGB"))
        night_red.red_array(a)
        img = Image.fromarray(a)
    except ImportError:
        img = img.convert("RGB")
        img.putdata([night_red.redden_rgb(*p) for p in img.getdata()])
    if brightness < 1:
        img = img.point(lambda v: int(v * brightness))
    return img


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "night_red_preview"
    os.makedirs(out, exist_ok=True)
    tiles = [
        ("Daytime colors", shot("idle")),
        ("Night: red glow (idle)", redden(shot("idle"), 0.75)),
        ("Night: talking (screen at 40%)", redden(shot("speaking", 0.6, caption="what time is it"), 0.85)),
        ("Night: sleepy + a notice", redden(shot("sleepy", notice="I moved to the other WiFi"), 0.6)),
        ("Night: resting", redden(shot("resting"), 0.5)),
        ("Red Alert always wins (full color)", shot("listening", red_alert=True)),
    ]
    tw, th = 400, 240
    sheet = Image.new("RGB", (tw * 3, (th + 34) * 2), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 17)
    except OSError:
        f = ImageFont.load_default()
    for i, (label, img) in enumerate(tiles):
        x, y = (i % 3) * tw, (i // 3) * (th + 34)
        sheet.paste(img.resize((tw - 8, th - 8)), (x + 4, y + 4))
        d.text((x + 10, y + th + 4), label, fill=(210, 210, 210), font=f)
        img.save(os.path.join(out, f"night-red-{i}.png"))
    sheet.save(os.path.join(out, "night-red-sheet.png"))
    print("saved to", out)

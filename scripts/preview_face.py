"""
Render Chatty's face states to PNG images without pygame (uses Pillow).
Usage: python3 scripts/preview_face.py [output_dir]
"""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from face_model import FaceModel  # noqa: E402

SCALE = 2  # draw at 2x and shrink, for smooth edges


class PILCanvas:
    def __init__(self, w, h):
        self.img = Image.new("RGB", (w * SCALE, h * SCALE))
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def _box(rect):
        x, y, w, h = rect
        return [x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE]

    def fill(self, color):
        self.d.rectangle([0, 0, *self.img.size], fill=color)

    def rrect(self, color, rect, radius):
        self.d.rounded_rectangle(self._box(rect), radius=radius * SCALE, fill=color)

    def ellipse(self, color, rect, width=0):
        if width:
            self.d.ellipse(self._box(rect), outline=color, width=width * SCALE)
        else:
            self.d.ellipse(self._box(rect), fill=color)

    def arc(self, color, rect, start, stop, width):
        # pygame angles: radians, counter-clockwise; Pillow: degrees, clockwise
        self.d.arc(self._box(rect), -math.degrees(stop), -math.degrees(start), fill=color, width=width * SCALE)

    def line(self, color, p1, p2, width):
        a, b = [v * SCALE for v in p1], [v * SCALE for v in p2]
        self.d.line([*a, *b], fill=color, width=width * SCALE)
        r = width * SCALE / 2
        for p in (a, b):
            self.d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)

    @staticmethod
    def _font(size):
        try:
            return ImageFont.truetype("DejaVuSans-Bold.ttf", size * SCALE)
        except OSError:
            return ImageFont.load_default()

    def text(self, txt, pos, size, color):
        self.d.text((pos[0] * SCALE, pos[1] * SCALE), txt, fill=color, font=self._font(size))

    def measure(self, txt, size):
        return self.d.textlength(txt, font=self._font(size)) / SCALE

    def image(self):
        return self.img.resize((self.img.width // SCALE, self.img.height // SCALE), Image.LANCZOS)


def render(state, level=0.0, t=1000.0, w=800, h=480, caption="", listen=None, rec="full"):
    face = FaceModel(w, h, rng=random.Random(3))
    face.set_rec(rec)
    face.next_blink = 1e12  # no blink in stills
    face.set_state(state, now=t)
    face.set_level(level)
    if caption:
        face.set_caption(caption)
    if listen:
        face.set_listen(listen[0], now=t + 2 - (listen[0] - listen[1]))  # (total, remaining)
    for i in range(60):  # let transitions settle
        face.update(1 / 30, t + i / 30)
    c = PILCanvas(w, h)
    face.draw(c, t + 2.4)
    return c.image()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "face_preview"
    os.makedirs(out, exist_ok=True)
    shots = [("idle", 0, "", None), ("listening", 0, "what time is", (8, 5)),
             ("thinking", 0, "what time is it", None), ("speaking", 0.75, "what time is it", None),
             ("puzzled", 0, "", None), ("sleepy", 0, "", None),
             ("mischief", 0, "be cheeky", None), ("mischief_talk", 0.6, "tell me a joke", None),
             ("resting", 0, "", None)]
    tiles = []
    for state, level, caption, listen in shots:
        img = render(state, level, caption=caption, listen=listen)
        img.save(os.path.join(out, f"{state}.png"))
        tiles.append((state, img))
    # contact sheet
    tw, th = 400, 240
    sheet = Image.new("RGB", (tw * 3, (th + 30) * 3), (30, 30, 34))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        f = ImageFont.load_default()
    for i, (state, img) in enumerate(tiles):
        x, y = (i % 3) * tw, (i // 3) * (th + 30)
        sheet.paste(img.resize((tw - 8, th - 8)), (x + 4, y + 4))
        d.text((x + 10, y + th), state, fill=(200, 200, 200), font=f)
    sheet.save(os.path.join(out, "all_states.png"))
    print("saved to", out)

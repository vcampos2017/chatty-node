#!/usr/bin/env python3
"""Draw what the Matrix node's 64x32 panel would show, as PNGs (needs Pillow).

    python3 scripts/preview_matrix.py [out_dir] [fonts_dir]

fonts_dir: a folder with the board's BDF fonts (6x10.bdf, helvR10.bdf, helvB12.bdf, as
on the CIRCUITPY drive's fonts folder) for a closer look; without it Pillow's own font
stands in.

Runs the real screen code (matrix_node/CIRCUITPY) on the stand-ins in
matrix_node/sim, then paints each lit pixel as a round LED. Fonts are only close to
the real BDF ones and the moon is a drawn disc (the board uses its own moon pictures).
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "matrix_node", "CIRCUITPY"))
sys.path.insert(0, os.path.join(ROOT, "matrix_node", "sim"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import fake_circuitpython as fake  # noqa: E402

fake.install({})
import chatty_clock as clock  # noqa: E402
import chatty_news as news  # noqa: E402
import chatty_screen  # noqa: E402

DOT = 10


BDF = {}


def _bdf(fonts_dir):
    """Read the board's BDF fonts (a small reader: ENCODING, DWIDTH, BBX, BITMAP)."""
    for name in ("6x10", "helvR10", "helvB12"):
        path = os.path.join(fonts_dir, name + ".bdf")
        if not os.path.exists(path):
            continue
        glyphs, cur, rows, ascent = {}, None, None, 8
        with open(path, encoding="latin-1") as fh:
            for line in fh:
                parts = line.split()
                if not parts:
                    continue
                key = parts[0]
                if key == "FONT_ASCENT":
                    ascent = int(parts[1])
                elif key == "ENCODING":
                    cur = {"code": int(parts[1])}
                elif key == "DWIDTH" and cur is not None:
                    cur["adv"] = int(parts[1])
                elif key == "BBX" and cur is not None:
                    cur["bbx"] = [int(x) for x in parts[1:5]]
                elif key == "BITMAP" and cur is not None:
                    rows = []
                elif key == "ENDCHAR" and cur is not None:
                    cur["rows"] = rows or []
                    if cur["code"] >= 0:
                        glyphs[chr(cur["code"])] = cur
                    cur, rows = None, None
                elif rows is not None:
                    rows.append(int(key, 16))
        BDF[name] = (glyphs, ascent)


def _bdf_text(canvas, x, y_mid, h, text, fill, font):
    """Draw like a displayio Label: y is the middle of the line."""
    glyphs, ascent = font
    base = y_mid - h // 2 + ascent
    for ch in text:
        g = glyphs.get(ch) or glyphs.get("?")
        if not g:
            continue
        w, gh, ox, oy = g["bbx"]
        nbits = (w + 7) // 8 * 8
        for r, bits in enumerate(g["rows"]):
            for col in range(w):
                if bits >> (nbits - 1 - col) & 1:
                    px, py = x + ox + col, base - oy - gh + r
                    if 0 <= px < canvas.width and 0 <= py < canvas.height:
                        canvas.putpixel((px, py), fill)
        x += g.get("adv", w)


def _font(px):
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def paint(screen):
    w, h = screen.w, screen.h
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.fontmode = "1"

    def color(c):
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)

    def walk(group, ox, oy):
        if getattr(group, "hidden", False):
            return
        for item in group:
            if getattr(item, "hidden", False):
                continue
            if isinstance(item, fake.Group):
                walk(item, ox + item.x, oy + item.y)
            elif isinstance(item, fake.TileGrid):
                bmp = item.bitmap
                if isinstance(bmp, fake.OnDiskBitmap):
                    moon(draw, ox + item.x, oy + item.y, int(bmp.path[-6:-4]) / 100)
                    continue
                pal = item.pixel_shader
                for y in range(bmp.height):
                    for x in range(bmp.width):
                        v = bmp[x, y]
                        if v in pal.transparent:
                            continue
                        canvas.putpixel((ox + item.x + x, oy + item.y + y), color(pal[v])) \
                            if 0 <= ox + item.x + x < w and 0 <= oy + item.y + y < h else None
            elif isinstance(item, fake.Label):
                if item.y < -50 or not item.text.strip():
                    continue
                f = item.font
                text = item.text.replace("\u21A5", "^").replace("\u21A7", "v")
                real = next((v for k, v in BDF.items() if k in f.path), None)
                if real:
                    _bdf_text(canvas, ox + item.x, oy + item.y, f.h, item.text,
                              color(item.color), real)
                    continue
                draw.text((ox + item.x, oy + item.y - f.h // 2), text,
                          fill=color(item.color), font=_font(f.h))

    walk(screen.root, 0, 0)
    big = Image.new("RGB", (w * DOT + 20, h * DOT + 20), (18, 18, 20))
    d = ImageDraw.Draw(big)
    for y in range(h):
        for x in range(w):
            r, g, b = canvas.getpixel((x, y))
            fill = (r, g, b) if r + g + b > 30 else (28, 28, 30)
            d.ellipse((10 + x * DOT + 1, 10 + y * DOT + 1, 10 + x * DOT + DOT - 2,
                       10 + y * DOT + DOT - 2), fill=fill)
    return big


def moon(draw, x0, y0, phase):
    k = math.cos(2 * math.pi * phase)
    for y in range(32):
        for x in range(32):
            nx, ny = (x - 15.5) / 14, (y - 15.5) / 14
            if nx * nx + ny * ny > 1:
                continue
            edge = math.sqrt(max(0, 1 - ny * ny))
            lit = nx > k * edge if phase < 0.5 else nx < -k * edge
            draw.point((x0 + x, y0 + y), fill=(200, 200, 170) if lit else (25, 25, 35))


def main(out):
    os.makedirs(out, exist_ok=True)
    fonts = chatty_screen.load_fonts()
    now = clock.epoch(2026, 11, 17, 21, 5)
    hm = lambda utc: clock.parts(utc - 5 * 3600)[3:5]  # noqa: E731
    n = news.News()
    n.message("chatty/forecast/rain", json.dumps({"rain_expected": True, "chance": 70,
                                                  "starts_ts": now + 3 * 3600, "kind": "storms",
                                                  "ts": now}), now, 1)
    n.message("chatty/nodes/greenhouse/data", json.dumps(
        {"metrics": {"air_temperature_f": 68.4, "soil_moisture_band": "okay"}}), now, 1)
    n.message("chatty/nodes/lightning/data", json.dumps(
        {"last_strike": {"ts": now - 240, "distance_mi": 6}}), now, 1)
    for name, state in (("rain", "online"), ("greenhouse", "online"), ("chatty", "online"),
                        ("wordclock", "offline")):
        n.message("chatty/nodes/%s/status" % name, json.dumps({"state": state}), now, 1)
    n.message("chatty/alerts/active", json.dumps({"alerts": [
        {"event": "Severe Thunderstorm Warning", "kind": "urgent", "expires_ts": now + 2400}],
        "ts": now}), now, 1)
    shots = []
    for rotation in (90, 0):
        tag = "portrait" if rotation == 90 else "landscape"
        s = chatty_screen.Screen(fake.FakeDisplay(), rotation, fonts)
        local = clock.parts(now - 5 * 3600)
        s.show_clock(local, {"phase": 0.27, "lit": 0.55, "next": "set", "next_local": (0, 41)}, True)
        shots.append(("clock-" + tag, paint(s)))
        s.rain(True, True)
        for _ in range(20):
            s.rain(True, True)
        shots.append(("rain-" + tag, paint(s)))
        s.rain(False, False)
        for card in n.cards(now, 2, hm):
            width = s.show_card(card)
            if width:
                for _ in range(s.w + 20):
                    s.step_scroll(width)
            shots.append(("card-" + card["icon"] + "-" + tag, paint(s)))
        card = {"icon": "warn", "color": news.RED, "lines": ["TAKE", "COVER"] if rotation else
                ["TAKE COVER"], "scroll": "TORNADO WARNING UNTIL 3:45PM - TAKE SHELTER NOW",
                "seconds": 0}
        width = s.show_card(card, urgent=True)
        s.tornado(True, True)
        for _ in range(s.w + 4):
            s.step_scroll(width)
        shots.append(("tornado-" + tag, paint(s)))
        s.tornado(False, False)
    for name, img in shots:
        img.save(os.path.join(out, name + ".png"))
    # one sheet of the portrait ones (the way the panel stands)
    tall = [img for name, img in shots if name.endswith("portrait")]
    sheet = Image.new("RGB", (sum(i.width for i in tall) + 10 * len(tall), tall[0].height),
                      (255, 255, 255))
    x = 0
    for img in tall:
        sheet.paste(img, (x, 0))
        x += img.width + 10
    sheet.save(os.path.join(out, "matrix-sheet.png"))
    print("Wrote", len(shots) + 1, "pictures to", out)


if __name__ == "__main__":
    if len(sys.argv) > 2:
        _bdf(sys.argv[2])
    main(sys.argv[1] if len(sys.argv) > 1 else "matrix_preview")

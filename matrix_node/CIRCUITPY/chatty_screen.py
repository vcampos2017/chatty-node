"""The Matrix node's picture: the moon clock, news cards, the tornado frame, the flash.

The clock layout is Phil Burgess's, from the Moon Phase Clock for Adafruit
(MIT license, see chatty_matrix.py for the notice).
"""
# pylint: disable=import-error,broad-except,too-many-instance-attributes
import time

import board
import busio
import displayio

import chatty_art as art
import chatty_clock as clock
from chatty_bits import dim

BITPLANES = 6


def make_display():
    try:
        from adafruit_matrixportal.matrix import Matrix
        return Matrix(bit_depth=BITPLANES).display
    except ImportError:
        import framebufferio
        import rgbmatrix
        matrix = rgbmatrix.RGBMatrix(
            width=64, height=32, bit_depth=BITPLANES,
            rgb_pins=[board.MTX_R1, board.MTX_G1, board.MTX_B1,
                      board.MTX_R2, board.MTX_G2, board.MTX_B2],
            addr_pins=[board.MTX_ADDRA, board.MTX_ADDRB, board.MTX_ADDRC, board.MTX_ADDRD],
            clock_pin=board.MTX_CLK, latch_pin=board.MTX_LAT, output_enable_pin=board.MTX_OE)
        return framebufferio.FramebufferDisplay(matrix)


def which_way_up():
    """0 / 90 / 180 / 270 from the accelerometer, like the original clock."""
    try:
        import math
        import adafruit_lis3dh
        accel = adafruit_lis3dh.LIS3DH_I2C(busio.I2C(board.SCL, board.SDA), address=0x19)
        _ = accel.acceleration
        time.sleep(0.1)
        a = accel.acceleration
        return (int(((math.atan2(-a.y, -a.x) + math.pi) / (math.pi * 2) + 0.875) * 4) % 4) * 90
    except Exception as ex:
        print("Accelerometer:", repr(ex))
        return 0


def show(display, group):
    try:
        display.root_group = group
    except AttributeError:
        display.show(group)


def load_fonts():
    from adafruit_bitmap_font import bitmap_font
    fonts = {}
    for key, path, glyphs in (("large", "/fonts/helvB12.bdf", "0123456789:"),
                              ("small", "/fonts/helvR10.bdf", "0123456789:/.%"),
                              ("symbol", "/fonts/6x10.bdf", "↥↧"),
                              ("text", "/fonts/6x10.bdf", None)):
        try:
            font = bitmap_font.load_font(path)
            if glyphs:
                font.load_glyphs(glyphs)
            fonts[key] = font
        except Exception as ex:
            print("Font", path, repr(ex))
            import terminalio
            fonts[key] = terminalio.FONT
    return fonts


def moon_bitmap(frame):
    path = "moon/moon" + "{:02d}".format(frame) + ".bmp"
    try:
        bmp = displayio.OnDiskBitmap(path)
        shader = getattr(bmp, "pixel_shader", None) or displayio.ColorConverter()
    except Exception:
        bmp = displayio.OnDiskBitmap(open(path, "rb"))
        shader = displayio.ColorConverter()
    return displayio.TileGrid(bmp, pixel_shader=shader)


class Screen:
    def __init__(self, display, rotation, fonts):
        from adafruit_display_text.label import Label
        self.Label = Label
        self.display, self.fonts = display, fonts
        self.portrait = rotation in (90, 270)
        self.w, self.h = (32, 64) if self.portrait else (64, 32)
        self.level = 1.0
        self.root = displayio.Group()

        # the clock (Phil Burgess's layout)
        self.moon = displayio.Group()
        self.moon_tile = displayio.Group()          # holds the moon picture
        self.moon_frame = None
        self.moon.append(self.moon_tile)
        self.rain_bmp = displayio.Bitmap(self.w, self.h, 2)
        rain_pal = displayio.Palette(2)
        rain_pal[0] = 0
        rain_pal.make_transparent(0)
        rain_pal[1] = 0x1040A0
        self.rain_pal = rain_pal
        self.rain_grid = displayio.TileGrid(self.rain_bmp, pixel_shader=rain_pal)
        self.rain_grid.hidden = True
        self.moon.append(self.rain_grid)
        self.drops = [((i * 7 + 3) % self.w, (i * 13) % self.h) for i in range(10)]
        small, large = fonts["small"], fonts["large"]
        self.outline = [Label(small, color=0, text="99.9%", y=-99) for _ in range(4)]
        for item in self.outline:
            self.moon.append(item)
        self.pct = Label(small, color=0xFFFF00, text="99.9%", y=-99)
        self.time = Label(large, color=0x808080, text="12:00", y=-99)
        self.date = Label(small, color=0x808080, text="12/31", y=-99)
        self.arrow = Label(fonts["symbol"], color=0x00FF00, text="x", y=-99)
        self.event = Label(small, color=0x00FF00, text="12:00", y=-99)
        for item in (self.pct, self.time, self.date, self.arrow, self.event):
            self.moon.append(item)
        self.root.append(self.moon)

        # a news card
        self.card = displayio.Group()
        self.icon_bmp = displayio.Bitmap(art.SIZE, art.SIZE, 3)
        self.icon_pal = displayio.Palette(3)
        self.icon_pal[0] = 0
        self.icon_pal.make_transparent(0)
        self.icon = displayio.TileGrid(self.icon_bmp, pixel_shader=self.icon_pal)
        self.card.append(self.icon)
        self.lines = [Label(fonts["text"], color=0xFFFFFF, text=" ", y=-99) for _ in range(3)]
        for item in self.lines:
            self.card.append(item)
        self.scroll = Label(fonts["text"], color=0xFFFFFF, text=" ", y=-99)
        self.card.append(self.scroll)
        self.card.hidden = True
        self.root.append(self.card)

        # Tornado Warning: a blinking frame behind the card
        self.frame_bmp = displayio.Bitmap(self.w, self.h, 2)
        for x in range(self.w):
            for y in (0, self.h - 1):
                self.frame_bmp[x, y] = 1
        for y in range(self.h):
            for x in (0, self.w - 1):
                self.frame_bmp[x, y] = 1
        self.frame_pal = displayio.Palette(2)
        self.frame_pal[0] = 0
        self.frame_pal.make_transparent(0)
        self.frame_pal[1] = 0xFF0000
        self.frame = displayio.TileGrid(self.frame_bmp, pixel_shader=self.frame_pal)
        self.frame.hidden = True
        self.root.insert(1, self.frame)

        # lightning flash
        self.flash_bmp = displayio.Bitmap(self.w, self.h, 1)
        self.flash_pal = displayio.Palette(1)
        self.flash_pal[0] = 0xFFFFFF
        self.flash = displayio.TileGrid(self.flash_bmp, pixel_shader=self.flash_pal)
        self.flash.hidden = True
        self.root.append(self.flash)
        show(display, self.root)

    # -- the clock

    def show_clock(self, local, moon, twelve):
        """local = clock.parts(...) or None; moon = dict from App.moon_now() or None."""
        self.card.hidden = True
        self.frame.hidden = True
        self.moon.hidden = False
        risen = bool(moon and moon.get("next") == "set")
        if not self.portrait:
            center_x, moon_y, time_y, event_y = 48, 0, 6, 26
        elif risen:
            center_x, moon_y, event_y, time_y = 16, 0, 38, 49
        else:
            center_x, time_y, event_y, moon_y = 16, 6, 26, 32
        if moon:
            frame = int(moon["phase"] * 100) % 100
            moved = not len(self.moon_tile) or self.moon_tile[0].y != moon_y
            if frame != self.moon_frame or moved:
                try:
                    tile = moon_bitmap(frame)
                    tile.y = moon_y
                    while len(self.moon_tile):
                        self.moon_tile.pop()
                    self.moon_tile.append(tile)
                    self.moon_frame = frame
                except Exception as ex:
                    print("Moon picture:", repr(ex))
            lit = moon["lit"] * 100
            text = "100%" if lit >= 99.95 else "{:.1f}".format(lit + 0.05) + "%"
            self._set(self.pct, text, 16 - self.pct.bounding_box[2] // 2, moon_y + 16)
            self.pct.x = 16 - self.pct.bounding_box[2] // 2
            for item, (dx, dy) in zip(self.outline, ((0, -1), (-1, 0), (1, 0), (0, 1))):
                item.text = text
                item.x, item.y = self.pct.x + dx, self.pct.y + dy
        else:
            self._set(self.pct, " ", 0, -99)
            for item in self.outline:
                item.y = -99
        if moon and moon.get("next_local"):
            hh, mm = moon["next_local"]
            text = clock.hh_mm(hh, mm, twelve)
            self.event.text = text
            x = center_x - (self.event.bounding_box[2] + 6) // 2
            self.arrow.text = "↧" if risen else "↥"
            self.arrow.x, self.arrow.y = x, event_y - (2 if risen else 1)
            self.event.x, self.event.y = x + 6, event_y
            color = 0x00FF00 if hh < 12 else 0xC04000
            self.arrow.color = self.event.color = dim(color, self.level)
        else:
            self.event.y = self.arrow.y = -99
        if local:
            self.time.text = clock.hh_mm(local[3], local[4], twelve)
            self.date.text = str(local[1]) + "/" + str(local[2])
        else:
            self.time.text, self.date.text = "--:--", "--/--"
        self.time.x, self.time.y = center_x - self.time.bounding_box[2] // 2, time_y
        self.date.x, self.date.y = center_x - self.date.bounding_box[2] // 2, time_y + 10
        self.time.color = self.date.color = dim(0x808080, max(self.level, 0.5))
        self.pct.color = dim(0xFFFF00, self.level)

    @staticmethod
    def _set(item, text, x, y):
        item.text = text
        item.x, item.y = x, y

    def rain(self, on, step):
        if not on:
            if not self.rain_grid.hidden:
                self.rain_bmp.fill(0)
                self.rain_grid.hidden = True
            return
        self.rain_grid.hidden = False
        self.rain_pal[1] = dim(0x1040A0, max(self.level, 0.5))
        if not step:
            return
        moved = []
        for x, y in self.drops:
            self.rain_bmp[x, y] = 0
            if y + 1 < self.h:
                self.rain_bmp[x, y + 1] = 0
            y = (y + 1) % self.h
            if y == 0:
                x = (x + 11) % self.w
            self.rain_bmp[x, y] = 1
            if y + 1 < self.h:
                self.rain_bmp[x, y + 1] = 1
            moved.append((x, y))
        self.drops = moved

    # -- cards

    def show_card(self, card, urgent=False):
        """Lay out a card (from chatty_news). Returns the scroll width (0 = no scroll)."""
        self.moon.hidden = True
        self.card.hidden = False
        level = 1.0 if urgent else self.level
        color = dim(card["color"], level)
        self.icon_bmp.fill(0)
        for x, y, v in art.pixels(card["icon"]):
            self.icon_bmp[x, y] = v
        self.icon_pal[1] = color
        self.icon_pal[2] = dim(0xFFFFFF, level * 0.8)
        lines = card.get("lines") or []
        for item in self.lines:
            item.y = -99
        self.scroll.y = -99
        if card.get("scroll"):
            self.scroll.text = card["scroll"]
            self.scroll.color = dim(0xFFFFFF if urgent else card["color"], level)
            self.icon.x = (self.w - art.SIZE) // 2
            self.icon.y = 8 if self.portrait else 2
            for i, text in enumerate(lines[:2]):
                item = self.lines[i]
                item.text = text
                item.color = dim(0xFFFFFF, level)
                item.x = (self.w - item.bounding_box[2]) // 2
                item.y = (24 + 11 * i) if self.portrait else 15
            self.icon.y = 8 if self.portrait else (1 if lines else 4)
            self.scroll.x = self.w
            self.scroll.y = (self.h - 9) if self.portrait else (26 if lines else 22)
            return self.scroll.bounding_box[2]
        n = len(lines)
        if self.portrait:
            top = (self.h - (art.SIZE + 3 + 11 * n)) // 2
            self.icon.x, self.icon.y = (self.w - art.SIZE) // 2, top
            for i, text in enumerate(lines):
                item = self.lines[i]
                item.text, item.color = text, color if i == 0 else dim(0xFFFFFF, level * 0.9)
                item.x = (self.w - item.bounding_box[2]) // 2
                item.y = top + art.SIZE + 3 + 5 + 11 * i
        else:
            self.icon.x, self.icon.y = 3, (self.h - art.SIZE) // 2
            for i, text in enumerate(lines):
                item = self.lines[i]
                item.text, item.color = text, color if i == 0 else dim(0xFFFFFF, level * 0.9)
                item.x = 14 + (50 - item.bounding_box[2]) // 2
                item.y = 16 - (n - 1) * 5 + 10 * i
        return 0

    def step_scroll(self, width):
        """Move the scrolling line one pixel. False once it has gone by."""
        self.scroll.x -= 1
        return self.scroll.x > -width

    def tornado(self, on, blink):
        self.frame.hidden = not on
        if on:
            self.frame_pal[1] = 0xFF0000 if blink else 0xFFC000

    def flash_on(self, on):
        self.flash_pal[0] = dim(0xFFFFFF, max(self.level, 0.3))
        self.flash.hidden = not on

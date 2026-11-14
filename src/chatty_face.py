"""
Chatty's face for the Pi screen (pygame).

Listens on UDP 127.0.0.1:47474 for small text messages from the voice node:
    state:idle | listening | thinking | speaking | puzzled | sleepy
    level:0.0-1.0        (mouth openness while speaking)
    ponder[:node]        (wonder about another node now, e.g. ponder:greenhouse)
    doodle[:style]       (draw something now: spiro, stars or rain; see doodles.py)
    chess[:node]         (play chess with another node now, e.g. chess:rain; see chess_match.py)
    trickster[:meeting | :vote:<node>]  (Who's the Trickster? start it, ring the bell, or vote; see trickster.py)
    chessmail:<who>:<n>  (show a game by letter, replaying its last n moves; see chess_mail.py)
    sky:rain | sky:dry | sky:strike:<miles>   (weather from the other nodes; see sky.py)
    timer:<end>:<timer|alarm>:<label>  (the next timer or alarm, shown top-right; "timer:" clears)
    redalert:<until>:<test|>:<title> | redalert:off   (Red Alert for a tornado warning; see red_alert.py)
    From the remote panel (panel.py):
    snap                 (save a picture of the screen + what's on it to /dev/shm, owner-only)
    calm                 (put down the pencils / chess board / game, like a tap, without waking her)
    notices:clear        (clear the notices, like the first tap)
    light:<0..1> | light:auto   (hold the screen at a brightness for a while, or back to automatic)
    bedtime        (the bedtime wind-down is done: night dimming until morning)

Touchscreen: tap the face to wake Chatty (same as saying "Hey Chatty");
press and hold for 2 seconds to say goodnight (Chatty rests until tapped).
The screen dims when nobody needs it (see backlight.py); when it's very dim
the first tap only lights it up.

Runs at 30 fps while something is moving and ~8 fps when idle, so it stays
light on the Pi. Esc or Q quits the face app. Use --windowed for a desktop window.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time

import pygame

try:  # same settings file as the voice service (e.g. CHATTY_FORCE_SPOOKY)
    from dotenv import load_dotenv
    load_dotenv("/etc/chatty/secrets.env")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(__file__))
import backlight  # noqa: E402
import chess_link  # noqa: E402
import chess_match  # noqa: E402
import chess_mail  # noqa: E402
import doodles  # noqa: E402
import trickster  # noqa: E402
from face_model import FaceModel  # noqa: E402

FACE_PORT = int(os.getenv("CHATTY_FACE_PORT", "47474"))
VOICE_PORT = int(os.getenv("CHATTY_VOICE_PORT", "47475"))  # voice node listens here
TAP_MAX_SECONDS = 0.6      # a quick touch wakes Chatty
REST_HOLD_SECONDS = 2.0    # holding this long puts Chatty to bed
FAST_FPS = 30
SLOW_FPS = 8
RAIN_FPS = 12      # raindrops behind her face (only while it's really raining)


class PygameCanvas:
    """The small drawing interface face_model expects, backed by pygame."""

    def __init__(self, surface):
        self.s = surface
        self._fonts = {}
        self._glyphs = {}

    def fill(self, color):
        self.s.fill(color)

    def rrect(self, color, rect, radius):
        pygame.draw.rect(self.s, color, pygame.Rect(*map(round, rect)), border_radius=max(0, round(radius)))

    def ellipse(self, color, rect, width=0):
        pygame.draw.ellipse(self.s, color, pygame.Rect(*map(round, rect)), width)

    def arc(self, color, rect, start, stop, width):
        pygame.draw.arc(self.s, color, pygame.Rect(*map(round, rect)), start, stop, width)

    def line(self, color, p1, p2, width):
        pygame.draw.line(self.s, color, p1, p2, width)
        # round the ends so thick lines look soft
        r = width / 2
        for p in (p1, p2):
            pygame.draw.circle(self.s, color, (round(p[0]), round(p[1])), r)

    def polyline(self, color, points, width):
        # one call for a whole curve (doodles): much cheaper than many line()s
        pygame.draw.lines(self.s, color, False, [(round(x), round(y)) for x, y in points], width)

    def polygon(self, color, points):
        pygame.draw.polygon(self.s, color, [(round(x), round(y)) for x, y in points])

    def _font(self, size):
        font = self._fonts.get(size)
        if font is None:
            font = self._fonts[size] = pygame.font.Font(None, int(size * 1.35))
        return font

    def text(self, txt, pos, size, color):
        if len(txt) <= 2:
            # single letters are drawn hundreds of times a frame by the falling-code
            # doodle: keep the rendered glyphs instead of rendering them again
            key = (txt, size, tuple(color))
            glyph = self._glyphs.get(key)
            if glyph is None:
                if len(self._glyphs) > 3000:
                    self._glyphs.clear()
                glyph = self._glyphs[key] = self._font(size).render(txt, True, color)
            self.s.blit(glyph, pos)
            return
        self.s.blit(self._font(size).render(txt, True, color), pos)

    def measure(self, txt, size):
        return self._font(size).size(txt)[0]


def open_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", FACE_PORT))
    sock.setblocking(False)
    return sock


SNAP_PNG = os.getenv("CHATTY_FACE_SNAP", "/dev/shm/chatty_face.png")
SNAP_JSON = os.path.splitext(SNAP_PNG)[0] + ".json"


def save_snapshot(screen, face: FaceModel) -> None:
    """A picture of the screen for the remote panel, plus the notices as text.
    Both files are owner-only and live in memory (/dev/shm), gone at reboot."""
    try:
        tmp = SNAP_PNG + ".tmp.png"
        pygame.image.save(screen, tmp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, SNAP_PNG)
        tmp = SNAP_JSON + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(face.panel_info(), f)
        os.replace(tmp, SNAP_JSON)
    except (OSError, pygame.error) as e:
        print("Snapshot failed:", repr(e), flush=True)


def read_messages(sock, face: FaceModel, dimmer=None):
    while True:
        try:
            data, _ = sock.recvfrom(1024)
        except BlockingIOError:
            return
        except OSError:
            return
        for line in data.decode("utf-8", "ignore").splitlines():
            key, _, value = line.partition(":")
            key = key.strip()
            if key == "state":
                face.set_state(value.strip().lower())
            elif key == "play":
                face.start_game(human=True)
            elif key == "ponder":   # "ponder" or "ponder:greenhouse" (testing, or asked to check)
                face.start_ponder(value.strip() or None)
            elif key == "sky":      # "sky:rain", "sky:dry", "sky:strike:4.2" (see sky.py)
                face.set_sky(value)
            elif key == "doodle":   # "doodle" or "doodle:rain"
                face.start_doodle(value.strip().lower() or None)
            elif key == "imagine":  # a daydream on the screen ("imagine" or "imagine:a dragon")
                face.start_daydream(value.strip()[:80])
            elif key == "chess":    # "chess" or "chess:lightning"
                face.start_chess(value.strip().lower() or None)
            elif key == "trickster":   # "trickster", "trickster:meeting", "trickster:vote:rain"
                face.mystery_message(value)
            elif key == "chessmail":   # "chessmail:claude:2" (a move by letter; see chess_mail.py)
                who, _, plies = value.strip().lower().partition(":")
                chess_mail.show_on_face(face, who, int(plies) if plies.isdigit() else 0)
            elif key == "rec":
                face.set_rec(value.strip())
            elif key == "heard":
                face.set_caption(value)
            elif key == "notice":
                face.add_notice(value)
            elif key == "redalert":   # "redalert:<until>:<test|>:Tornado Warning" or "redalert:off"
                face.set_red_alert(value)
            elif key == "morse":    # "morse:<start>:<dit seconds>:<code>" or "morse:off" (morse.py)
                face.set_morse(value)
            elif key == "timer":    # "timer:<end>:<timer|alarm>:<label>" or "timer:" (none)
                face.set_timer(value)
            elif key == "snap":     # the remote panel wants a picture of the screen
                face.snap_wanted = True
            elif key == "calm":
                face.calm()
            elif key == "notices" and value.strip() == "clear":
                face.notices = []
            elif key == "bedtime" and dimmer is not None:   # wind-down done: dim until morning
                dimmer.bedtime(time.time())
            elif key == "light" and dimmer is not None:
                v = value.strip().lower()
                try:
                    dimmer.hold(None if v == "auto" else float(v), time.time())
                except ValueError:
                    pass
            elif key == "listen":
                try:
                    face.set_listen(float(value))
                except ValueError:
                    pass
            elif key == "level":
                try:
                    face.set_level(float(value))
                except ValueError:
                    pass


def main():
    windowed = "--windowed" in sys.argv
    pygame.display.init()
    pygame.font.init()
    if windowed:
        screen = pygame.display.set_mode((800, 480))
    else:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    pygame.display.set_caption("Chatty")

    w, h = screen.get_size()
    face = FaceModel(w, h)
    if chess_match.ENABLED:
        face.chess_link = chess_link.ChessLink().start()   # finds a node to play chess with
    canvas = PygameCanvas(screen)
    sock = open_socket()
    clock = pygame.time.Clock()
    print(f"Chatty face running at {w}x{h}, listening on UDP {FACE_PORT}", flush=True)

    dimmer = backlight.Dimmer()
    light = backlight.Backlight()
    main.light = light                  # so the screen is put back to full on exit

    last = time.time()
    touch_started = 0.0
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
                return
            # touchscreens report taps as mouse clicks
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                touch_started = time.time()
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and touch_started:
                held = time.time() - touch_started
                touch_started = 0.0
                if (held <= TAP_MAX_SECONDS and light.ok and light.level <= backlight.DARK
                        and not face.red_on()):
                    dimmer.poke(time.time())   # a dark screen: the first tap just lights it up
                    continue
                if held <= TAP_MAX_SECONDS and face.handle_tap(event.pos):
                    pass  # a tic-tac-toe move or dismissing notices, not a wake-up
                elif held <= TAP_MAX_SECONDS:
                    print("Tap: waking Chatty", flush=True)
                    try:
                        sock.sendto(b"wake", ("127.0.0.1", VOICE_PORT))
                    except OSError:
                        pass

        # long press says goodnight (checked while still held)
        if touch_started and time.time() - touch_started >= REST_HOLD_SECONDS:
            touch_started = 0.0
            print("Long press: goodnight", flush=True)
            try:
                sock.sendto(b"rest", ("127.0.0.1", VOICE_PORT))
            except OSError:
                pass

        read_messages(sock, face, dimmer)
        now = time.time()
        face.update(now - last, now)
        while face.outbox:   # e.g. "notify:The plants are thirsty" -> spoken by the voice node
            msg = face.outbox.pop(0)
            print("To voice:", msg, flush=True)
            try:
                sock.sendto(msg.encode("utf-8")[:500], ("127.0.0.1", VOICE_PORT))
            except OSError:
                pass
        target = dimmer.target(face.state, face.last_activity, now)
        if face.red_on(now):
            target = backlight.FULL          # Red Alert: full brightness, day or night
        light.step(target, now - last)
        last = now
        face.draw(canvas, now)
        pygame.display.flip()
        if face.snap_wanted:
            face.snap_wanted = False
            save_snapshot(screen, face)
        if light.busy(target):
            clock.tick(FAST_FPS)             # a smooth fade
        elif face.doodle and face.state == "idle":
            clock.tick(doodles.FPS)
        elif face.chess and face.state == "idle":
            clock.tick(chess_match.FPS)
        elif face.mystery and face.state == "idle":
            clock.tick(trickster.FPS)
        elif face.busy():
            clock.tick(FAST_FPS)
        else:
            clock.tick(RAIN_FPS if face.raining() else SLOW_FPS)


if __name__ == "__main__":
    try:
        main()
    finally:
        light = getattr(main, "light", None)
        if light is not None and light.ok:
            light.step(backlight.FULL, backlight.FADE_SECONDS)   # never leave the screen dark
        pygame.quit()

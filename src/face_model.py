"""
Chatty's face: expressions and animation, independent of the screen library.

FaceModel.update() advances the animation; FaceModel.draw(canvas) draws one
frame using a small canvas interface (see chatty_face.py for the pygame one).
Keeping this separate lets the same face be previewed without pygame.
"""
from __future__ import annotations

import math
import random
import time

try:
    import chess_match
    import doodles
    import dreams
    import quiet_hours
    import games
    import imagine
    import morse
    import nodes
    import pondering
    import trickster
except ImportError:  # running from another folder
    from . import chess_match, doodles, dreams, games, imagine, morse, nodes, pondering, quiet_hours, trickster  # type: ignore
import os

# colors per state (eye/mouth color)
PALETTE = {
    "idle":      (225, 240, 236),
    "listening": (77, 217, 240),
    "thinking":  (180, 140, 255),
    "speaking":  (255, 200, 87),
    "puzzled":   (255, 159, 67),
    "sleepy":    (92, 124, 186),
    "resting":   (40, 52, 78),    # put to bed: dim and calm
    "mischief":      (255, 84, 140),  # cheeky hot pink
    "mischief_talk": (255, 84, 140),
    "love":          (255, 128, 178),  # soft valentine pink
    "love_talk":     (255, 128, 178),
    "actually":      (168, 120, 255),  # "well, actually..." science purple
    "actually_talk": (168, 120, 255),
    "snapped":       (196, 210, 232),  # cold, flat, fluorescent "booking photo" white-blue
    "snapped_talk":  (196, 210, 232),
    "tiny":          (206, 228, 92),   # Tiny the tuxedo cat's green-yellow eyes
    "tiny_talk":     (206, 228, 92),
    "imagine":       (255, 214, 120),  # starting color; while imagining her eyes cycle the rainbow
    "imagine_talk":  (255, 214, 120),
    "morse":         (255, 196, 92),   # warm telegraph-lamp amber while she taps out Morse
}
BACKGROUND = (8, 10, 14)

# per-state expression targets
#   open: eye openness (1 = fully open), size: eye scale,
#   gaze: (x, y) where eyes look, -1..1, mouth: shape name
EXPRESSIONS = {
    "idle":      dict(open=1.0, size=1.0, gaze=(0.0, 0.0), mouth="smile"),
    "listening": dict(open=1.08, size=1.06, gaze=(0.0, -0.05), mouth="small_o"),
    "thinking":  dict(open=0.82, size=1.0, gaze=(0.55, -0.6), mouth="flat"),
    "speaking":  dict(open=1.0, size=1.0, gaze=(0.0, 0.0), mouth="talk"),
    "puzzled":   dict(open=1.0, size=1.0, gaze=(-0.3, -0.2), mouth="tilt"),
    "sleepy":    dict(open=0.07, size=1.0, gaze=(0.0, 0.25), mouth="small_smile"),
    "resting":   dict(open=0.05, size=0.95, gaze=(0.0, 0.3), mouth="small_smile"),
    # sly sideways look, half-lidded eyes, lopsided smirk (and the odd wink)
    "mischief":      dict(open=0.55, size=1.0, gaze=(0.55, 0.1), mouth="smirk"),
    "mischief_talk": dict(open=0.6, size=1.0, gaze=(0.35, 0.05), mouth="talk"),
    # happy closed eyes (^ ^), rosy cheeks, a kiss, and little hearts floating up
    "love":          dict(open=1.0, size=1.0, gaze=(0.0, 0.0), mouth="kiss"),
    "love_talk":     dict(open=1.0, size=1.0, gaze=(0.0, 0.0), mouth="talk"),
    # "Well, actually..." (a gentle correction): one brow up, knowing smile, finger raised, a planet orbiting
    "actually":      dict(open=0.9, size=1.0, gaze=(-0.15, -0.1), mouth="knowing"),
    "actually_talk": dict(open=0.95, size=1.0, gaze=(-0.1, -0.05), mouth="talk"),
    # "Snapped": the princess is done being nice. Level, half-lidded deadpan stare
    # straight at you, flat mouth, a crooked cracked tiara, height-chart lines behind.
    "snapped":       dict(open=0.48, size=1.0, gaze=(0.0, 0.0), mouth="deadpan"),
    "snapped_talk":  dict(open=0.5, size=1.0, gaze=(0.0, 0.0), mouth="talk"),
    # "Tiny": channeling Tiny the tuxedo cat. Ears up, slit pupils, a wary sideways
    # look, whiskers and a little cat mouth.
    "tiny":          dict(open=0.78, size=1.0, gaze=(-0.75, 0.25), mouth="cat"),
    "tiny_talk":     dict(open=0.8, size=1.0, gaze=(-0.55, 0.15), mouth="talk"),
    # "Imagine": her hands sweep a rainbow open over her head; big starry eyes looking
    # up at it, a wide open grin, eyes slowly cycling through the rainbow (imagine.py)
    "imagine":       dict(open=1.0, size=0.92, gaze=(0.0, -0.3), mouth="grin"),
    "imagine_talk":  dict(open=1.0, size=0.92, gaze=(0.0, -0.15), mouth="talk"),
    # "Morse": eyes down on the little telegraph tape, lips pressed in concentration;
    # her eyes flash with every dit and dah (morse.py)
    "morse":         dict(open=0.95, size=0.96, gaze=(0.0, 0.35), mouth="small_smile"),
}
LOVE_STATES = ("love", "love_talk")
TINY_STATES = ("tiny", "tiny_talk")
SNAPPED_STATES = ("snapped", "snapped_talk")
ACTUALLY_STATES = ("actually", "actually_talk")
IMAGINE_STATES = ("imagine", "imagine_talk")

IDLE_TO_SLEEPY_SECONDS = 600  # (night) doze off after 10 quiet minutes
# She's less sleepy during the day: plays instead of dozing.
SLEEPY_AFTER_DAY = float(os.getenv("CHATTY_SLEEPY_AFTER_DAY", "1800"))      # 8am-10pm
SLEEPY_AFTER_NIGHT = float(os.getenv("CHATTY_SLEEPY_AFTER_NIGHT", str(IDLE_TO_SLEEPY_SECONDS)))
GAMES = os.getenv("CHATTY_GAMES", "1") != "0"
BORED_AFTER = float(os.getenv("CHATTY_BORED_AFTER", "180"))  # idle this long -> plays a game
# Pondering: now and then she wonders about another node (greenhouse, rain) and asks it.
CURIOUS = os.getenv("CHATTY_CURIOSITY", "1") != "0"
PONDER_EVERY = float(os.getenv("CHATTY_PONDER_EVERY", "1500"))   # ~25 min (randomized)
# Say worrying readings out loud (dry soil, very hot), daytime only, at most every few hours.
PONDER_SPEAK = os.getenv("CHATTY_PONDER_SPEAK", "1") != "0"
SPEAK_GAP = float(os.getenv("CHATTY_PONDER_SPEAK_GAP", str(3 * 3600)))


def sleepy_after(t: float) -> float:
    hour = time.localtime(t).tm_hour
    return SLEEPY_AFTER_DAY if 8 <= hour < 22 else SLEEPY_AFTER_NIGHT

# Status line at the bottom of the screen (plain ASCII: the Pi's default font is basic)
STATUS = {
    "idle":          ("Say \"Hey Chatty\" or tap me", False),
    "listening":     ("Listening", True),     # True = animated dots
    "thinking":      ("Thinking", True),
    "speaking":      ("Speaking", False),
    "mischief_talk": ("Speaking", False),
    "mischief":      ("", False),
    "love_talk":     ("Speaking", False),
    "love":          ("", False),
    "actually":      ("Well, actually...", False),
    "actually_talk": ("Well, actually...", False),
    "snapped":       ("", False),
    "snapped_talk":  ("Speaking", False),
    "tiny":          ("", False),
    "tiny_talk":     ("Speaking", False),
    "imagine":       ("Imagining", True),
    "imagine_talk":  ("Imagining...", False),
    "morse":         ("Morse code", False),
    "puzzled":       ("Hmm...", False),
    "sleepy":        ("Dozing - tap to wake", False),
    "resting":       ("Resting - tap to wake", False),
}
CAPTION_COLOR = (210, 220, 228)
MORSE_TAPE = (24, 22, 18)        # the Morse tape: dark, warm
MORSE_MARK = (190, 160, 110)     # dits and dahs already sent
MORSE_LAMP = (255, 214, 120)     # the lamp, and the beep sounding right now
MORSE_LAMP_OFF = (70, 58, 40)
MORSE_TEXT = (240, 230, 210)
MORSE_FLASH = (255, 244, 214)    # her eyes on each beep
TIMER_COLOR = (120, 214, 190)   # the timer / alarm chip, top-right: soft mint
NOTICE_COLOR = (255, 196, 92)   # night-mode notices: warm amber, easy to spot
MAX_NOTICES = 10
# Notices go away on their own after this long, so last night's notices don't
# sit on the screen for days when nobody taps (CHATTY_NOTICE_HOURS=0: never).
NOTICE_MAX_AGE = float(os.getenv("CHATTY_NOTICE_HOURS", "12")) * 3600
# Safety net for the caption: clear it if nothing has updated it for this long
# (e.g. the voice node restarted mid-sentence and never sent "state:idle").
CAPTION_MAX_AGE = float(os.getenv("CHATTY_CAPTION_SECONDS", "120"))

# Recording indicator (top-left), shown only while Chatty is awake:
#   "full"    red pulsing dot + REC: the conversation's words are being logged
#   "private" grey PRIVATE: privacy mode, nothing is being saved
#   "stats"   grey STATS ONLY: timing/statistics logged, no words
#   "off"     nothing (logging disabled)
REC_RED = (235, 64, 64)
QUIET_STATES = ("idle", "sleepy", "resting")

# Sky (rain and lightning from the other nodes, see sky.py)
RAIN_HOLD = 30 * 60         # keep the raindrops this long after the last "sky:rain"
DROP = (78, 118, 178)       # soft blue raindrops behind her face
RED_ALERT = (255, 64, 52)      # Red Alert (tornado warning, red_alert.py): her eyes and the frame
RED_BAND = (58, 6, 6)          # the banner behind the words
RED_TEXT = (255, 226, 214)
RED_STALE = 600                # no word from the voice node this long: the red screen goes away
FLASH = (236, 232, 255)     # lightning: a pale lavender-white flash
COUNT_COLOR = (255, 226, 140)
COUNT_REAL = 10             # count "Mississippi"s in real seconds up to this, then hurry
NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
           "fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()

# Blush and hearts
BLUSH = (255, 92, 140)
HEART = (255, 70, 120)
HEART_EVERY = 0.7          # a new heart this often (seconds) in the love face
HEART_LIFE = 2.6           # how long each heart floats before it fades away

GOLD = (255, 204, 64)       # planet ring, stars and the raised finger in "actually"
TEAL = (64, 184, 220)
TIARA = (214, 190, 120)     # tarnished gold
TUX_WHITE = (226, 228, 232)  # Tiny's white bib and whiskers
EAR_PINK = (232, 150, 170)
CHART = (52, 58, 70)        # height-chart lines behind the "snapped" face

# Spooky mode: only on Halloween and Friday the 13th (CHATTY_FORCE_SPOOKY=1 to test).
# The cheeky face turns into a glowing red "evil robot" glare, just for fun.
SPOOKY_COLOR = (255, 48, 24)


def is_spooky_day(t: float | None = None) -> bool:
    import os
    if os.getenv("CHATTY_FORCE_SPOOKY") == "1":
        return True
    d = time.localtime(t or time.time())
    return (d.tm_mon == 10 and d.tm_mday == 31) or (d.tm_mday == 13 and d.tm_wday == 4)


def is_valentines_day(t: float | None = None) -> bool:
    """February 14th (or CHATTY_FORCE_VALENTINE=1 to test): a rosy idle face."""
    import os
    if os.getenv("CHATTY_FORCE_VALENTINE") == "1":
        return True
    d = time.localtime(t or time.time())
    return d.tm_mon == 2 and d.tm_mday == 14


def heart_points(cx: float, cy: float, size: float, n: int = 36):
    """Outline of a heart centered at (cx, cy), about `size` pixels wide."""
    k = size / 34.0
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * k, cy - y * k))
    return pts


def _lerp(a, b, t):
    return a + (b - a) * t


def _lerp_color(c1, c2, t):
    return tuple(int(_lerp(a, b, t)) for a, b in zip(c1, c2))


def _wrap(c, text: str, size: int, max_width: float, max_lines: int = 2) -> list:
    """Split text into lines that fit; the last line ends in '...' if cut."""
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and c.measure(trial, size) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    lines.append(current)
    if len(lines) > max_lines:
        last = " ".join(lines[max_lines - 1:])
        while c.measure(last + "...", size) > max_width and len(last) > 4:
            last = last[:-1].rstrip()
        lines = lines[:max_lines - 1] + [last + "..."]
    return lines


class FaceModel:
    def __init__(self, width: int, height: int, rng: random.Random | None = None):
        self.w, self.h = width, height
        self.rng = rng or random.Random()
        self.state = "idle"
        self.last_activity = time.time()

        exp = EXPRESSIONS["idle"]
        self.color = PALETTE["idle"]
        self.open = exp["open"]
        self.size = exp["size"]
        self.gaze = list(exp["gaze"])
        self.level = 0.0          # mouth openness while talking, 0..1
        self.target_level = 0.0
        self.caption = ""         # what Chatty heard (shown at the top)
        self.caption_at = 0.0     # when the caption last changed
        self.notices = []         # (when, text): shown instead of spoken at night
        self.rec_mode = "off"     # recording indicator, see REC_RED above
        self.dream_mix = 0.0      # 0 = face, 0.5 = blank, 1 = dream cloud
        self.game = None          # tic-tac-toe in progress, if any
        self.doodle = None        # a drawing in progress (screensaver), if any
        self.chess = None         # a chess game with another node, if any (chess_match.py)
        self.chess_paused = None  # (game, when) put aside when someone needed her
        self.chess_link = None    # chess_link.ChessLink, set by chatty_face (MQTT)
        self.mystery = None       # "Who's the Trickster?" (trickster.py); just waits while she talks
        self.next_game_at = 0.0
        self.ponder = None        # wondering about / asking another node, if any
        self.next_ponder_at = time.time() + self.rng.uniform(300, 600)
        self.ponder_turn = 0      # which node she wonders about next
        self.last_spoken = {}     # node -> when she last said something about it
        self.outbox = []          # messages for the voice node ("notify:...")
        self.asleep_since = 0.0
        self._was_asleep = False
        self.dream_item = None
        self.dream_started = 0.0
        self.listen_until = 0.0   # listening timer bar
        self.listen_total = 0.0
        self.love_since = 0.0     # when the love face started (hearts float from then)
        self.imagine_since = 0.0  # when the rainbow sweep started (imagine mood)
        self.imagined_aloud = 0.0  # when she last said a daydream out loud
        self.rain_until = 0.0     # raindrops behind her while it's raining (sky:rain)
        self.drops = []           # [x, y, speed, length]
        self.flash_at = 0.0       # last lightning flash
        self.thunder = None       # the "one Mississippi..." count: dict(start, seconds, miles)
        self.timer = None         # the next timer or alarm: dict(end, kind, label)
        self.snap_wanted = False  # the remote panel asked for a picture of the screen
        self.red_alert = None     # Red Alert (tornado warning): dict(until, test, title, seen)
        self.morse = None         # Morse being sent: dict(start, unit, letters, beeps, total) (morse.py)

        self.blink = 0.0          # 0 = no blink, 1 = fully closed
        self.next_blink = time.time() + self.rng.uniform(2, 5)
        self.blink_started = 0.0

        self.wink = 0.0           # 0 = open, 1 = left eye fully winked
        self.next_wink = 0.0
        self.drift = [0.0, 0.0]   # idle eye wandering
        self.next_drift = time.time() + self.rng.uniform(2, 4)
        self.drift_target = [0.0, 0.0]

    # ----- inputs -----
    def set_state(self, state: str, now: float | None = None):
        if state not in EXPRESSIONS:
            return
        now = now or time.time()
        if state in LOVE_STATES and self.state not in LOVE_STATES:
            self.love_since = now
        if state in IMAGINE_STATES and self.state not in IMAGINE_STATES:
            self.imagine_since = now
        self.state = state
        self.last_activity = now
        if state != "idle" and self.game:
            self.game = None          # a real conversation takes priority over playing
        if state != "idle" and self.ponder:
            self.ponder = None        # ...and over pondering
        if state != "idle" and self.doodle:
            self.doodle = None        # ...and over drawing
        if state != "idle" and self.chess:
            self._pause_chess(now)    # ...and over chess (she'll pick it up later)
        if state != "speaking":
            self.target_level = 0.0
        if state != "listening":
            self.listen_until = 0.0
        if state in ("idle", "sleepy", "resting"):
            self.caption = ""

    def set_red_alert(self, value: str, now: float | None = None):
        """'redalert:<until>:<test|>:<title>' from the voice node (red_alert.py), or 'redalert:off'.
        The voice node repeats it every 30 s while the warning lasts."""
        now = now or time.time()
        parts = (value or "").strip().split(":", 2)
        if parts[0] in ("", "off") or len(parts) < 3:
            self.red_alert = None
            return
        try:
            until = float(parts[0])
        except ValueError:
            return
        if not self.red_alert:
            self.calm(now)                  # put the pencils / board / game away
            self.dream_mix, self.dream_item = 0.0, None
        self.red_alert = dict(until=until, test=parts[1] == "test",
                              title=parts[2].strip()[:40] or "Tornado Warning", seen=now,
                              since=(self.red_alert or {}).get("since", now))

    def set_morse(self, value: str, now: float | None = None):
        """'<start>:<dit seconds>:<code>' from the voice node as the beeps start, or 'off'.
        The tape and the flashing eyes follow the same timing as the sound."""
        now = now or time.time()
        parts = (value or "").strip().split(":", 2)
        if parts[0] in ("", "off") or len(parts) < 3:
            self.morse = None
            return
        try:
            start, unit = float(parts[0]), float(parts[1])
        except ValueError:
            return
        code = morse.clean_code(parts[2])[:400]
        if not code or unit <= 0:
            self.morse = None
            return
        beeps, t, letters = [], 0, []      # beeps: (from, to, letter, dah?) in dits
        for on, n, letter in morse.elements(code):
            if on:
                beeps.append((t, t + n, letter, n > 1))
            t += n
        words = code.split(" / ")
        for wi, word in enumerate(words):
            for li, part in enumerate(word.split()):
                letters.append((morse.LETTERS.get(part, "?"), wi > 0 and li == 0))
        self.morse = dict(start=start, unit=unit, letters=letters, beeps=beeps, total=t)
        self.last_activity = now

    def morse_now(self, now: float):
        """(dits into the message, tone on?) while Morse is showing, else None
        (the tape stays up 3 s after the last beep)."""
        m = self.morse
        if not m:
            return None
        t = (now - m["start"]) / m["unit"]
        if t > m["total"] + 3.0 / m["unit"] or t < -10.0 / m["unit"]:
            self.morse = None
            return None
        return t, any(a <= t < b for a, b, _, _ in m["beeps"])

    def red_on(self, now: float | None = None) -> bool:
        """Is the Red Alert showing? (It goes away by itself if the voice node stops
        talking about it for RED_STALE seconds, so a crash can't leave it red.)"""
        r = self.red_alert
        if not r:
            return False
        now = now or time.time()
        if now - r["seen"] > RED_STALE:
            self.red_alert = None
            return False
        return True

    def set_timer(self, value: str):
        """'1730900000:timer:10 minute', '1730900000:alarm:7:00 AM', or '' for none."""
        end, _, rest = (value or "").partition(":")
        kind, _, label = rest.partition(":")
        try:
            self.timer = {"end": float(end), "kind": kind or "timer", "label": label}
        except ValueError:
            self.timer = None

    def timer_text(self, now: float) -> str:
        """'9:42' counting down for a timer, 'Alarm 7:00 AM' for an alarm, '' for none."""
        t = self.timer
        if not t or t["end"] < now - 5:
            return ""
        if t["kind"] == "alarm":
            return f"Alarm {t['label']}"
        left = max(0, int(t["end"] - now + 0.999))
        h, rest = divmod(left, 3600)
        m, s = divmod(rest, 60)
        return f"Timer {h}:{m:02d}:{s:02d}" if h else f"Timer {m}:{s:02d}"

    def set_rec(self, mode: str):
        self.rec_mode = mode if mode in ("full", "private", "stats", "off") else "off"

    # ----- games -----
    def start_game(self, human: bool, now: float | None = None):
        if not GAMES:
            return
        now = now or time.time()
        if self.state != "idle":
            self.set_state("idle", now)
        self._pause_chess(now)
        self.mystery = None
        self.game = games.TicTacToe(human, self.rng, now)

    # ----- doodles (screensaver) -----
    def start_doodle(self, style: str | None = None, now: float | None = None) -> bool:
        if style == "imagine":
            return self.start_daydream(now=now)
        if not doodles.ENABLED:
            return False
        now = now or time.time()
        if self.state != "idle":
            self.set_state("idle", now)
        self.game = self.ponder = self.mystery = None
        self._pause_chess(now)
        raining = self.raining(now)
        if style is None and raining and "rain" in doodles.styles() and self.rng.random() < 0.7:
            style = "rain"      # it's raining for real: her code rain turns into blue rain
        self.doodle = doodles.Doodle(self.rng, now, style, raining=raining)
        return True

    # ----- daydreams (imagine.py): a rainbow and a made-up idea, on the screen -----
    def start_daydream(self, topic: str = "", now: float | None = None) -> bool:
        if not imagine.ENABLED:
            return False
        now = now or time.time()
        if self.state != "idle":
            self.set_state("idle", now)
        self.game = self.ponder = self.mystery = None
        self._pause_chess(now)
        self.doodle = imagine.Daydream(self.rng, now, topic)   # it lives in the doodle slot
        return True

    def _maybe_say_daydream(self, now: float):
        """Once a daydream is typed out, she may say it (daytime, free, now and then)."""
        d = self.doodle
        if (not isinstance(d, imagine.Daydream) or d.spoken or not imagine.SPEAK
                or not d.finished_typing(now) or self.state != "idle"):
            return
        d.spoken = True                     # decided either way: one chance per daydream
        hour = time.localtime(now).tm_hour
        if (9 <= hour < 21 and not quiet_hours.is_night(now)
                and now - self.imagined_aloud > imagine.SPEAK_GAP):
            self.imagined_aloud = now
            self.outbox.append("notify:imagine:" + d.text)

    # ----- chess with another node -----
    def start_chess(self, opponent: str | None = None, now: float | None = None) -> bool:
        if not chess_match.ENABLED:
            return False
        now = now or time.time()
        if self.state != "idle":
            self.set_state("idle", now)
        self.game = self.doodle = self.ponder = self.mystery = None
        paused = self.chess_paused
        self.chess_paused = None
        if paused and (not opponent or chess_match._key(opponent) == paused[0].opponent):
            self.chess = paused[0]            # finish the game we started
            self.chess.resume(now)
        else:
            name = chess_match.pick_opponent(self.chess_link, self.rng, opponent)
            self.chess = chess_match.ChessMatch(name, self.rng, now, link=self.chess_link)
        return True

    def start_mail_chess(self, match, now: float | None = None) -> bool:
        """Show a game by letter (chess_mail.MailMatch): Claude's move and her answer."""
        if not chess_match.ENABLED:
            return False
        now = now or time.time()
        if self.state != "idle" or self.mystery:
            return False          # she's busy; the board can wait for the next letter
        self.game = self.doodle = self.ponder = None
        self._pause_chess(now)    # a game with a node waits (she picks it up later)
        self.chess = match
        self.last_activity = now
        return True

    # ----- Who's the Trickster? -----
    def start_mystery(self, human: bool = False, now: float | None = None) -> bool:
        if not trickster.ENABLED:
            return False
        now = now or time.time()
        if self.state != "idle":
            self.set_state("idle", now)
        self.game = self.doodle = self.ponder = None
        self._pause_chess(now)
        self.mystery = trickster.Mystery(self.rng, now, human=human)
        self.last_activity = now
        return True

    def mystery_message(self, value: str, now: float | None = None) -> bool:
        """'' starts a game, 'meeting' rings the bell, 'vote:<node>' votes (tap, panel or voice)."""
        now = now or time.time()
        what, _, arg = (value or "").strip().lower().partition(":")
        if not what:
            return self.start_mystery(human=True, now=now)
        if not self.mystery:
            return False
        self.last_activity = now
        if what == "meeting":
            return self.mystery.call_meeting("you")
        if what == "vote":
            return self.mystery.vote(arg)
        return False

    def _pause_chess(self, now: float):
        if self.chess and not self.chess.result and not getattr(self.chess, "mail", False):
            self.chess_paused = (self.chess, now)   # a game by letter is just put away
        self.chess = None

    # ----- sky: rain and lightning from the other nodes -----
    def raining(self, now: float | None = None) -> bool:
        return (now or time.time()) < self.rain_until

    def set_sky(self, value: str, now: float | None = None):
        """'rain', 'dry' or 'strike:<miles>' (see sky.py)."""
        now = now or time.time()
        kind, _, arg = value.strip().lower().partition(":")
        if kind == "rain":
            self.rain_until = now + RAIN_HOLD
        elif kind == "dry":
            self.rain_until = 0.0
        elif kind == "strike":
            self.flash_at = now
            try:
                miles = max(0.0, float(arg)) if arg else None
            except ValueError:
                miles = None
            if not self.thunder:      # one count at a time; more strikes just flash
                seconds = None if miles is None else max(1, round(miles * 5))
                self.thunder = dict(start=now, seconds=seconds, miles=miles)

    def _thunder_text(self, now: float):
        """(text, done) for the Mississippi count, or (None, True) when it's over."""
        th = self.thunder
        t = now - th["start"] - 0.6           # a beat after the flash
        n = th["seconds"]
        if n is None or (th["miles"] or 0) > 10:
            # too far to hear thunder: just say how far
            return (f"Lightning, about {round(th['miles'])} miles away" if n else
                    "Lightning, far away"), t > 6
        # count in real seconds up to COUNT_REAL, then hurry (4 a second) to the answer
        if t < 0:
            return "", False
        count = int(t) + 1 if t < COUNT_REAL else COUNT_REAL + int((t - COUNT_REAL) * 4) + 1
        if count <= n:
            word = NUMBERS[count] if count < len(NUMBERS) else str(count)
            return f"{word[:1].upper()}{word[1:]} Mississippi...", False
        end = COUNT_REAL + (n - COUNT_REAL) / 4 if n > COUNT_REAL else n
        mi = th["miles"]
        where = "Less than a mile away!" if mi < 1 else f"About {round(mi)} mile{'s' if round(mi) != 1 else ''} away"
        return f"Boom! {where}", t > end + 4

    # ----- pondering -----
    def start_ponder(self, node: str | None = None, now: float | None = None) -> bool:
        now = now or time.time()
        names = nodes.enabled()
        if node not in names:
            if not names:
                return False
            node = names[self.ponder_turn % len(names)]
            self.ponder_turn += 1
        if self.state != "idle":
            self.set_state("idle", now)
        self.game = self.doodle = self.mystery = None
        self._pause_chess(now)
        self.ponder = pondering.Ponder(node, self.rng, now)
        return True

    def _finish_ponder(self, now: float):
        r = self.ponder.reading
        self.ponder = None
        self.next_ponder_at = now + PONDER_EVERY * self.rng.uniform(0.7, 1.3)
        self.next_game_at = max(self.next_game_at, now + 60)
        if not (r and r.ok and r.spoken and PONDER_SPEAK):
            return
        hour = time.localtime(now).tm_hour
        if 9 <= hour < 21 and now - self.last_spoken.get(r.node, 0) > SPEAK_GAP:
            self.last_spoken[r.node] = now
            self.outbox.append("notify:" + r.spoken)

    def add_notice(self, text: str, now: float | None = None):
        """A notice to show on screen until tapped (night mode)."""
        text = (text or "").strip()
        if not text:
            return
        # the same notice again (e.g. another failed SSH login) replaces the old
        # one instead of piling up as "+N more"
        self.notices = [(when, old) for when, old in self.notices if old != text]
        self.notices.append((now or time.time(), text))
        del self.notices[:-MAX_NOTICES]

    def _expire_notices(self, now: float):
        if NOTICE_MAX_AGE > 0 and self.notices:
            self.notices = [(when, text) for when, text in self.notices
                            if now - when < NOTICE_MAX_AGE]

    def handle_tap(self, pos, now: float | None = None) -> bool:
        """A tap on the screen. True if the face used it (so it shouldn't wake the voice)."""
        now = now or time.time()
        if self.red_on(now):
            self.notices = []           # and the tap goes on to stop the alarm
            self.last_activity = now
            return False
        if self.notices:
            # first tap just dismisses the notices, so reading them at night
            # doesn't make her start talking
            self.notices = []
            self.last_activity = now
            return True
        if self.doodle and self.state == "idle":
            # a tap puts the pencils down (without waking the voice)
            self.doodle = None
            self.last_activity = now
            self.next_game_at = now + self.rng.uniform(120, 300)
            return True
        if self.mystery and self.state == "idle":
            used = self.mystery.tap(pos, self.w, self.h)   # the bell, or a vote
            self.last_activity = now
            if used is None:                               # anywhere else: put the game away
                self.mystery = None
                self.next_game_at = now + self.rng.uniform(120, 300)
            return True
        if self.chess and self.state == "idle":
            # a tap hides the board (without waking the voice); the game waits for later
            self._pause_chess(now)
            self.last_activity = now
            self.next_game_at = now + self.rng.uniform(120, 300)
            return True
        if self.game and self.state == "idle":
            cell = self.game.cell_at(self.w, self.h, pos)
            if cell is not None:
                self.game.tap(cell, now)
                self.last_activity = now
                return True
        return False

    def calm(self, now: float | None = None) -> None:
        """Put down the pencils, chess board and game (the remote panel's "stop"),
        like a tap, but without dismissing notices or waking her."""
        now = now or time.time()
        if self.chess:
            self._pause_chess(now)
        self.doodle = self.game = self.ponder = self.mystery = None
        self.last_activity = now
        self.next_game_at = now + self.rng.uniform(120, 300)

    def activity(self) -> str:
        """What she's busy with on screen: '', 'doodle:<style>', 'chess:<node>', 'game', 'ponder'."""
        if self.doodle:
            return f"doodle:{getattr(self.doodle, 'style', '')}"
        if self.chess:
            return f"chess:{getattr(self.chess, 'opponent', '')}"
        if self.mystery:
            return "trickster"
        if self.game:
            return "game"
        if self.ponder:
            return "ponder"
        return ""

    def panel_info(self) -> dict:
        """What the remote panel shows next to the picture of the screen."""
        return {"state": self.state, "notices": [t for _, t in self.notices],
                "red_alert": bool(self.red_on()),
                "activity": self.activity(), "caption": self.caption,
                "timer": self.timer, "ts": time.time(),
                "mystery": self.mystery.panel_info() if self.mystery else None}

    def set_caption(self, text: str, now: float | None = None):
        self.caption = (text or "").strip()
        self.caption_at = now or time.time()

    def set_listen(self, seconds: float, now: float | None = None):
        """Show a shrinking bar: how long Chatty will keep listening."""
        now = now or time.time()
        self.listen_total = max(0.1, seconds)
        self.listen_until = now + seconds

    def set_level(self, level: float):
        self.target_level = max(0.0, min(1.0, level))

    # ----- animation -----
    def busy(self) -> bool:
        """True when something is moving and the screen needs a high frame rate."""
        now = time.time()
        asleep = self.state in ("sleepy", "resting")
        if self.red_on(now):
            return True   # the pulsing red frame
        if self.ponder and self.state == "idle":
            return True   # thought bubble and signal waves are animated
        if self.doodle and self.state == "idle":
            return True   # drawing (chatty_face runs doodles at doodles.FPS)
        if self.chess and self.state == "idle":
            return True   # chess (chatty_face runs it at chess_match.FPS)
        if self.mystery and self.state == "idle":
            return True   # the mystery game (chatty_face runs it at trickster.FPS)
        if self.thunder or now - self.flash_at < 0.5:
            return True   # lightning flash and the Mississippi count
        if self.morse:
            return True   # the telegraph tape and the flashing eyes
        return (self.state in ("speaking", "listening", "thinking", "mischief", "mischief_talk", "puzzled",
                                "love", "love_talk", "actually", "actually_talk",
                                "snapped_talk", "tiny", "tiny_talk") + IMAGINE_STATES
                or (not asleep and (self.blink > 0 or self.next_blink - now < 0.3))  # smooth blinks
                or (self.state == "resting" and self.open > 0.08)  # still closing its eyes
                or abs(self.level - self.target_level) > 0.01)

    def update(self, dt: float, now: float | None = None):
        now = now or time.time()
        self._expire_notices(now)
        self._update_sky(dt, now)
        red = self.red_on(now)
        if red:
            # wide awake: no games, no dozing, no dreams, full brightness (see chatty_face)
            if self.chess:
                self._pause_chess(now)
            self.doodle = self.game = self.ponder = self.mystery = None
            if self.state in ("sleepy", "resting"):
                self.state = "idle"
            self.last_activity = now
        if self.caption and CAPTION_MAX_AGE > 0 and now - self.caption_at > CAPTION_MAX_AGE:
            self.caption = ""

        # bored? wonder about the other nodes, or play a game (she'd rather do that than doze)
        if self.ponder:
            self.ponder.update(now)
            if self.ponder.done:
                self._finish_ponder(now)
        elif self.doodle:
            self.doodle.update(now)
            self._maybe_say_daydream(now)
            if self.doodle.done:
                dreamy = isinstance(self.doodle, imagine.Daydream)
                self.doodle = None
                if not dreamy and self.rng.random() < 0.5 and now - self.last_activity < sleepy_after(now):
                    self.doodle = doodles.Doodle(self.rng, now)    # another one!
                else:
                    self.next_game_at = now + self.rng.uniform(120, 300)
        elif self.mystery:
            if self.state == "idle":
                self.mystery.update(now)
                if self.mystery.done:
                    self.mystery = None
                    self.next_game_at = now + self.rng.uniform(300, 600)
            elif now - self.mystery.last_now > trickster.FORGET_AFTER:
                self.mystery = None       # she's been busy a long time; it's forgotten
        elif self.chess:
            self.chess.update(now)
            if self.chess.done:
                self.chess = None
                self.next_game_at = now + self.rng.uniform(300, 600)
        elif self.game:
            self.game.update(now)
            if self.game.done:
                human = self.game.human
                self.game = None
                if human:
                    self.last_activity = now        # you just played with her
                elif self.rng.random() < 0.4:
                    self.game = games.TicTacToe(False, self.rng, now)   # one more!
                self.next_game_at = now + self.rng.uniform(120, 300)
        elif (self.state == "idle" and now - self.last_activity > BORED_AFTER
              and now - self.last_activity < sleepy_after(now)):
            paused = self.chess_paused
            if paused and now - paused[1] > chess_match.RESUME_WITHIN:
                self.chess_paused = paused = None     # too long ago; a fresh game next time
            if paused and now >= self.next_game_at:
                self.start_chess(now=now)             # back to the unfinished game
            elif CURIOUS and now >= self.next_ponder_at and nodes.enabled():
                self.start_ponder(now=now)
            elif (trickster.ENABLED and now >= self.next_game_at
                  and self.rng.random() < trickster.SHARE):
                self.start_mystery(now=now)         # she hosts a little mystery
            elif (chess_match.ENABLED and now >= self.next_game_at
                  and self.rng.random() < chess_match.SHARE):
                self.start_chess(now=now)           # she decides to challenge a node
            elif (imagine.ENABLED and now >= self.next_game_at
                  and self.rng.random() < imagine.SHARE):
                self.start_daydream(now=now)        # she daydreams a little
            elif (GAMES or doodles.ENABLED) and now >= self.next_game_at:
                if doodles.ENABLED and (not GAMES or self.rng.random() < doodles.SHARE):
                    self.start_doodle(now=now)      # she draws instead
                else:
                    self.game = games.TicTacToe(False, self.rng, now)

        if (self.state == "idle" and not self.game and not self.ponder and not self.doodle and not self.chess
                and not self.mystery and now - self.last_activity > sleepy_after(now)):
            self.state = "sleepy"

        # dreams: a while after falling asleep, the face fades into a dream cloud
        asleep = self.state in ("sleepy", "resting")
        if asleep and not self._was_asleep:
            self.asleep_since = now
        self._was_asleep = asleep
        if not asleep:
            self.dream_mix, self.dream_item = 0.0, None   # wake up instantly
        elif dreams.ENABLED and now - self.asleep_since > dreams.DELAY:
            self.dream_mix = min(1.0, self.dream_mix + dt / 4.0)  # ~2 s face out, ~2 s dream in
            if self.dream_mix >= 0.5 and (self.dream_item is None or
                                          now - self.dream_started > dreams.ITEM_SECONDS):
                self.dream_item = dreams.pick(self.rng, self.dream_item)
                self.dream_started = now

        exp = dict(EXPRESSIONS[self.state])
        target_color = PALETTE[self.state]
        if self.state in IMAGINE_STATES:
            target_color = imagine.hue_color(now - self.imagine_since)   # eyes cycle the rainbow
        if self.state in ("mischief", "mischief_talk") and is_spooky_day(now):
            target_color = SPOOKY_COLOR
            exp["open"] = 0.38          # narrow, glowing glare
            exp["gaze"] = (0.0, 0.0)    # staring right at you
        mnow = self.morse_now(now)
        if red:
            target_color = RED_ALERT    # alert red eyes, wide open, looking right at you
            exp["open"], exp["gaze"] = max(exp["open"], 1.08), (0.0, 0.0)
        # falling asleep is slow and gentle (~2 s); everything else is quick
        ease = min(1.0, dt * (1.2 if self.state == "resting" else 8))
        self.color = _lerp_color(self.color, target_color, ease)
        if mnow and mnow[1] and not red:
            self.color = _lerp_color(self.color, MORSE_FLASH, 0.75)   # eyes flash with each beep
        self.open = _lerp(self.open, exp["open"], ease)
        self.size = _lerp(self.size, exp["size"], ease)

        # wandering gaze when idle; slow circling while thinking
        if self.state == "idle":
            if now > self.next_drift:
                self.drift_target = [self.rng.uniform(-0.5, 0.5), self.rng.uniform(-0.25, 0.25)]
                if self.rng.random() < 0.4:
                    self.drift_target = [0.0, 0.0]
                self.next_drift = now + self.rng.uniform(1.5, 4.5)
        elif self.state == "thinking":
            a = now * 1.6
            self.drift_target = [0.18 * math.cos(a), 0.12 * math.sin(a)]
        else:
            self.drift_target = [0.0, 0.0]
        for i in range(2):
            self.drift[i] = _lerp(self.drift[i], self.drift_target[i], min(1.0, dt * 6))
            self.gaze[i] = _lerp(self.gaze[i], exp["gaze"][i], ease)

        # cheeky wink: a quick left-eye wink every few seconds
        if self.state in ("mischief", "mischief_talk"):
            if self.next_wink == 0.0:
                self.next_wink = now + 0.6
            t = (now - self.next_wink) / 0.45
            if 0 <= t < 1:
                self.wink = math.sin(t * math.pi)
            elif t >= 1:
                self.wink = 0.0
                self.next_wink = now + self.rng.uniform(2.5, 4.5)
        else:
            self.wink = 0.0
            self.next_wink = 0.0

        # blinking (not while asleep, and not with happy closed eyes)
        if self.state not in ("sleepy", "resting") + LOVE_STATES:
            if self.blink_started == 0.0 and now > self.next_blink:
                self.blink_started = now
            if self.blink_started:
                t = (now - self.blink_started) / 0.16  # 160 ms blink
                self.blink = 1 - abs(1 - 2 * t) if t < 1 else 0.0
                if t >= 1:
                    self.blink_started = 0.0
                    gap = self.rng.uniform(2.5, 6.0)
                    if self.rng.random() < 0.15:
                        gap = 0.25  # occasional double blink
                    self.next_blink = now + gap
        else:
            self.blink = 0.0

        # mouth follows the voice: open fast, close a bit slower
        rate = 25 if self.target_level > self.level else 12
        self.level = _lerp(self.level, self.target_level, min(1.0, dt * rate))

    def _update_sky(self, dt: float, now: float):
        if self.thunder:
            _, done = self._thunder_text(now)
            if done:
                self.thunder = None
        if not self.raining(now):
            self.drops = []
            return
        w, h = self.w, self.h
        if not self.drops:
            self.drops = [[self.rng.uniform(0, w * 1.1), self.rng.uniform(-h, h),
                           self.rng.uniform(0.55, 1.0), self.rng.uniform(0.03, 0.06)] for _ in range(26)]
        for d in self.drops:
            d[1] += d[2] * h * 0.9 * min(dt, 0.25)
            d[0] -= d[2] * h * 0.12 * min(dt, 0.25)      # a little slant
            if d[1] > h:
                d[0], d[1] = self.rng.uniform(0, w * 1.1), -self.rng.uniform(0, h * 0.2)

    def _draw_drops(self, c, now: float):
        if not self.drops or (self.doodle and self.state == "idle"):
            return      # a doodle has the whole screen (and its own rain)
        asleep = self.state in ("sleepy", "resting")
        col = _lerp_color(BACKGROUND, DROP, 0.5 if asleep else 1.0)
        h = self.h
        lw = max(2, int(h * 0.006))
        for x, y, speed, length in self.drops:
            dy = length * h
            c.line(col, (x, y), (x - dy * 0.13, y + dy), lw)

    def _draw_sky_over(self, c, now: float):
        """The lightning flash and the Mississippi count, on top of everything."""
        w, h = self.w, self.h
        t = now - self.flash_at
        if t < 0.42:
            # bright, dark, bright again (fading): how lightning flickers
            k = 1.0 if t < 0.07 else 0.0 if t < 0.16 else max(0.0, 0.7 * (1 - (t - 0.16) / 0.26))
            if self.state in ("sleepy", "resting") or quiet_hours.is_night(now):
                k *= 0.3        # gentle in a dark room
            if k > 0.02:
                c.rrect(_lerp_color(BACKGROUND, FLASH, k), (0, 0, w, h), 0)
        if self.thunder and self.state in QUIET_STATES:
            text, _ = self._thunder_text(now)
            if text:
                size = max(16, int(h * 0.06))
                c.text(text, ((w - c.measure(text, size)) / 2, h * 0.035), size, COUNT_COLOR)

    # ----- drawing -----
    def draw(self, c, now: float | None = None):
        now = now or time.time()
        self._draw_main(c, now)
        self._draw_sky_over(c, now)
        if self.morse and not self.red_on(now):
            self._draw_morse(c, now)
        if self.red_on(now):
            self._draw_red_alert(c, now)

    def _draw_morse(self, c, now):
        """A little telegraph tape near the bottom: a lamp that lights with each beep,
        the dits and dahs scrolling by, and each letter written under its marks once sent."""
        mn = self.morse_now(now)
        if not mn:
            return
        t, on = mn
        m = self.morse
        w, h = self.w, self.h
        bx, by, bw, bh = w * 0.05, h * 0.725, w * 0.90, h * 0.145
        c.rrect(MORSE_TAPE, (bx, by, bw, bh), radius=bh * 0.22)
        # the lamp
        r = bh * 0.27
        lx, ly = bx + bh * 0.5, by + bh * 0.5
        if on:
            c.ellipse(_lerp_color(MORSE_TAPE, MORSE_LAMP, 0.35), (lx - r * 1.45, ly - r * 1.45, r * 2.9, r * 2.9))
        c.ellipse(MORSE_LAMP if on else MORSE_LAMP_OFF, (lx - r, ly - r, 2 * r, 2 * r))
        # lay out the marks: u = one dit wide
        u = bh * 0.16
        x0, x1 = bx + bh * 1.05, bx + bw - bh * 0.3
        sy = by + bh * 0.24
        marks, x, letter_x, last_letter = [], 0.0, {}, -1
        for a, b, letter, dah in m["beeps"]:
            if a > t:
                break
            if letter != last_letter:
                if last_letter >= 0:
                    x += u * (4.5 if m["letters"][letter][1] else 2.2)
                letter_x[letter] = [x, x]
                last_letter = letter
            width = u * (3 if dah else 1)
            marks.append((x, width, a <= t < b))
            x += width + u * 0.9
            letter_x[letter][1] = x - u * 0.9
        shift = max(0.0, x - (x1 - x0))                # scroll so the newest marks stay in view
        for mx, width, now_on in marks:
            px = x0 + mx - shift
            if px + width < x0:
                continue
            color = MORSE_LAMP if now_on else MORSE_MARK
            c.rrect(color, (px, sy, width, u), radius=u / 2)
        # the letters, once each one is fully sent
        size = max(14, int(bh * 0.36))
        sent = {letter for a, b, letter, _ in m["beeps"] if b <= t}
        done = {lt for lt in sent if all(b <= t for _, b, l2, _ in m["beeps"] if l2 == lt)}
        for letter, (a, b) in letter_x.items():
            if letter not in done:
                continue
            ch = m["letters"][letter][0]
            cx = x0 + (a + b) / 2 - shift
            if cx < x0:
                continue
            c.text(ch, (cx - c.measure(ch, size) / 2, sy + u * 1.6), size, MORSE_TEXT)

    def _draw_red_alert(self, c, now):
        """A pulsing red frame and a banner: TORNADO WARNING / Take shelter now."""
        w, h = self.w, self.h
        r = self.red_alert
        pulse = 0.5 + 0.5 * math.sin((now - r["since"]) * math.pi * 1.6)   # ~0.8 beats a second
        frame = _lerp_color(RED_BAND, RED_ALERT, 0.35 + 0.65 * pulse)
        t = max(6, int(min(w, h) * (0.025 + 0.012 * pulse)))
        for rect in ((0, 0, w, t), (0, h - t, w, t), (0, 0, t, h), (w - t, 0, t, h)):
            c.rrect(frame, rect, 0)
        # the banner at the top
        title = r["title"].upper()
        if r["test"]:
            title = "TEST - " + title
        size = max(20, int(h * 0.075))
        while c.measure(title, size) > w * 0.86 and size > 14:
            size -= 2
        until = ""
        if r["until"] > now:
            d = time.localtime(r["until"])
            until = f" - until {d.tm_hour % 12 or 12}:{d.tm_min:02d} {'AM' if d.tm_hour < 12 else 'PM'}"
        sub = "Take shelter now" + until
        ssize = max(14, int(h * 0.045))
        band_h = size * 1.2 + ssize * 1.4 + h * 0.025
        c.rrect(RED_BAND, (t + w * 0.03, t + h * 0.01, w - 2 * t - w * 0.06, band_h), radius=h * 0.03)
        y = t + h * 0.025
        c.text(title, ((w - c.measure(title, size)) / 2, y), size, _lerp_color(RED_ALERT, RED_TEXT, pulse))
        c.text(sub, ((w - c.measure(sub, ssize)) / 2, y + size * 1.2), ssize, RED_TEXT)
        # and at the bottom, what a tap does
        hint = "Red alert - tap when you're safe"
        hsize = max(14, int(h * 0.05))
        hw = c.measure(hint, hsize)
        top = h * 0.87                    # covers the usual status line
        c.rrect(RED_BAND, ((w - hw) / 2 - w * 0.03, top, hw + w * 0.06, h - t - top - h * 0.01), radius=h * 0.02)
        c.text(hint, ((w - hw) / 2, top + h * 0.02), hsize, RED_TEXT)

    def _draw_main(self, c, now):
        w, h = self.w, self.h
        c.fill(BACKGROUND)
        self._draw_drops(c, now)

        if self.ponder and self.state == "idle":
            self.ponder.draw(c, w, h, now)
            self._status(c, now)
            return
        if self.doodle and self.state == "idle":
            self.doodle.draw(c, w, h, now)
            self._status(c, now)
            return
        if self.chess and self.state == "idle":
            self.chess.draw(c, w, h, now)
            self._status(c, now)
            return
        if self.mystery and self.state == "idle":
            self.mystery.draw(c, w, h, now)
            self._status(c, now)
            return
        if self.game and self.state == "idle":
            self.game.draw(c, w, h, now)
            self._status(c, now)
            return

        if self.dream_mix > 0:
            if self.dream_mix >= 0.5:
                self._draw_dream(c, now)
                self._status(c, now)
                return
            # first half of the transition: the sleeping face fades out
            saved = self.color
            self.color = _lerp_color(BACKGROUND, saved, 1 - 2 * self.dream_mix)
            try:
                self._draw_face(c, now)
            finally:
                self.color = saved
            return
        self._draw_face(c, now)

    def _draw_dream(self, c, now):
        w, h = self.w, self.h
        k = min(1.0, 2 * self.dream_mix - 1)          # cloud fades in
        night = self.state == "resting"
        cloud = _lerp_color(BACKGROUND, (18, 22, 38) if night else (26, 32, 54), k)
        dreams.draw_cloud(c, w, h, now, cloud)
        dreams.draw_sleeper(c, w, h, now, _lerp_color(BACKGROUND, self.color, k), cloud)
        if self.dream_item:
            t = now - self.dream_started
            envelope = max(0.0, min(1.0, t / 2.5, (dreams.ITEM_SECONDS - t) / 2.5))
            dreams.draw_item(c, w, h, now, self.dream_item, self.dream_started,
                             k * envelope, 1.0 if night else 0.0, cloud)

    def _draw_face(self, c, now):
        w, h = self.w, self.h

        bob = math.sin(now * 1.3) * h * 0.006  # gentle "breathing"
        gx = (self.gaze[0] + self.drift[0]) * w * 0.035
        gy = (self.gaze[1] + self.drift[1]) * h * 0.05

        eye_w = w * 0.14 * self.size
        eye_h = h * 0.34 * self.size
        cy = h * 0.42 + bob + gy
        openness = max(0.04, self.open * (1 - self.blink))

        if self.state in TINY_STATES:
            self._cat_ears(c, now, bob)
        if self.state in SNAPPED_STATES:
            self._height_chart(c)        # booking-photo wall behind her
        if self.state in ACTUALLY_STATES:
            self._cosmos_back(c, now)   # drawn first, so the planet passes behind her eyes
        if self.state in IMAGINE_STATES:
            # both hands sweep a rainbow open over her head
            imagine.draw_rainbow(c, w, h, now, self.imagine_since, box=(w * 0.04, h * 0.06 + bob, w * 0.92, h * 1.0))

        love = self.state in LOVE_STATES
        valentine = self.state == "idle" and is_valentines_day(now)
        if love or valentine:
            self._blush(c, cy, eye_w, eye_h, strong=love)

        for side, cx in (("left", w * 0.34), ("right", w * 0.66)):
            ex = cx + gx
            if love:
                # happy closed eye: an upside-down U, like ^
                aw, ah = eye_w * 1.05, eye_h * 0.5
                c.arc(self.color, (ex - aw / 2, cy - ah * 0.2, aw, ah), math.pi * 0.06, math.pi * 0.94,
                      max(7, int(h * 0.032)))
                continue
            this_open = openness
            if self.state == "puzzled" and side == "right":
                this_open *= 0.55
            if side == "left" and self.wink > 0:
                this_open *= max(0.06, 1 - self.wink)
            eh = max(eye_h * this_open, h * 0.018)
            rect = (ex - eye_w / 2, cy - eh / 2, eye_w, eh)
            c.rrect(self.color, rect, radius=min(eye_w, eh) * 0.45)
            # small highlight makes the eyes feel alive
            if eh > eye_h * 0.4:
                r = eye_w * 0.11
                hx, hy = ex - eye_w * 0.2, cy - eh * 0.28
                c.ellipse(_lerp_color(self.color, (255, 255, 255), 0.75),
                          (hx - r, hy - r, 2 * r, 2 * r))

        # imagining: a twinkling star in each eye
        if self.state in IMAGINE_STATES:
            for i, cx0 in enumerate((w * 0.34, w * 0.66)):
                eh = max(eye_h * openness, h * 0.018)
                if eh > eye_h * 0.4:
                    tw = 0.8 + 0.2 * math.sin(now * 5 + i * 1.3)
                    imagine.star(c, (255, 255, 255), cx0 + gx + eye_w * 0.16, cy + eh * 0.12, eye_w * 0.09 * tw)

        # Tiny: vertical slit pupils glancing sideways, a heavy lid, whiskers
        if self.state in TINY_STATES:
            for cx0 in (w * 0.34, w * 0.66):
                ex = cx0 + gx
                eh = max(eye_h * openness, h * 0.018)
                if eh > eye_h * 0.3:
                    px = ex + self.gaze[0] * eye_w * 0.22
                    pw, ph = eye_w * 0.2, eh * 0.78
                    c.ellipse(BACKGROUND, (px - pw / 2, cy - ph / 2, pw, ph))
                # a flat, unimpressed upper lid
                c.rrect(BACKGROUND, (ex - eye_w * 0.6, cy - eh / 2 - h * 0.02, eye_w * 1.2, eh * 0.28 + h * 0.02), 0)
            self._whiskers(c, now, cy + eye_h * 0.62)

        # well, actually: left brow level, right brow raised high
        if self.state in ACTUALLY_STATES:
            lx, rx = w * 0.34 + gx, w * 0.66 + gx
            top = cy - eye_h * 0.5
            c.line(self.color, (lx - eye_w * 0.5, top - h * 0.02), (lx + eye_w * 0.5, top - h * 0.03), 8)
            c.arc(self.color, (rx - eye_w * 0.6, top - h * 0.12, eye_w * 1.2, h * 0.12),
                  math.pi * 0.1, math.pi * 0.9, 8)

        # snapped: heavy, flat brows pressed down on the eyes, then a crooked tiara
        if self.state in SNAPPED_STATES:
            top = cy - eye_h * self.size * self.open * 0.5 - h * 0.025
            for ex, tilt in ((w * 0.34 + gx, 1), (w * 0.66 + gx, -1)):
                c.line(self.color, (ex - eye_w * 0.6, top - h * 0.012 * tilt),
                       (ex + eye_w * 0.6, top + h * 0.012 * tilt), 9)
            self._tiara(c, top - h * 0.03, gx)

        # puzzled: raised brow over the squinting eye
        if self.state == "puzzled":
            bx = w * 0.66 + gx
            by = cy - eye_h * 0.47
            c.line(self.color, (bx - eye_w * 0.6, by + h * 0.02), (bx + eye_w * 0.6, by - h * 0.03), 8)

        # mischief: left brow dips toward the middle, right brow arches up
        if self.state in ("mischief", "mischief_talk"):
            lx, rx = w * 0.34 + gx, w * 0.66 + gx
            by = cy - eye_h * 0.33
            c.line(self.color, (lx - eye_w * 0.55, by - h * 0.035), (lx + eye_w * 0.55, by + h * 0.015), 8)
            c.line(self.color, (rx - eye_w * 0.55, by - h * 0.02), (rx + eye_w * 0.55, by - h * 0.06), 8)

        self._mouth(c, cx=w / 2 + gx * 0.5, cy=h * 0.76 + bob)
        if love:
            self._hearts(c, now, mouth=(w / 2 + gx * 0.5, h * 0.76 + bob))
        if self.state in ACTUALLY_STATES:
            self._finger(c, now, bob)

        self._status(c, now)

        if self.state in ("sleepy", "resting"):
            for i, size in enumerate((20, 28, 36)):
                t = (now * 0.5 + i * 0.33) % 1.0
                x = w * 0.74 + i * w * 0.035 + t * w * 0.02
                y = h * 0.22 - i * h * 0.07 - t * h * 0.04
                c.text("z", (x, y), int(size * h / 480), _lerp_color(BACKGROUND, self.color, 1 - t))

    def _blush(self, c, cy, eye_w, eye_h, strong: bool):
        """Rosy cheeks just below and outside each eye."""
        w, h = self.w, self.h
        amount = 0.6 if strong else 0.3
        col = _lerp_color(BACKGROUND, BLUSH, amount)
        bw, bh = eye_w * 0.95, h * 0.07
        if strong:
            by = cy + eye_h * 0.36                              # under the closed ^ ^ eyes
        else:
            by = cy + eye_h * self.size * self.open * 0.5 + h * 0.06   # just below open eyes
        for cx in (w * 0.34 - eye_w * 0.55, w * 0.66 + eye_w * 0.55):
            c.ellipse(col, (cx - bw / 2, by - bh / 2, bw, bh))

    def _hearts(self, c, now, mouth):
        """Little hearts drift up and to the right from the kiss, then fade."""
        w, h = self.w, self.h
        t0 = self.love_since or now
        newest = int((now - t0) / HEART_EVERY)
        for i in range(max(0, newest - 4), newest + 1):
            age = now - t0 - i * HEART_EVERY
            if age < 0 or age > HEART_LIFE:
                continue
            k = age / HEART_LIFE
            sway = math.sin(age * 3.0 + i) * w * 0.012
            x = mouth[0] + w * 0.1 + k * w * 0.32 + sway + (i % 3) * w * 0.015
            y = mouth[1] - h * 0.03 - k * h * 0.42
            grow = min(1.0, age / 0.35)                      # pop in
            fade = 1.0 - max(0.0, (k - 0.6) / 0.4)           # fade out near the end
            size = w * (0.035 + 0.012 * (i % 2)) * grow
            c.polygon(_lerp_color(BACKGROUND, HEART, fade), heart_points(x, y, size))

    def _cosmos_back(self, c, now):
        """'Well, actually' backdrop: twinkling stars and a ringed planet passing behind her."""
        w, h = self.w, self.h
        # twinkling four-point stars
        for i, (sx, sy, r) in enumerate(((0.12, 0.2, 0.022), (0.88, 0.16, 0.018),
                                         (0.08, 0.66, 0.015), (0.9, 0.58, 0.02))):
            k = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(now * 2.2 + i * 1.7))
            col = _lerp_color(BACKGROUND, GOLD if i % 2 == 0 else TEAL, k)
            x, y, rr = sx * w, sy * h, r * h * (0.7 + 0.3 * k)
            c.polygon(col, [(x, y - 2.4 * rr), (x + rr * 0.5, y - rr * 0.5), (x + 2.4 * rr, y),
                            (x + rr * 0.5, y + rr * 0.5), (x, y + 2.4 * rr), (x - rr * 0.5, y + rr * 0.5),
                            (x - 2.4 * rr, y), (x - rr * 0.5, y - rr * 0.5)])
        # a ringed planet orbiting slowly around the face
        a = now * 0.6
        px, py = w * 0.5 + math.cos(a) * w * 0.4, h * 0.45 + math.sin(a) * h * 0.06
        pr = h * 0.045
        ring = (px - pr * 2.0, py - pr * 0.55, pr * 4.0, pr * 1.1)
        c.ellipse(GOLD, ring, width=max(3, int(h * 0.008)))
        c.ellipse(TEAL, (px - pr, py - pr, 2 * pr, 2 * pr))
        c.ellipse(_lerp_color(TEAL, (255, 255, 255), 0.5),
                  (px - pr * 0.55, py - pr * 0.6, pr * 0.5, pr * 0.5))

    def _cat_ears(self, c, now, bob):
        """Two pointed tuxedo-cat ears; the right one gives an occasional flick."""
        w, h = self.w, self.h
        flick = max(0.0, math.sin(now * 1.7)) ** 8          # a quick twitch now and then
        for k, (cx, lean) in enumerate(((w * 0.27, -1), (w * 0.73, 1))):
            tip_dx = lean * w * (0.012 + (0.02 * flick if k == 1 else 0))
            base_y = h * 0.2 + bob
            tip = (cx + tip_dx, h * 0.03 + bob + (h * 0.02 * flick if k == 1 else 0))
            outer = [(cx - w * 0.06, base_y + h * 0.01), tip, (cx + w * 0.06, base_y + h * 0.01)]
            c.polygon(TUX_WHITE, outer)
            inner = [(cx - w * 0.034, base_y),
                     (tip[0] * 0.85 + cx * 0.15, tip[1] + h * 0.055),
                     (cx + w * 0.034, base_y)]
            c.polygon(EAR_PINK, inner)

    def _whiskers(self, c, now, y):
        """Three whiskers on each side; they twitch a little."""
        w, h = self.w, self.h
        twitch = math.sin(now * 2.3) * h * 0.006
        for side in (-1, 1):
            x0 = w * 0.5 + side * w * 0.09
            for i, dy in enumerate((-0.03, 0.0, 0.03)):
                x1 = x0 + side * w * 0.19
                y0 = y + dy * h
                y1 = y0 + (dy * 1.6) * h + (twitch if i == 1 else 0)
                c.line(_lerp_color(BACKGROUND, TUX_WHITE, 0.8), (x0, y0), (x1, y1), 3)

    def _height_chart(self, c):
        """Height-chart lines on both sides, like a booking-photo wall."""
        w, h = self.w, self.h
        for i in range(13):
            y = h * 0.1 + i * h * 0.055
            long = i % 3 == 0
            for x0 in (w * 0.03, w * 0.97):
                d = w * (0.09 if long else 0.05)
                x1 = x0 + d if x0 < w / 2 else x0 - d
                c.line(CHART, (x0, y), (x1, y), 3 if long else 2)

    def _tiara(self, c, base_y, gx):
        """A small tiara knocked crooked, one point snapped off, with a crack."""
        w, h = self.w, self.h
        cx = w * 0.5 + gx + w * 0.02
        tilt = -0.18                       # slopes down to the left
        span = w * 0.12

        def p(dx, dy):                     # rotate around the tiara's center
            return (cx + dx * math.cos(tilt) - dy * math.sin(tilt),
                    base_y + dx * math.sin(tilt) + dy * math.cos(tilt))

        band = h * 0.02
        c.polygon(TIARA, [p(-span / 2, 0), p(span / 2, 0), p(span / 2, -band), p(-span / 2, -band)])
        peaks = [(-0.5, 0.045), (-0.25, 0.07), (0.0, 0.1), (0.25, 0.07), (0.5, 0.045)]
        for k, (fx, ph) in enumerate(peaks):
            hgt = ph * h * (0.45 if k == 3 else 1.0)       # one point snapped off short
            x = fx * span * 0.9
            c.polygon(TIARA, [p(x - w * 0.013, -band), p(x + w * 0.013, -band), p(x, -band - hgt)])
        # the jewel, and a crack running through the band beside it
        r = h * 0.017
        jx, jy = p(0, -band - h * 0.032)
        c.ellipse(BACKGROUND, (jx - r, jy - r, 2 * r, 2 * r))
        c.ellipse(_lerp_color(TIARA, (120, 200, 255), 0.55), (jx - r * 0.7, jy - r * 0.7, 1.4 * r, 1.4 * r))
        crack = [p(span * 0.12, 1), p(span * 0.16, -band * 0.5), p(span * 0.13, -band - h * 0.02),
                 p(span * 0.18, -band - h * 0.04)]
        for a, b in zip(crack, crack[1:]):
            c.line(BACKGROUND, a, b, 3)

    def _finger(self, c, now, bob):
        """One finger raised, bottom right: 'Well, actually...'"""
        w, h = self.w, self.h
        # one finger raised, bottom right: "Well, actually..."
        fx, fy = w * 0.79, h * 0.66 + bob
        fw = w * 0.032
        tap = max(0.0, math.sin(now * 3.0)) * h * 0.012      # a little emphatic bob
        c.rrect(GOLD, (fx - fw / 2, fy - h * 0.2 - tap, fw, h * 0.22), radius=fw / 2)   # index finger
        c.rrect(GOLD, (fx - fw * 0.6, fy - h * 0.02 - tap, fw * 2.6, h * 0.14), radius=fw * 0.7)  # fist
        knuckle = _lerp_color(GOLD, BACKGROUND, 0.35)
        for k in range(1, 3):
            y = fy + k * h * 0.04 - tap
            c.line(knuckle, (fx + fw * 0.6, y), (fx + fw * 1.8, y), max(2, int(h * 0.006)))

    def _status(self, c, now):
        """Status line + listening timer at the bottom, caption at the top."""
        w, h = self.w, self.h
        label, dots = STATUS.get(self.state, ("", False))
        if self.dream_mix >= 0.5:
            label = "Dreaming - tap to wake"
        elif self.ponder and self.state == "idle":
            label = self.ponder.status()
            dots = self.ponder.phase in ("wonder", "asking")
        elif self.doodle and self.state == "idle":
            label, dots = self.doodle.status(now), False
        elif self.mystery and self.state == "idle":
            label, dots = self.mystery.status(), self.mystery.phase == "vote" and bool(self.mystery.you)
        elif self.chess and self.state == "idle":
            label = self.chess.status(now)
            dots = label.endswith("thinking") or label.startswith("Thinking")
        elif self.game and self.state == "idle":
            g = self.game
            if g.human and not g.result:
                label = "Your turn - tap a square" if g.turn == "X" else "Chatty is thinking"
            else:
                label = "Playing tic-tac-toe - tap a square to join" if not g.human else "Good game!"
        if self.notices and self.state in QUIET_STATES:
            label, dots = "Tap to dismiss", False
        size = max(14, int(h * 0.055))
        if label:
            if dots:
                label += "." * (int(now * 2.5) % 4)
                width = c.measure(label.rstrip(".") + "...", size)  # keep it from jiggling
            else:
                width = c.measure(label, size)
            quiet = self.state in ("idle", "sleepy", "resting")
            color = (112, 122, 138) if quiet else self.color  # soft grey when nothing's happening
            c.text(label, ((w - width) / 2, h * 0.895), size, color)

        # listening timer: a bar that shrinks as time runs out
        if self.state == "listening" and self.listen_until:
            frac = max(0.0, min(1.0, (self.listen_until - now) / self.listen_total))
            bw, bh = w * 0.5, max(4, h * 0.012)
            x0, y0 = (w - bw) / 2, h * 0.965
            c.rrect(_lerp_color(BACKGROUND, self.color, 0.25), (x0, y0, bw, bh), radius=bh / 2)
            if frac > 0:
                c.rrect(self.color, (x0, y0, bw * frac, bh), radius=bh / 2)

        # recording indicator, top-left, only while awake
        if self.state not in QUIET_STATES and self.rec_mode != "off":
            size = max(14, int(h * 0.05))
            x, y = w * 0.025, h * 0.035
            if self.rec_mode == "full":
                pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(now * 4))
                r = size * 0.32
                c.ellipse(_lerp_color(BACKGROUND, REC_RED, pulse),
                          (x, y + size * 0.36 - r, 2 * r, 2 * r))
                c.text("REC", (x + 2 * r + size * 0.3, y), size, REC_RED)
            else:
                label = "PRIVATE" if self.rec_mode == "private" else "STATS ONLY"
                c.text(label, (x, y), size, (112, 122, 138))

        # the next timer or alarm, top-right
        ttext = self.timer_text(now)
        if ttext:
            tsize = max(14, int(h * 0.05))
            c.text(ttext, (w * 0.975 - c.measure(ttext, tsize), h * 0.035), tsize, TIMER_COLOR)

        # caption: the words Chatty heard (kept clear of the corner indicator)
        if self.caption:
            csize = max(14, int(h * 0.05))
            text = '"' + self.caption + '"'
            room = w * (0.50 if ttext else 0.70)    # leave the corners free
            while c.measure(text, csize) > room and len(text) > 8:
                text = '"...' + text[5:]  # keep the newest words visible
            c.text(text, ((w - c.measure(text, csize)) / 2, h * 0.035), csize, CAPTION_COLOR)

        # night-mode notices: the newest one, under the caption if there is one
        if self.notices:
            when, text = self.notices[-1]
            nsize = max(14, int(h * 0.048))
            stamp = time.strftime("%I:%M %p", time.localtime(when)).lstrip("0")
            lines = _wrap(c, f"{stamp}  {text}", nsize, w * 0.90, max_lines=2)
            y = h * (0.11 if self.caption or ttext else 0.035)
            for line in lines:
                c.text(line, ((w - c.measure(line, nsize)) / 2, y), nsize, NOTICE_COLOR)
                y += nsize * 1.25
            more = len(self.notices) - 1
            if more:
                hint = f"+{more} more"
                hsize = max(12, int(h * 0.036))
                c.text(hint, ((w - c.measure(hint, hsize)) / 2, y + nsize * 0.1), hsize, (112, 122, 138))

    def _mouth(self, c, cx, cy):
        w, h = self.w, self.h
        col = self.color
        shape = EXPRESSIONS[self.state]["mouth"]
        thick = max(4, int(h * 0.016))
        if shape == "talk":
            mw = w * (0.07 + 0.06 * self.level)
            mh = h * (0.025 + 0.17 * self.level)
            c.rrect(col, (cx - mw / 2, cy - mh / 2, mw, mh), radius=min(mw, mh) * 0.5)
        elif shape == "small_o":
            r = h * 0.035
            c.ellipse(col, (cx - r, cy - r, 2 * r, 2 * r), width=thick)
        elif shape == "flat":
            c.line(col, (cx - w * 0.045, cy), (cx + w * 0.045, cy), thick)
        elif shape == "tilt":
            c.line(col, (cx - w * 0.05, cy + h * 0.015), (cx + w * 0.05, cy - h * 0.02), thick)
        elif shape == "smirk":
            # flat on the left, curling up on the right
            p1 = (cx - w * 0.06, cy + h * 0.005)
            p2 = (cx + w * 0.025, cy + h * 0.012)
            p3 = (cx + w * 0.07, cy - h * 0.035)
            c.line(col, p1, p2, thick)
            c.line(col, p2, p3, thick)
        elif shape == "cat":
            # a small pink nose over a little "w" cat mouth
            n = h * 0.022
            c.polygon(EAR_PINK, [(cx - n, cy - h * 0.06), (cx + n, cy - h * 0.06), (cx, cy - h * 0.035)])
            r = w * 0.022
            for sx in (-1, 1):
                c.arc(col, (cx - r + sx * r, cy - r * 1.2, 2 * r, 2 * r), math.pi * 1.0, math.pi * 2.0, thick)
        elif shape == "deadpan":
            # a flat, pressed line, a touch down at one corner: unimpressed
            c.line(col, (cx - w * 0.06, cy), (cx + w * 0.05, cy), thick)
            c.line(col, (cx + w * 0.05, cy), (cx + w * 0.065, cy + h * 0.01), thick)
        elif shape == "knowing":
            # a closed, slightly lopsided "I know something you don't" smile
            c.arc(col, (cx - w * 0.05, cy - h * 0.085, w * 0.13, h * 0.1), math.pi * 1.12, math.pi * 1.97, thick)
        elif shape == "kiss":
            # puckered lips: a little sideways "3", leaning toward the hearts
            r = h * 0.04
            x0 = cx - r * 0.4
            for dy in (-r, r):
                c.arc(col, (x0 - r, cy + dy - r, 2 * r, 2 * r), -math.pi * 0.5, math.pi * 0.5, thick)
        elif shape == "grin":
            # a wide-open, delighted grin (a "D" on its back), with a little tongue
            rx, ry = w * 0.08, h * 0.09
            top = cy - h * 0.035
            pts = [(cx + rx * math.cos(a), top + ry * math.sin(a))
                   for a in [math.pi * i / 16 for i in range(17)]]
            c.polygon(col, pts)
            inner = [(cx + rx * 0.78 * math.cos(a), top + h * 0.012 + ry * 0.72 * math.sin(a))
                     for a in [math.pi * i / 16 for i in range(17)]]
            c.polygon(_lerp_color(BACKGROUND, col, 0.18), inner)
            tr = rx * 0.38
            c.ellipse(_lerp_color(BACKGROUND, (255, 120, 140), 0.85),
                      (cx - tr, top + ry * 0.72 - tr * 0.95, 2 * tr, tr * 1.3))
        elif shape == "small_smile":
            c.arc(col, (cx - w * 0.035, cy - h * 0.05, w * 0.07, h * 0.06), math.pi * 1.15, math.pi * 1.85, thick)
        else:  # smile
            c.arc(col, (cx - w * 0.07, cy - h * 0.1, w * 0.14, h * 0.12), math.pi * 1.1, math.pi * 1.9, thick)

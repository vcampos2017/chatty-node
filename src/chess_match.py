"""
Chess on Chatty's face: when she's bored she sometimes challenges another node
(Lightning, Rain, Greenhouse, the Word Clock) to a game and shows the board.

  - The node plays its own moves if it runs scripts/chess_peer.py (over MQTT, see
    chess_link.py). If it doesn't, or it's offline or slow, Chatty moves for it
    "in its style", so the game always goes on.
  - Each node has a personality: Lightning loves captures ("Zap!"), Rain is
    patient, Greenhouse grows her pawns, the Word Clock is punctual.
  - A tap hides the board without waking her; talking to her pauses it too.
    Next time she's bored (within half an hour) she picks the game up again.
  - "Hey Chatty, play chess" (or "play chess with the rain node") starts one;
    "what's the chess score?" tells you who's winning. Scores are kept in
    ~/.local/share/chatty/chess.json.
  - She's a kind player: she never gloats, and every game ends with a "good game".

Settings (in /etc/chatty/secrets.env):
  CHATTY_CHESS=0             no chess
  CHATTY_CHESS_SHARE=0.3     when bored, how often she picks chess
  CHATTY_CHESS_PACE=4        seconds per move (each side), so you can follow it
  CHATTY_CHESS_WAIT=25       seconds to wait for a node's move before moving for it
  CHATTY_CHESS_NODES=6000    how hard she thinks (positions per move)

Her thinking runs in a background thread so the face stays smooth; on a Pi 4 a
move takes well under a second.
"""
from __future__ import annotations

import json
import math
import os
import random
import threading
import time
from typing import Optional

try:
    import chess_engine as ce
    import quiet_hours
except ImportError:  # running from another folder
    from . import chess_engine as ce  # type: ignore
    from . import quiet_hours  # type: ignore

ENABLED = os.getenv("CHATTY_CHESS", "1") != "0"
SHARE = float(os.getenv("CHATTY_CHESS_SHARE", "0.3"))
PACE = float(os.getenv("CHATTY_CHESS_PACE", "4"))
PEER_WAIT = float(os.getenv("CHATTY_CHESS_WAIT", "25"))
RESUME_WITHIN = 1800       # a paused game is picked up again if she's bored within this
END_SECONDS = 9.0          # the result stays up this long
FPS = 10
SCORES = os.path.expanduser(os.getenv("CHATTY_CHESS_SCORES", "~/.local/share/chatty/chess.json"))
DEFAULT_OPPONENTS = ("lightning", "rain", "greenhouse", "wordclock")

BG = (8, 10, 14)
LIGHT_SQ = (70, 80, 106)
DARK_SQ = (40, 47, 66)
LAST_MOVE = (255, 204, 64)
CHECK_RED = (235, 90, 90)
WHITE_PIECE = (240, 233, 216)
WHITE_EDGE = (40, 40, 50)
BLACK_PIECE = (22, 24, 32)
BLACK_EDGE = (176, 186, 204)
TEXT = (210, 220, 228)
SOFT = (130, 140, 158)
FACE = (225, 240, 236)

# who's who: colors, icons and kind little lines for each node
PEOPLE = {
    "chatty": dict(title="Chatty", color=(130, 220, 200), icon="face",
                   capture=["Ooh, thank you!", "I'll take that, please.", "Got one!"],
                   check=["Check! ...sorry.", "Check! Your king says hi.", "Check!"],
                   lost=["Hey, I liked that one!", "Oops. Didn't see that.", "Fair enough."]),
    "lightning": dict(title="Lightning", color=(255, 214, 90), icon="bolt",
                      capture=["Zap!", "Zzzap!", "Crackle!"],
                      check=["Thunder check!", "Check! Count the seconds..."],
                      hello="Lightning is charged up and ready."),
    "rain": dict(title="Rain", color=(120, 180, 255), icon="drop",
                 capture=["Drip, drop.", "Splash!", "Washed away."],
                 check=["Pitter-patter, check.", "A little drizzle of check."],
                 hello="Rain takes her time. That's fine by me."),
    "greenhouse": dict(title="Greenhouse", color=(130, 210, 120), icon="leaf",
                       capture=["Into the compost!", "Pruned!", "Snip!"],
                       check=["Check! Fresh from the garden."],
                       grow=["Grow, little pawn!", "Sunshine for that pawn!"],
                       hello="Greenhouse brought her sunniest pawns."),
    "wordclock": dict(title="Word Clock", color=(200, 205, 220), icon="clock",
                      capture=["Right on time.", "Tick, tock, taken."],
                      check=["It is time. Check.", "Check, o'clock."],
                      hello="The Word Clock is never late to a game."),
}


def _key(node: str) -> str:
    return (node or "").lower().replace("-node", "").replace("_", "").replace("-", "").replace(" ", "")


def person(node: str) -> dict:
    p = PEOPLE.get(_key(node))
    if p:
        return p
    words = (node or "a node").replace("-node", "").replace("_", " ").replace("-", " ")
    return dict(title=words[:1].upper() + words[1:], color=(190, 170, 240), icon="dot",
                capture=["Got it!"], check=["Check!"])


def pick_opponent(link, rng: random.Random, wanted: Optional[str] = None) -> str:
    if wanted:
        return _key(wanted) or wanted
    found = [n for n in (link.opponents() if link else []) if n != "chatty"]
    with_player = [n for n in found if link.has_player(n)]
    if with_player:
        return rng.choice(with_player)
    return rng.choice(found or list(DEFAULT_OPPONENTS))


# ----- the scoreboard -----

def load_scores() -> dict:
    try:
        with open(SCORES) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record(opponent: str, outcome: str) -> None:
    """outcome from Chatty's side: 'win', 'loss' or 'draw'."""
    data = load_scores()
    row = data.setdefault(_key(opponent) or "node", {"win": 0, "loss": 0, "draw": 0})
    row[outcome] = int(row.get(outcome, 0)) + 1
    try:
        os.makedirs(os.path.dirname(SCORES), exist_ok=True)
        tmp = SCORES + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, SCORES)
    except OSError:
        pass


def _times(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def score_text() -> str:
    data = load_scores()
    if not data:
        return "I haven't played chess with the other nodes yet. Give me a few quiet minutes!"
    parts = []
    for node, row in sorted(data.items()):
        who = person(node)["title"]
        w, l, d = row.get("win", 0), row.get("loss", 0), row.get("draw", 0)
        bits = [_times(w, "win")] + ([_times(l, "loss").replace("losss", "losses")] if l else []) + \
               ([_times(d, "draw")] if d else [])
        parts.append(f"against {who}, " + ", ".join(bits))
    wins = sum(r.get("win", 0) for r in data.values())
    losses = sum(r.get("loss", 0) for r in data.values())
    tail = (" I'm ahead, but they're getting better." if wins > losses else
            " They're beating me! I'm learning though." if losses > wins else " We're neck and neck.")
    return "Chess so far: " + "; ".join(parts) + "." + tail


# ----- one game on the screen -----

class ChessMatch:
    def __init__(self, opponent: str, rng: random.Random, now: float, link=None,
                 threaded: bool = True):
        self.opponent = _key(opponent) or opponent
        self.who = person(self.opponent)
        self.me = PEOPLE["chatty"]
        self.rng = rng
        self.link = link
        self.threaded = threaded
        self.game = ce.Game()
        self.chatty_white = rng.random() < 0.5
        self.id = "%08x" % rng.getrandbits(32)
        self.done = False
        self.result = None            # (winner 'chatty'|opponent|'draw', why)
        self.ended_at = 0.0
        self.ghost = not (link and link.has_player(self.opponent))   # Chatty moves for the node
        self.mood = "happy"
        self.speaker = "chatty"       # whose line is showing
        self.message = self._hello()
        self.message_at = now
        self.last = None              # last move (from, to)
        self.moved_at = 0.0
        self.turn_started = now + 2.5   # a moment to say hello first
        self.asked = False
        self.asked_at = 0.0
        self.peer_move = None         # the node's answer, held until it's time to show it
        self._think_id = 0
        self._found = None            # (think id, move) from the background thread
        self._thinking = False
        self.dim = 0.6 if quiet_hours.is_night(now) else 1.0

    # ----- words -----
    def _hello(self) -> str:
        t = self.who["title"]
        side = "white" if self.chatty_white else "black"
        lines = [f"I think I'll challenge {t} to a game of chess. I'm {side}!",
                 f"Hey {t}, fancy a game? I'll be {side}.",
                 f"Chess time! Me against {t}. I'm playing {side}."]
        if self.ghost:
            lines = [f"{t} can't come to the board, so I'll play both sides. I'm {side}, {t} is the other!",
                     f"Chess with {t}! {t} is busy, so I'll move for it, in its style. I'm {side}."]
        line = self.rng.choice(lines)
        if self.who.get("hello") and self.rng.random() < 0.4:
            line = self.who["hello"]
        return line

    def _say(self, who: str, text: str, now: float):
        self.speaker, self.message, self.message_at = who, text, now

    # ----- life cycle -----
    def chatty_to_move(self) -> bool:
        return self.game.pos.white == self.chatty_white

    def resume(self, now: float):
        """Back after a pause: ask the node again (it may have forgotten) and carry on."""
        self.asked = False
        self.peer_move = None
        self.turn_started = now + 2.0
        self.mood = "happy"
        self._say("chatty", self.rng.choice([f"Where were we? Ah yes, my game with {self.who['title']}.",
                                             "Back to the board!", "Now, where was I..."]), now)
        self.dim = 0.6 if quiet_hours.is_night(now) else 1.0

    def _think(self, style: str):
        self._think_id += 1
        tid = self._think_id
        pos, seen = self.game.pos, dict(self.game.seen)
        rng = random.Random(self.rng.getrandbits(32))
        self._thinking = True

        def run():
            try:
                m = ce.best_move(pos, style, rng, seen)
            except Exception as e:   # never take the face down
                print("Chess: thinking failed:", repr(e), flush=True)
                m = None
            self._found = (tid, m)

        if self.threaded:
            threading.Thread(target=run, daemon=True, name="chess").start()
        else:
            run()

    def _take_found(self):
        f = self._found
        if f and f[0] == self._think_id:
            self._found = None
            self._thinking = False
            return f[1] or ce.legal_moves(self.game.pos)[0]
        return None

    def update(self, now: float):
        if self.result:
            if now - self.ended_at > END_SECONDS:
                self.done = True
            return
        if now < self.turn_started:
            return
        if self.chatty_to_move():
            self.mood = "thinking"
            if not self._thinking:
                self._think("chatty")
            if now - self.turn_started >= PACE:
                m = self._take_found()
                if m:
                    self._play(m, now)
            return
        # the node's turn
        if not self.ghost and not self.asked:
            if self.link and self.link.ask(self.opponent, self.id, list(self.game.moves)):
                self.asked, self.asked_at = True, now
            else:
                self._go_ghost(now)
        if not self.ghost:
            if self.peer_move is None:
                text = self.link.reply(self.opponent, self.id, len(self.game.moves))
                self.peer_move = ce.from_uci(self.game.pos, text) if text else None
            if self.peer_move and now - self.turn_started >= PACE * 0.5:
                self._play(self.peer_move, now)
            elif not self.peer_move and now - self.asked_at > PEER_WAIT:
                self._go_ghost(now)
            return
        if not self._thinking:
            self._think(self.opponent)
        if now - self.turn_started >= PACE:
            m = self._take_found()
            if m:
                self._play(m, now)

    def _go_ghost(self, now: float):
        if not self.ghost:
            t = self.who["title"]
            self._say("chatty", self.rng.choice([f"{t} seems to be napping. I'll move for it.",
                                                 f"{t} isn't answering, so I'll play its moves for it."]), now)
        self.ghost = True
        self.asked = False

    def _play(self, m, now: float):
        pos = self.game.pos
        mover = "chatty" if self.chatty_to_move() else self.opponent
        took = pos.board[m[1]] != "." or (pos.board[m[0]].upper() == "P" and m[1] == pos.ep and pos.ep)
        pawn_push = pos.board[m[0]].upper() == "P" and not took
        self.game.push(m)
        self.last = (m[0], m[1])
        self.moved_at = now
        self.turn_started = now
        self.asked = False
        self.peer_move = None
        winner, why = self.game.result()
        if winner:
            self._finish(winner, why, now)
            return
        p = self.me if mover == "chatty" else self.who
        check = ce.in_check(self.game.pos)
        if check:
            self._say(mover, self.rng.choice(p["check"]), now)
        elif took and self.rng.random() < 0.6:
            if mover != "chatty" and self.rng.random() < 0.35:
                self._say("chatty", self.rng.choice(self.me["lost"]), now)
            else:
                self._say(mover, self.rng.choice(p["capture"]), now)
        elif pawn_push and "grow" in p and self.rng.random() < 0.25:
            self._say(mover, self.rng.choice(p["grow"]), now)
        elif now - self.message_at > 12:
            self.message = ""
        self.mood = "happy" if mover == "chatty" else "thinking"

    def _finish(self, winner: str, why: str, now: float):
        t = self.who["title"]
        if winner == "draw":
            self.result = ("draw", why)
            self.mood = "puzzled"
            if why == "time for tea":
                line = self.rng.choice(["We've played for ages. Tea break: it's a draw!",
                                        "Tiny sat on the board. We'll call it a draw!"])
            else:
                line = self.rng.choice([f"A draw ({why})! Good game, {t}.",
                                        f"Draw by {why}. Shake hands, {t}?"])
            outcome = "draw"
        elif (winner == "white") == self.chatty_white:
            self.result = ("chatty", why)
            self.mood = "proud"
            line = self.rng.choice([f"Checkmate! Good game, {t}. You made me think!",
                                    f"Checkmate! Thanks for the game, {t}. Rematch soon?"])
            outcome = "win"
        else:
            self.result = (self.opponent, why)
            self.mood = "happy"
            line = self.rng.choice([f"Checkmate. You got me, {t}! Well played.",
                                    f"{t} wins! Good game. I'll get you next time... nicely."])
            outcome = "loss"
        self._say("chatty", line, now)
        self.ended_at = now
        record(self.opponent, outcome)
        if self.link and not self.ghost:
            self.link.result(self.opponent, self.id, outcome if outcome == "draw" else
                             ("chatty" if outcome == "win" else self.opponent), why)

    def status(self, now: float) -> str:
        t = self.who["title"]
        if self.result:
            return "Good game!"
        if now < self.turn_started or not self.game.moves and now - self.turn_started < 1:
            return f"Chess with {t} - tap to stop"
        if self.chatty_to_move():
            return "Chatty is thinking"
        return f"{t} is thinking" if not self.ghost else f"Thinking for {t}"

    # ----- drawing -----
    @staticmethod
    def board_box(w, h):
        size = int(h * 0.8 / 8) * 8
        return w * 0.05, h * 0.06, size     # x, y, size

    def _xy(self, i, x0, y0, cell):
        r, c = i // 10 - 2, i % 10 - 1
        if not self.chatty_white:            # Chatty's side is always at the bottom
            r, c = 7 - r, 7 - c
        return x0 + c * cell, y0 + r * cell

    def draw(self, c, w, h, now):
        k = self.dim
        mix = lambda col, a=1.0: tuple(int(b + (x - b) * k * a) for x, b in zip(col, BG))
        x0, y0, size = self.board_box(w, h)
        cell = size / 8
        pos = self.game.pos
        c.rrect(mix((30, 36, 50)), (x0 - cell * 0.12, y0 - cell * 0.12, size + cell * 0.24, size + cell * 0.24),
                radius=cell * 0.2)
        check_sq = ce.king_square(pos.board, pos.white) if ce.in_check(pos) else 0
        slide = min(1.0, (now - self.moved_at) / 0.45) if self.last else 1.0
        for i in range(21, 99):
            if pos.board[i] == " ":
                continue
            x, y = self._xy(i, x0, y0, cell)
            r, col = i // 10 - 2, i % 10 - 1
            sqc = LIGHT_SQ if (r + col) % 2 == 0 else DARK_SQ
            if self.last and i in self.last:
                sqc = tuple(int(a + (b - a) * 0.28) for a, b in zip(sqc, LAST_MOVE))
            if i == check_sq:
                sqc = tuple(int(a + (b - a) * 0.5) for a, b in zip(sqc, CHECK_RED))
            c.rrect(mix(sqc), (x, y, cell + 0.5, cell + 0.5), radius=0)
        for i in range(21, 99):
            p = pos.board[i]
            if not p.isalpha():
                continue
            x, y = self._xy(i, x0, y0, cell)
            if self.last and i == self.last[1] and slide < 1:
                fx, fy = self._xy(self.last[0], x0, y0, cell)
                e = 1 - (1 - slide) ** 3
                x, y = fx + (x - fx) * e, fy + (y - fy) * e
            draw_piece(c, p, x, y, cell, mix)
        self._draw_side(c, w, h, now, mix, x0 + size + cell * 0.5)

    def _draw_side(self, c, w, h, now, mix, left):
        right = w * 0.97
        mid = (left + right) / 2
        t = self.who["title"]
        # the two players, with a little "your turn" glow
        size_t = max(14, int(h * 0.05))
        ytop = h * 0.08
        for k, (who, p) in enumerate((("chatty", self.me), (self.opponent, self.who))):
            cx = left + (right - left) * (0.25 + 0.5 * k)
            to_move = not self.result and (self.chatty_to_move() == (who == "chatty"))
            r = h * 0.075
            if to_move:
                glow = 0.25 + 0.15 * math.sin(now * 3)
                c.ellipse(mix(p["color"], glow), (cx - r * 1.35, ytop + r - r * 1.35, r * 2.7, r * 2.7))
            if who == "chatty":
                self._mini_face(c, cx, ytop + r, r, now, mix)
            else:
                draw_icon(c, p["icon"], cx, ytop + r, r, mix(p["color"]))
            label = p["title"]
            c.text(label, (cx - c.measure(label, size_t) / 2, ytop + 2.3 * r), size_t, mix(p["color"]))
            white = self.chatty_white == (who == "chatty")
            dot = h * 0.018
            c.ellipse(mix(WHITE_PIECE if white else BLACK_EDGE),
                      (cx - c.measure(label, size_t) / 2 - dot * 2.6, ytop + 2.3 * r + size_t * 0.35, dot * 1.6, dot * 1.6),
                      width=0 if white else 2)
        vs = "vs"
        c.text(vs, (mid - c.measure(vs, size_t) / 2, ytop + h * 0.055), size_t, mix(SOFT))
        # what they're saying
        if self.message:
            p = self.me if self.speaker == "chatty" else self.who
            msize = max(14, int(h * 0.046))
            lines = _wrap(c, self.message, msize, right - left)
            y = h * 0.42
            for line in lines[:4]:
                c.text(line, (mid - c.measure(line, msize) / 2, y), msize, mix(p["color"] if self.speaker != "chatty" else TEXT))
                y += msize * 1.3
        # the last few moves, like a score sheet
        ssize = max(12, int(h * 0.04))
        sans = self.game.sans
        if sans:
            n = len(sans)
            start = max(0, (n - 1) // 2 * 2 - 2)
            rows = []
            for j in range(start, n, 2):
                rows.append(f"{j // 2 + 1}. {sans[j]}" + (f"  {sans[j + 1]}" if j + 1 < n else ""))
            y = h * 0.86 - len(rows) * ssize * 1.25
            for row in rows:
                c.text(row, (mid - c.measure(row, ssize) / 2, y), ssize, mix(SOFT))
                y += ssize * 1.25
        lead = self.game.material() * (1 if self.chatty_white else -1)
        if lead and not self.result:
            text = (f"Chatty +{lead}" if lead > 0 else f"{t} +{-lead}")
            c.text(text, (mid - c.measure(text, ssize) / 2, h * 0.865), ssize, mix(SOFT, 0.8))

    def _mini_face(self, c, cx, cy, r, now, mix):
        ew, eh = r * 0.32, r * 0.72
        mood = self.mood
        look = -r * 0.12 if mood == "thinking" else 0
        bob = math.sin(now * 2.2) * r * 0.05 if mood in ("happy", "proud") and self.result else 0
        for side in (-1, 1):
            ex = cx + side * r * 0.36 - r * 0.08
            open_ = 0.45 if mood == "puzzled" and side > 0 else (0.35 if mood == "proud" else 1.0)
            hh = max(eh * open_, r * 0.1)
            c.rrect(mix(FACE), (ex - ew / 2, cy - r * 0.15 + look + bob - hh / 2, ew, hh), radius=min(ew, hh) * 0.45)
        my = cy + r * 0.55 + bob
        if mood in ("happy", "proud"):
            c.arc(mix(FACE), (cx - r * 0.3, my - r * 0.35, r * 0.6, r * 0.4), math.pi * 1.1, math.pi * 1.9, 3)
        elif mood == "puzzled":
            c.line(mix(FACE), (cx - r * 0.2, my), (cx + r * 0.2, my - r * 0.1), 3)
        else:
            c.ellipse(mix(FACE), (cx - r * 0.1, my - r * 0.1, r * 0.2, r * 0.2), width=2)


def _wrap(c, text, size, width):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if c.measure(trial, size) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


# ----- pieces, drawn from simple shapes (no font needed) -----

def _outline(c, color, pts, width):
    pts = list(pts) + [pts[0]]
    fn = getattr(c, "polyline", None)
    if fn:
        fn(color, pts, width)
    else:
        for a, b in zip(pts, pts[1:]):
            c.line(color, a, b, width)


_SHAPES = {
    "P": [[(0.36, 0.56), (0.64, 0.56), (0.7, 0.78), (0.3, 0.78)]],
    "R": [[(0.27, 0.2), (0.36, 0.2), (0.36, 0.28), (0.45, 0.28), (0.45, 0.2), (0.55, 0.2), (0.55, 0.28),
           (0.64, 0.28), (0.64, 0.2), (0.73, 0.2), (0.73, 0.36), (0.65, 0.42), (0.66, 0.7), (0.34, 0.7),
           (0.35, 0.42), (0.27, 0.36)]],
    "N": [[(0.3, 0.78), (0.72, 0.78), (0.7, 0.58), (0.67, 0.4), (0.6, 0.26), (0.5, 0.2), (0.46, 0.13),
           (0.41, 0.22), (0.3, 0.33), (0.23, 0.48), (0.28, 0.54), (0.42, 0.47), (0.47, 0.52), (0.34, 0.66)]],
    "B": [[(0.5, 0.18), (0.62, 0.34), (0.62, 0.5), (0.56, 0.62), (0.44, 0.62), (0.38, 0.5), (0.38, 0.34)]],
    "Q": [[(0.24, 0.28), (0.36, 0.5), (0.4, 0.24), (0.5, 0.46), (0.6, 0.24), (0.64, 0.5), (0.76, 0.28),
           (0.68, 0.7), (0.32, 0.7)]],
    "K": [[(0.3, 0.38), (0.7, 0.38), (0.66, 0.7), (0.34, 0.7)],
          [(0.46, 0.12), (0.54, 0.12), (0.54, 0.2), (0.62, 0.2), (0.62, 0.27), (0.54, 0.27), (0.54, 0.38),
           (0.46, 0.38), (0.46, 0.27), (0.38, 0.27), (0.38, 0.2), (0.46, 0.2)]],
}
_BASE = [(0.24, 0.72), (0.76, 0.72), (0.78, 0.84), (0.22, 0.84)]


def draw_piece(c, p, x, y, cell, mix=lambda col: col):
    white = p.isupper()
    fill, edge = (WHITE_PIECE, WHITE_EDGE) if white else (BLACK_PIECE, BLACK_EDGE)
    fill, edge = mix(fill), mix(edge)
    k = p.upper()
    lw = max(1, int(cell * 0.045))
    big = cell * 1.2                      # the shapes leave a margin; use most of the square
    x, y, cell = x - (big - cell) * 0.5, y - (big - cell) * 0.56, big
    at = lambda pts: [(x + u * cell, y + v * cell) for u, v in pts]
    shapes = _SHAPES[k] + [_BASE]
    for s in shapes:
        pts = at(s)
        c.polygon(fill, pts)
        _outline(c, edge, pts, lw)
    if k == "P":
        r = cell * 0.13
        c.ellipse(fill, (x + cell * 0.5 - r, y + cell * 0.4 - r, 2 * r, 2 * r))
        c.ellipse(edge, (x + cell * 0.5 - r, y + cell * 0.4 - r, 2 * r, 2 * r), width=lw)
    elif k == "B":
        r = cell * 0.05
        c.ellipse(fill, (x + cell * 0.5 - r, y + cell * 0.12 - r, 2 * r, 2 * r))
        c.line(edge, (x + cell * 0.45, y + cell * 0.36), (x + cell * 0.55, y + cell * 0.46), lw)
    elif k == "N":
        r = cell * 0.035
        c.ellipse(edge, (x + cell * 0.5 - r, y + cell * 0.3 - r, 2 * r, 2 * r))
    elif k == "Q":
        r = cell * 0.04
        for u, v in ((0.24, 0.28), (0.4, 0.24), (0.6, 0.24), (0.76, 0.28)):
            c.ellipse(fill, (x + u * cell - r, y + v * cell - r, 2 * r, 2 * r))


def draw_icon(c, icon, cx, cy, r, color):
    """The other node's little badge."""
    if icon == "bolt":
        pts = [(0.15, -1), (-0.55, 0.15), (-0.05, 0.15), (-0.25, 1), (0.55, -0.2), (0.05, -0.2), (0.3, -1)]
        c.polygon(color, [(cx + u * r * 0.85, cy + v * r * 0.85) for u, v in pts])
    elif icon == "drop":
        c.ellipse(color, (cx - r * 0.55, cy - r * 0.15, r * 1.1, r * 1.05))
        c.polygon(color, [(cx, cy - r * 0.95), (cx - r * 0.5, cy + 0.1 * r), (cx + r * 0.5, cy + 0.1 * r)])
    elif icon == "leaf":
        pts = [(cx + r * 0.8 * math.cos(a), cy + r * 0.45 * math.sin(a)) for a in
               [i * math.pi / 10 for i in range(20)]]
        rot = [(cx + (px - cx) * 0.7 - (py - cy) * 0.7, cy + (px - cx) * 0.7 + (py - cy) * 0.7) for px, py in pts]
        c.polygon(color, rot)
        c.line(BG, (cx - r * 0.5, cy - r * 0.5), (cx + r * 0.5, cy + r * 0.5), max(2, int(r * 0.08)))
        c.line(color, (cx + r * 0.5, cy + r * 0.5), (cx + r * 0.85, cy + r * 0.85), max(2, int(r * 0.1)))
    elif icon == "clock":
        lw = max(2, int(r * 0.12))
        c.ellipse(color, (cx - r * 0.8, cy - r * 0.8, r * 1.6, r * 1.6), width=lw)
        tm = time.localtime()
        for frac, length in (((tm.tm_hour % 12 + tm.tm_min / 60) / 12, 0.4), (tm.tm_min / 60, 0.6)):
            a = frac * 2 * math.pi - math.pi / 2
            c.line(color, (cx, cy), (cx + math.cos(a) * r * length, cy + math.sin(a) * r * length), lw)
    elif icon == "spark":       # a little starburst (a letter-writer, like Claude)
        lw = max(2, int(r * 0.16))
        for k in range(6):
            a = k * math.pi / 6
            dx, dy = math.cos(a) * r * 0.8, math.sin(a) * r * 0.8
            c.line(color, (cx - dx, cy - dy), (cx + dx, cy + dy), lw)
    elif icon == "ring":
        c.ellipse(color, (cx - r * 0.7, cy - r * 0.7, r * 1.4, r * 1.4), width=max(2, int(r * 0.18)))
        c.ellipse(color, (cx - r * 0.2, cy - r * 0.2, r * 0.4, r * 0.4))
    else:
        c.ellipse(color, (cx - r * 0.6, cy - r * 0.6, r * 1.2, r * 1.2))

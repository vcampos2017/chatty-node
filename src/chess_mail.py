"""
Chess by letter: Claude (or anyone else with a message door key) plays a slow,
correspondence-style game against Chatty through her message door (door.py).

Why by letter: Claude only "wakes up" when Vincent opens a chat, so a game can
take hours or days. Each move is one signed door message; Chatty checks it
against the rules, answers with her own move straight away, keeps the game on
disk, and shows both moves on her face. Nothing else changes hands.

    chess new            start a game (Chatty picks colors)
    chess new white      start, and I'm white (or "black")
    chess e2e4           a move: UCI (e2e4, e7e8q) or SAN (e4, Nf3, O-O, exd5)
    chess board          where are we? (FEN + the last few moves)
    chess draw           offer a draw (she takes it if she isn't ahead)
    chess resign         give up the game, gracefully
    chess score          everyone's record against her
    chess help           this list

Her reply always says her move (SAN and UCI), whose turn it is, and the FEN, so
the other player never has to remember the board.

Room for a tournament: every door sender gets their own game and their own row
in the scoreboard (chess_match.record), so giving ChatGPT a key
(`sudo python3 scripts/door_send.py --add-sender chatgpt`) is all it takes for
Claude, ChatGPT and the nodes to have a three-way standings table. "What's the
chess score?" reads it out.

Safety: a chess message is only ever read as a move or one of the words above.
Nothing the sender wrote is shown or spoken, only the move it names, after the
rules engine has checked it. Games live in ~/.local/share/chatty/chess_mail.json.

Settings (in /etc/chatty/secrets.env):
    CHATTY_CHESS_MAIL=0      no chess by letter (the door answers as usual)
    CHATTY_CHESS_MAIL_FILE   where the games are kept
    CHATTY_CHESS_MAIL_SHOW   seconds the board stays on her face after a move (45)
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Dict, List, Optional, Tuple

try:
    import chess_engine as ce
    import chess_match
except ImportError:  # running from another folder
    from . import chess_engine as ce  # type: ignore
    from . import chess_match  # type: ignore

ENABLED = os.getenv("CHATTY_CHESS_MAIL", "1") != "0"
FILE = os.path.expanduser(os.getenv("CHATTY_CHESS_MAIL_FILE", "~/.local/share/chatty/chess_mail.json"))
SHOW = float(os.getenv("CHATTY_CHESS_MAIL_SHOW", "45"))
CHESS_RE = re.compile(r"^\s*chess\b", re.I)
MAX_REPLY = 250            # the door allows 280; a little room to spare

# how each letter-writer looks on her face (anyone else gets a friendly default)
chess_match.PEOPLE.setdefault("claude", dict(
    title="Claude", color=(222, 140, 104), icon="spark",
    capture=["A thoughtful capture.", "I'll take that, kindly.", "Hmm, yes. That one."],
    check=["Check, I believe.", "Check! Politely."],
    hello="A letter from Claude: it's a chess move!"))
chess_match.PEOPLE.setdefault("chatgpt", dict(
    title="ChatGPT", color=(110, 200, 170), icon="ring",
    capture=["Captured!", "That piece is mine now."],
    check=["Check!", "Check, as computed."],
    hello="ChatGPT sent a chess move by letter."))


def is_chess(text: str) -> bool:
    return ENABLED and bool(CHESS_RE.match(text or ""))


# ----- the games on disk (the face reads the same file) -----

def load(path: str = None) -> Dict[str, dict]:
    try:
        with open(path or FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: Dict[str, dict], path: str = None) -> None:
    path = path or FILE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError as e:
        print("Chess by letter: couldn't save:", repr(e), flush=True)


def fen(pos: "ce.Position") -> str:
    rows = []
    for r in range(8):
        row, empty = "", 0
        for c in range(8):
            p = pos.board[21 + 10 * r + c]
            if p == ".":
                empty += 1
                continue
            if empty:
                row, empty = row + str(empty), 0
            row += p
        rows.append(row + (str(empty) if empty else ""))
    ep = ce.name(pos.ep) if pos.ep else "-"
    return f"{'/'.join(rows)} {'w' if pos.white else 'b'} {pos.castle or '-'} {ep} {pos.half} {pos.full}"


def parse_move(pos: "ce.Position", text: str) -> Optional["ce.Move"]:
    """UCI ('e2e4', 'e7e8q') or SAN ('e4', 'Nf3', 'O-O', 'exd5', 'e8=Q+')."""
    t = (text or "").strip().rstrip("!?").strip()
    m = ce.from_uci(pos, t)
    if m:
        return m
    norm = lambda s: s.replace("+", "").replace("#", "").replace("0", "O").replace("=", "").lower()
    want = norm(t)
    if not want:
        return None
    for mv in ce.legal_moves(pos):
        if norm(ce.san(pos, mv)) == want:
            return mv
    return None


def _turn_words(g: "ce.Game") -> str:
    return f"move {g.pos.full}, {'white' if g.pos.white else 'black'} to play"


def _last_moves(g: "ce.Game", n: int = 6) -> str:
    sans = g.sans
    start = max(0, len(sans) - n)
    start -= start % 2
    out = []
    for j in range(start, len(sans), 2):
        out.append(f"{j // 2 + 1}. {sans[j]}" + (f" {sans[j + 1]}" if j + 1 < len(sans) else ""))
    return " ".join(out)


def _fit(text: str) -> str:
    return text if len(text) <= MAX_REPLY else text[:MAX_REPLY - 1] + "…"


HELP = ("Chess by letter! Send: 'chess new' (or 'chess new white'/'black'), then a move like "
        "'chess e2e4' or 'chess Nf3'. Also: 'chess board', 'chess draw', 'chess resign', 'chess score'.")


class Result:
    """What the voice node should do after a chess letter."""

    def __init__(self, reply: str, show: int = 0, event: str = "", line: str = ""):
        self.reply = reply      # the signed answer to the sender
        self.show = show        # plies to replay on her face (0: don't show the board)
        self.event = event      # '' | 'new' | 'end'
        self.line = line        # something she may say out loud (daytime, while free)


class Correspondence:
    """All games by letter. Pure logic (no network); the voice node feeds it door messages."""

    def __init__(self, path: str = None, rng: Optional[random.Random] = None, clock=time.time):
        self.path = path or FILE
        self.rng = rng or random.Random()
        self.clock = clock

    def handle(self, sender: str, text: str) -> Result:
        words = CHESS_RE.sub("", text or "", count=1).strip()
        cmd = words.lower()
        data = load(self.path)
        row = data.get(sender)
        who = chess_match.person(sender)["title"]
        if cmd in ("", "help", "?", "how"):
            return Result(HELP)
        if cmd in ("score", "scores", "standings"):
            return Result(_fit(chess_match.score_text()))
        if cmd.startswith("new") or cmd in ("start", "play", "let's play", "lets play"):
            if row and not row.get("over"):
                g = ce.Game(row["moves"])
                return Result(_fit(f"We're still playing ({_turn_words(g)}). Send 'chess board' to see it, "
                                   "or 'chess resign' to start over."))
            side = "white" if "white" in cmd else "black" if "black" in cmd else ""
            chatty_white = (side == "black") if side else self.rng.random() < 0.5
            row = {"game": "%08x" % self.rng.getrandbits(32), "moves": [], "chatty_white": chatty_white,
                   "started": int(self.clock()), "updated": int(self.clock()), "over": ""}
            data[sender] = row
            g = ce.Game()
            hello = f"A new game! You're {'black' if chatty_white else 'white'}."
            if chatty_white:
                mine = self._my_move(g)
                row["moves"] = list(g.moves)
                save(data, self.path)
                return Result(_fit(f"{hello} I open with {mine}. Your move. FEN {fen(g.pos)}"),
                              show=1, event="new",
                              line=f"{who} challenged me to a game of chess by letter! I'm white.")
            save(data, self.path)
            return Result(_fit(f"{hello} Your move: send it like 'chess e2e4'. FEN {fen(g.pos)}"),
                          show=0, event="new",
                          line=f"{who} challenged me to a game of chess by letter! {who} goes first.")
        if not row:
            return Result("We don't have a game going yet. Send 'chess new' to start one!")
        g = ce.Game(row["moves"])
        if cmd in ("board", "status", "position", "where are we", "fen"):
            state = f"Game over ({row['over']})." if row.get("over") else (
                "Your move." if self._their_turn(row, g) else "My move, one moment.")
            return Result(_fit(f"{state} You're {'black' if row['chatty_white'] else 'white'}, "
                               f"{_turn_words(g)}. Last: {_last_moves(g) or 'none yet'}. FEN {fen(g.pos)}"),
                          show=0 if not g.moves else min(2, len(g.moves)))
        if row.get("over"):
            return Result(f"That game is over ({row['over']}). Send 'chess new' for a rematch!")
        if cmd in ("resign", "i resign", "give up"):
            return self._end(data, sender, row, g, "win", f"{who} resigned",
                             f"Thank you for the game, {who}! That was fun. Rematch anytime: 'chess new'.",
                             f"{who} resigned our chess game. Good game, {who}!")
        if cmd in ("draw", "offer draw", "draw?"):
            lead = g.material() * (1 if row["chatty_white"] else -1)
            if lead <= 1:
                return self._end(data, sender, row, g, "draw", "agreed draw",
                                 f"A draw it is. Shake hands, {who}? Good game!",
                                 f"{who} and I agreed to a draw. Good game!")
            return Result(f"That's kind, but I think I'll play on. Your move! FEN {fen(g.pos)}")
        if not self._their_turn(row, g):
            mine = self._my_move(g)        # she owes a move (e.g. after a restart): make it now
            row["moves"] = list(g.moves)
            row["updated"] = int(self.clock())
            save(data, self.path)
            return Result(_fit(f"Oops, it was my turn. I play {mine}. Your move. FEN {fen(g.pos)}"), show=1)
        m = parse_move(g.pos, words)
        if m is None:
            n = len(ce.legal_moves(g.pos))
            return Result(_fit(f"Hmm, '{_safe(words)}' isn't a legal move here. You have {n} legal moves, "
                               f"e.g. {self._examples(g)}. FEN {fen(g.pos)}"))
        theirs = ce.san(g.pos, m)
        g.push(m)
        row["moves"] = list(g.moves)
        row["updated"] = int(self.clock())
        winner, why = g.result()
        if winner:
            return self._game_over(data, sender, row, g, winner, why, f"You played {theirs}.", show=1)
        mine = self._my_move(g)
        row["moves"] = list(g.moves)
        winner, why = g.result()
        if winner:
            return self._game_over(data, sender, row, g, winner, why,
                                   f"You played {theirs}, I answer {mine}.", show=2)
        save(data, self.path)
        extra = ""
        if ce.in_check(g.pos):
            extra = " Check!"
        return Result(_fit(f"You played {theirs}. I answer {mine}.{extra} Your move ({_turn_words(g)}). "
                           f"FEN {fen(g.pos)}"), show=2)

    # ----- helpers -----
    @staticmethod
    def _their_turn(row: dict, g: "ce.Game") -> bool:
        return g.pos.white != row["chatty_white"]

    def _my_move(self, g: "ce.Game") -> str:
        m = ce.best_move(g.pos, "chatty", random.Random(self.rng.getrandbits(32)), g.seen)
        m = m or ce.legal_moves(g.pos)[0]
        text = f"{ce.san(g.pos, m)} ({ce.to_uci(m)})"
        g.push(m)
        return text

    def _examples(self, g: "ce.Game") -> str:
        moves = ce.legal_moves(g.pos)
        pick = self.rng.sample(moves, min(3, len(moves)))
        return ", ".join(f"{ce.san(g.pos, m)} ({ce.to_uci(m)})" for m in pick)

    def _game_over(self, data, sender, row, g, winner, why, said, show) -> Result:
        who = chess_match.person(sender)["title"]
        if winner == "draw":
            return self._end(data, sender, row, g, "draw", why,
                             f"{said} That's a draw ({why}). Good game, {who}!",
                             f"My chess game with {who} ended in a draw. Good game!", show)
        chatty_won = (winner == "white") == row["chatty_white"]
        if chatty_won:
            return self._end(data, sender, row, g, "win", why,
                             f"{said} Checkmate! Thank you for a lovely game, {who}. Rematch?",
                             f"Checkmate! I won my chess game with {who}. Good game, {who}!", show)
        return self._end(data, sender, row, g, "loss", why,
                         f"{said} Checkmate. You got me, {who}! Well played. Rematch?",
                         f"{who} beat me at chess! Well played, {who}.", show)

    def _end(self, data, sender, row, g, outcome, why, reply, line, show=0) -> Result:
        row["over"] = why
        row["outcome"] = outcome
        row["moves"] = list(g.moves)
        row["updated"] = int(self.clock())
        save(data, self.path)
        chess_match.record(sender, outcome)
        return Result(_fit(reply), show=show, event="end", line=line)

    # ----- for her voice: "how's your game with Claude?" -----
    def status_text(self, sender: Optional[str] = None) -> str:
        data = load(self.path)
        if sender:
            data = {k: v for k, v in data.items() if k == sender}
        live = {k: v for k, v in data.items() if not v.get("over")}
        if not live:
            if sender:
                who = chess_match.person(sender)["title"]
                return (f"I don't have a game going with {who} right now. "
                        f"{who} can start one by sending me 'chess new' through my message door.")
            return "No chess games by letter right now. Anyone with a door key can send me 'chess new'."
        parts = []
        for name, row in sorted(live.items()):
            who = chess_match.person(name)["title"]
            try:
                g = ce.Game(row["moves"])
            except ValueError:
                continue
            lead = g.material() * (1 if row["chatty_white"] else -1)
            turn = f"it's {who}'s turn" if self._their_turn(row, g) else "it's my turn"
            ahead = (f", and I'm up {lead}" if lead > 0 else f", and {who} is up {-lead}" if lead < 0 else
                     ", and it's even")
            parts.append(f"against {who} I'm {'white' if row['chatty_white'] else 'black'}, "
                         f"we're on move {g.pos.full}, {turn}{ahead}")
        return ("Chess by letter: " + "; ".join(parts) + ".") if parts else "No chess games by letter right now."


def _safe(words: str) -> str:
    """Echo a bad move back only if it looks like chess notation (never free text)."""
    w = (words or "").strip()[:8]
    return w if re.fullmatch(r"[a-hKQRBNOx0-8=+#\-]{1,8}", w) else "that"


# ----- on her face: replay the latest move(s) of a game by letter -----

class MailMatch(chess_match.ChessMatch):
    """A ChessMatch that only shows a game by letter: no thinking, no network,
    no scores (the voice node keeps those). It replays the last `show` plies,
    then stays up for CHATTY_CHESS_MAIL_SHOW seconds."""

    mail = True

    def __init__(self, sender: str, row: dict, show: int, rng: random.Random, now: float):
        super().__init__(sender, rng, now, link=None, threaded=False)
        moves = list(row.get("moves") or [])
        show = max(0, min(int(show), len(moves)))
        self.game = ce.Game(moves[:len(moves) - show])
        self.todo: List[str] = moves[len(moves) - show:]
        self.chatty_white = bool(row.get("chatty_white"))
        self.ghost = False
        self.over = row.get("over") or ""
        self.outcome = row.get("outcome") or ""
        t = self.who["title"]
        self.message = (self.who.get("hello") if self.todo and self.rng.random() < 0.5 else
                        f"My game by letter with {t}." if not self.over else f"My game with {t} ({self.over}).")
        self.speaker = "chatty"
        self.turn_started = now + 1.5
        self.until = now + SHOW
        if not self.todo:
            self._settle(now)

    def resume(self, now: float):
        self.until = max(self.until, now + SHOW / 2)

    def update(self, now: float):
        if self.done:
            return
        if self.todo and now >= self.turn_started:
            m = self.todo.pop(0)
            self._play(ce.from_uci(self.game.pos, m), now)
            self.turn_started = now + chess_match.PACE
            self.until = max(self.until, now + SHOW)
            if not self.todo:
                self._settle(now)
        if now > self.until and not self.todo:
            self.done = True

    def _settle(self, now: float):
        t = self.who["title"]
        if self.over:
            self.result = (("chatty" if self.outcome == "win" else "draw" if self.outcome == "draw"
                            else self.opponent), self.over)
            if self.over.endswith("resigned"):
                self._say("chatty", f"{t} resigned. Good game, {t}!", now)
        elif self.chatty_to_move():
            self.mood = "thinking"
        else:
            self.mood = "happy"
            if not self.message or self.rng.random() < 0.5:
                self._say("chatty", self.rng.choice([f"Your move, {t}. I'll wait for your letter!",
                                                     f"Over to you, {t}. Take your time."]), now)

    def _finish(self, winner: str, why: str, now: float):
        t = self.who["title"]
        if winner == "draw":
            self.result, self.mood = ("draw", why), "puzzled"
            self._say("chatty", f"A draw ({why})! Good game, {t}.", now)
        elif (winner == "white") == self.chatty_white:
            self.result, self.mood = ("chatty", why), "proud"
            self._say("chatty", f"Checkmate! Good game, {t}. Rematch?", now)
        else:
            self.result, self.mood = (self.opponent, why), "happy"
            self._say("chatty", f"Checkmate. You got me, {t}! Well played.", now)
        self.ended_at = now

    def status(self, now: float) -> str:
        t = self.who["title"]
        if self.result:
            return "Good game!"
        if self.todo:
            return f"A chess letter from {t}"
        return f"Waiting for {t}'s letter" if not self.chatty_to_move() else "Chatty is thinking"


def show_on_face(face, sender: str, show: int, now: float = None) -> bool:
    """Called in the face process for a 'chessmail:<sender>:<plies>' message."""
    now = now or time.time()
    row = load().get(sender)
    if not row:
        return False
    try:
        return face.start_mail_chess(MailMatch(sender, row, show, face.rng, now), now)
    except ValueError:      # a broken game file: never take the face down
        return False

"""
A tiny chess player for Chatty and the other nodes. Standard library only, one
file, so it can be copied onto any node (even a Pi Zero) next to chess_peer.py.

  - Full rules: castling, en passant, promotion, check, checkmate, stalemate,
    the 50-move rule, threefold repetition and "not enough pieces to mate".
  - A small alpha-beta search with a hard budget (CHATTY_CHESS_NODES positions per
    move), so it never hogs a weak CPU: it looks two moves ahead and checks
    the captures that follow, then picks a move. It plays like a keen beginner.
  - Styles give each node its own personality:
        chatty      balanced, likes her knights and bishops out early
        lightning   loves captures and checks (zap!)
        rain        patient, quiet moves, a little dreamy
        greenhouse  grows her pawns
        wordclock   punctual: castles on time, keeps things tidy

Moves are UCI strings ("e2e4", "e7e8q"), the same over MQTT as on the board.
"""
from __future__ import annotations

import os
import random
from typing import Dict, List, Optional, Tuple

NODE_BUDGET = int(os.getenv("CHATTY_CHESS_NODES", "6000"))

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FILES = "abcdefgh"

N, S, E, W = -10, 10, 1, -1
KNIGHT = (-21, -19, -12, -8, 8, 12, 19, 21)
DIAG = (-11, -9, 9, 11)
ORTHO = (-10, 10, -1, 1)
ALL8 = DIAG + ORTHO
VALUE = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
MATE = 100000

Move = Tuple[int, int, str]     # (from, to, promotion piece or "")


def sq(name: str) -> int:
    """'e2' -> mailbox index."""
    return 21 + FILES.index(name[0]) + 10 * (8 - int(name[1]))


def name(i: int) -> str:
    return FILES[i % 10 - 1] + str(10 - i // 10)


def _row(i: int) -> int:
    """0 for the 8th rank ... 7 for the 1st."""
    return i // 10 - 2


def _col(i: int) -> int:
    return i % 10 - 1


class Position:
    __slots__ = ("board", "white", "castle", "ep", "half", "full")

    def __init__(self, board, white, castle, ep, half, full):
        self.board = board      # 120 cells: '.' empty, ' ' off the board, 'P'..'k' pieces
        self.white = white      # True: white to move
        self.castle = castle    # subset of "KQkq"
        self.ep = ep            # en passant target square, or 0
        self.half = half        # moves since a capture or pawn move
        self.full = full

    @classmethod
    def from_fen(cls, fen: str = START) -> "Position":
        parts = fen.split()
        board = [" "] * 120
        for r, row in enumerate(parts[0].split("/")):
            c = 0
            for ch in row:
                if ch.isdigit():
                    for _ in range(int(ch)):
                        board[21 + 10 * r + c] = "."
                        c += 1
                else:
                    board[21 + 10 * r + c] = ch
                    c += 1
        castle = "" if parts[2] == "-" else parts[2]
        ep = 0 if parts[3] == "-" else sq(parts[3])
        return cls(board, parts[1] == "w", castle, ep, int(parts[4]), int(parts[5]))

    def key(self) -> str:
        """Same key = same position (for repetition)."""
        return "".join(self.board[21:99]) + ("w" if self.white else "b") + self.castle + str(self.ep)

    def piece_at(self, square: str) -> str:
        p = self.board[sq(square)]
        return "" if p == "." else p


def _mine(p: str, white: bool) -> bool:
    return p.isalpha() and p.isupper() == white


def _theirs(p: str, white: bool) -> bool:
    return p.isalpha() and p.isupper() != white


def attacked(board, i: int, by_white: bool) -> bool:
    """Is square i attacked by the given side?"""
    if by_white:
        if board[i + 9] == "P" or board[i + 11] == "P":
            return True
        n, b, r, q, k = "NBRQK"
    else:
        if board[i - 9] == "p" or board[i - 11] == "p":
            return True
        n, b, r, q, k = "nbrqk"
    for d in KNIGHT:
        if board[i + d] == n:
            return True
    for d in ALL8:
        if board[i + d] == k:
            return True
    for dirs, slider in ((DIAG, b), (ORTHO, r)):
        for d in dirs:
            j = i + d
            while board[j] == ".":
                j += d
            if board[j] == slider or board[j] == q:
                return True
    return False


def king_square(board, white: bool) -> int:
    k = "K" if white else "k"
    for i in range(21, 99):
        if board[i] == k:
            return i
    return 0


def in_check(pos: Position, white: Optional[bool] = None) -> bool:
    white = pos.white if white is None else white
    k = king_square(pos.board, white)
    return bool(k) and attacked(pos.board, k, not white)


def pseudo_moves(pos: Position, captures_only: bool = False) -> List[Move]:
    b, white = pos.board, pos.white
    out: List[Move] = []
    fwd = N if white else S
    start_row, last_row = (6, 0) if white else (1, 7)
    for i in range(21, 99):
        p = b[i]
        if not _mine(p, white):
            continue
        kind = p.upper()
        if kind == "P":
            j = i + fwd
            if not captures_only and b[j] == ".":
                if _row(j) == last_row:
                    out.extend((i, j, pr) for pr in "QNRB")
                else:
                    out.append((i, j, ""))
                    if _row(i) == start_row and b[j + fwd] == ".":
                        out.append((i, j + fwd, ""))
            for j in (i + fwd - 1, i + fwd + 1):
                if _theirs(b[j], white) or (j == pos.ep and pos.ep):
                    if _row(j) == last_row:
                        out.extend((i, j, pr) for pr in "QNRB")
                    else:
                        out.append((i, j, ""))
        elif kind in "NK":
            for d in (KNIGHT if kind == "N" else ALL8):
                j = i + d
                t = b[j]
                if t == "." and not captures_only or _theirs(t, white):
                    out.append((i, j, ""))
        else:
            dirs = DIAG if kind == "B" else ORTHO if kind == "R" else ALL8
            for d in dirs:
                j = i + d
                while b[j] == ".":
                    if not captures_only:
                        out.append((i, j, ""))
                    j += d
                if _theirs(b[j], white):
                    out.append((i, j, ""))
    if not captures_only:
        _castles(pos, out)
    return out


def _castles(pos: Position, out: List[Move]):
    b, white = pos.board, pos.white
    home = 95 if white else 25
    if b[home] != ("K" if white else "k"):
        return
    rights = ("K", "Q") if white else ("k", "q")
    rook = "R" if white else "r"
    them = not white
    if rights[0] in pos.castle and b[home + 3] == rook and b[home + 1] == b[home + 2] == ".":
        if not any(attacked(b, s, them) for s in (home, home + 1, home + 2)):
            out.append((home, home + 2, ""))
    if rights[1] in pos.castle and b[home - 4] == rook and b[home - 1] == b[home - 2] == b[home - 3] == ".":
        if not any(attacked(b, s, them) for s in (home, home - 1, home - 2)):
            out.append((home, home - 2, ""))


_CORNER_RIGHTS = {98: "K", 91: "Q", 28: "k", 21: "q"}


def make(pos: Position, m: Move) -> Position:
    """The position after move m (pos itself is not changed)."""
    f, t, promo = m
    b = pos.board[:]
    p = b[f]
    kind = p.upper()
    captured = b[t]
    b[t], b[f] = p, "."
    ep = 0
    if kind == "P":
        fwd = N if pos.white else S
        if t == pos.ep and pos.ep and captured == ".":
            b[t - fwd] = "."             # en passant
            captured = "p"
        if t - f == 2 * fwd:
            ep = f + fwd
        if promo:
            b[t] = promo if pos.white else promo.lower()
    elif kind == "K" and abs(t - f) == 2:
        if t > f:                         # king side
            b[f + 1], b[f + 3] = b[f + 3], "."
        else:
            b[f - 1], b[f - 4] = b[f - 4], "."
    castle = pos.castle
    if castle:
        if kind == "K":
            castle = castle.replace("K" if pos.white else "k", "").replace("Q" if pos.white else "q", "")
        for s in (f, t):
            r = _CORNER_RIGHTS.get(s)
            if r:
                castle = castle.replace(r, "")
    half = 0 if kind == "P" or captured != "." else pos.half + 1
    return Position(b, not pos.white, castle, ep, half, pos.full + (0 if pos.white else 1))


def legal_moves(pos: Position) -> List[Move]:
    out = []
    for m in pseudo_moves(pos):
        nxt = make(pos, m)
        if not in_check(nxt, pos.white):
            out.append(m)
    return out


def to_uci(m: Move) -> str:
    return name(m[0]) + name(m[1]) + m[2].lower()


def from_uci(pos: Position, text: str) -> Optional[Move]:
    """A legal move from its UCI text, or None (anything odd from the network is refused)."""
    text = (text or "").strip().lower()
    if not (4 <= len(text) <= 5):
        return None
    for m in legal_moves(pos):
        if to_uci(m) == text or (len(text) == 4 and m[2] == "Q" and to_uci(m)[:4] == text):
            return m
    return None


def san(pos: Position, m: Move) -> str:
    """Short algebraic notation for the screen: 'Nf3', 'exd5', 'O-O', 'e8=Q+'."""
    f, t, promo = m
    p = pos.board[f].upper()
    capture = pos.board[t] != "." or (p == "P" and t == pos.ep and pos.ep)
    if p == "K" and abs(t - f) == 2:
        text = "O-O" if t > f else "O-O-O"
    elif p == "P":
        text = (name(f)[0] + "x" if capture else "") + name(t) + ("=" + promo if promo else "")
    else:
        text = p
        twins = [o for o in legal_moves(pos) if o[1] == t and o[0] != f and pos.board[o[0]] == pos.board[f]]
        if twins:
            text += name(f)[0] if all(_col(o[0]) != _col(f) for o in twins) else name(f)
        text += ("x" if capture else "") + name(t)
    nxt = make(pos, m)
    if in_check(nxt):
        text += "#" if not legal_moves(nxt) else "+"
    return text


def insufficient(pos: Position) -> bool:
    minors = 0
    for i in range(21, 99):
        p = pos.board[i].upper()
        if p in "PRQ":
            return False
        if p in "NB":
            minors += 1
    return minors <= 1


# ----- thinking -----

STYLES: Dict[str, dict] = {
    #            develop  pawns  center  aggression  castle  noise
    "chatty":     dict(develop=14, pawns=4, center=10, aggro=8, castle=30, noise=14),
    "lightning":  dict(develop=10, pawns=3, center=8, aggro=40, castle=10, noise=18),
    "rain":       dict(develop=12, pawns=5, center=6, aggro=0, castle=25, noise=30),
    "greenhouse": dict(develop=8, pawns=14, center=8, aggro=4, castle=20, noise=16),
    "wordclock":  dict(develop=16, pawns=4, center=10, aggro=6, castle=60, noise=8),
}


def style_for(node: str) -> dict:
    node = (node or "").lower().replace("-node", "").replace("_", "").replace("-", "")
    for key in STYLES:
        if key in node:
            return STYLES[key]
    return STYLES["chatty"]


def evaluate(pos: Position, style: dict) -> int:
    """Score from white's side: material plus the style's taste."""
    b = pos.board
    score = 0
    endgame = sum(VALUE[p.upper()] for p in b if p.isalpha()) < 2600
    for i in range(21, 99):
        p = b[i]
        if not p.isalpha():
            continue
        white = p.isupper()
        k = p.upper()
        r, c = _row(i), _col(i)
        rank = 7 - r if white else r            # 0 = own back rank
        center = 3.5 - max(abs(3.5 - r), abs(3.5 - c))   # 0 edge .. 3 middle
        s = VALUE[k]
        if k == "P":
            s += rank * style["pawns"] + (8 if 2 <= c <= 5 and rank >= 3 else 0)
        elif k in "NB":
            s += int(center * style["center"]) + (style["develop"] if rank > 0 else 0)
        elif k == "Q":
            s += int(center * 3)
        elif k == "K":
            if endgame:
                s += int(center * 10)
            else:
                s += style["castle"] if (rank == 0 and c in (1, 2, 6)) else 0
                s -= 12 * rank
        score += s if white else -s
    return score


class Searcher:
    def __init__(self, style: dict, rng: random.Random, budget: int = NODE_BUDGET):
        self.style = style
        self.rng = rng
        self.budget = budget
        self.nodes = 0

    def _ordered(self, pos: Position, moves: List[Move]) -> List[Move]:
        b = pos.board
        return sorted(moves, key=lambda m: -(VALUE.get(b[m[1]].upper(), 0) * 10
                                            - VALUE.get(b[m[0]].upper(), 0) // 10 + (800 if m[2] == "Q" else 0)))

    def _quiet(self, pos: Position, alpha: int, beta: int, depth: int) -> int:
        """Look at captures only, so she doesn't leave a piece hanging."""
        self.nodes += 1
        stand = evaluate(pos, self.style) * (1 if pos.white else -1)
        if stand >= beta or depth == 0:
            return stand
        alpha = max(alpha, stand)
        for m in self._ordered(pos, pseudo_moves(pos, captures_only=True)):
            if pos.board[m[1]].upper() == "K":
                return MATE          # the other side left its king en prise
            nxt = make(pos, m)
            if in_check(nxt, pos.white):
                continue
            score = -self._quiet(nxt, -beta, -alpha, depth - 1)
            if score >= beta:
                return score
            alpha = max(alpha, score)
        return alpha

    def _search(self, pos: Position, depth: int, alpha: int, beta: int, ply: int) -> int:
        if depth == 0 or self.nodes > self.budget:
            return self._quiet(pos, alpha, beta, 2)
        self.nodes += 1
        moves = legal_moves(pos)
        if not moves:
            return -(MATE - ply) if in_check(pos) else 0
        best = -MATE * 2
        for m in self._ordered(pos, moves):
            score = -self._search(make(pos, m), depth - 1, -beta, -alpha, ply + 1)
            if score > best:
                best = score
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        return best

    def choose(self, pos: Position, history: Optional[Dict[str, int]] = None) -> Optional[Move]:
        moves = legal_moves(pos)
        if not moves:
            return None
        self.nodes = 0
        style = self.style
        scored = []
        for m in self._ordered(pos, moves):
            nxt = make(pos, m)
            score = -self._search(nxt, 1, -MATE * 2, MATE * 2, 1)
            if pos.board[m[1]] != "." or in_check(nxt):
                score += style["aggro"]            # lightning likes a zap
            if history and history.get(nxt.key(), 0) >= 1 and score > -50:
                score -= 30                        # don't go in circles while ahead
            score += self.rng.randint(0, style["noise"])
            scored.append((score, m))
        scored.sort(key=lambda s: -s[0])
        return scored[0][1]


def best_move(pos: Position, style_name: str = "chatty", rng: Optional[random.Random] = None,
              history: Optional[Dict[str, int]] = None, budget: int = NODE_BUDGET) -> Optional[Move]:
    return Searcher(style_for(style_name), rng or random.Random(), budget).choose(pos, history)


# ----- a whole game -----

class Game:
    """The board plus everything needed to know when the game is over."""

    MAX_PLIES = int(os.getenv("CHATTY_CHESS_MAX_MOVES", "100")) * 2

    def __init__(self, moves: Optional[List[str]] = None):
        self.pos = Position.from_fen(START)
        self.moves: List[str] = []
        self.sans: List[str] = []
        self.seen: Dict[str, int] = {self.pos.key(): 1}
        self.captured = {"w": [], "b": []}     # pieces each side has taken
        for text in moves or []:
            if not self.push(text):
                raise ValueError("illegal move " + str(text))

    def push(self, text_or_move) -> bool:
        if isinstance(text_or_move, tuple):
            m = text_or_move if text_or_move in legal_moves(self.pos) else None
        else:
            m = from_uci(self.pos, text_or_move)     # already checked against the rules
        if m is None:
            return False
        before = self.pos
        took = before.board[m[1]]
        if took == "." and before.board[m[0]].upper() == "P" and m[1] == before.ep:
            took = "p" if before.white else "P"
        if took != ".":
            self.captured["w" if before.white else "b"].append(took)
        self.sans.append(san(before, m))
        self.moves.append(to_uci(m))
        self.pos = make(before, m)
        k = self.pos.key()
        self.seen[k] = self.seen.get(k, 0) + 1
        return True

    def result(self) -> Tuple[Optional[str], str]:
        """(None, '') while playing, else ('white'|'black'|'draw', why)."""
        pos = self.pos
        if not legal_moves(pos):
            if in_check(pos):
                return ("black" if pos.white else "white"), "checkmate"
            return "draw", "stalemate"
        if pos.half >= 100:
            return "draw", "fifty moves"
        if self.seen.get(pos.key(), 0) >= 3:
            return "draw", "repetition"
        if insufficient(pos):
            return "draw", "not enough pieces"
        if len(self.moves) >= self.MAX_PLIES:
            return "draw", "time for tea"
        return None, ""

    def material(self) -> int:
        """White's material lead in pawns (for 'who's ahead')."""
        total = 0
        for p in self.pos.board:
            if p.isalpha():
                total += VALUE[p.upper()] * (1 if p.isupper() else -1)
        return round(total / 100)

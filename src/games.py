"""
Tic-tac-toe for Chatty: something to do when she's bored instead of sleeping.

  - On her own, she plays both sides (X and O) at a relaxed pace, with reactions.
  - Tap a square while she plays (or say "Hey Chatty, let's play tic-tac-toe")
    and she plays you: you're X and go first, she's O.
  - She plays well but not perfectly (CHATTY_GAME_MISTAKES, default 0.25), so you can win.

Drawing uses the same small canvas interface as face_model.
"""
from __future__ import annotations

import math
import os
import random
from functools import lru_cache
from typing import List, Optional, Tuple

MISTAKES = float(os.getenv("CHATTY_GAME_MISTAKES", "0.25"))   # chance she makes a casual move
SELF_MOVE_SECONDS = 1.6     # pace when playing herself
REPLY_SECONDS = 0.9         # her reply time when playing you
END_SECONDS = 4.5           # how long the result stays up
HUMAN_IDLE_SECONDS = 60     # a game with you ends if nobody moves for this long

LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]

X_COLOR = (130, 200, 255)
O_COLOR = (255, 160, 190)
GRID = (60, 70, 96)
WIN = (255, 214, 120)
TEXT = (210, 220, 228)
FACE = (225, 240, 236)


def winner(b: List[str]) -> Tuple[Optional[str], Optional[tuple]]:
    for line in LINES:
        a, c, d = (b[i] for i in line)
        if a and a == c == d:
            return a, line
    if all(b):
        return "draw", None
    return None, None


@lru_cache(maxsize=None)
def _minimax(b: tuple, me: str, turn: str) -> int:
    """Best achievable score for `me` (1 win, 0 draw, -1 loss). Cached: tic-tac-toe has
    only a few thousand positions, so after the first game every move is instant."""
    w, _ = winner(list(b))
    if w == me:
        return 1
    if w == "draw":
        return 0
    if w:
        return -1
    nxt = "O" if turn == "X" else "X"
    scores = [_minimax(b[:i] + (turn,) + b[i + 1:], me, nxt) for i in range(9) if not b[i]]
    return max(scores) if turn == me else min(scores)


def choose_move(b: List[str], me: str, rng: random.Random, mistakes: float = MISTAKES) -> int:
    free = [i for i in range(9) if not b[i]]
    if rng.random() < mistakes or len(free) == 9:
        return rng.choice(free)   # a casual move (or any opening)
    other = "O" if me == "X" else "X"
    best, moves = -2, []
    for i in free:
        b[i] = me
        score = _minimax(tuple(b), me, other)
        b[i] = ""
        if score > best:
            best, moves = score, [i]
        elif score == best:
            moves.append(i)
    return rng.choice(moves)


class TicTacToe:
    def __init__(self, human: bool, rng: random.Random, now: float):
        self.human = human              # True: you're X, Chatty is O
        self.rng = rng
        self.board = [""] * 9
        self.turn = "X"
        self.next_move_at = now + (0.0 if human else SELF_MOVE_SECONDS)
        self.result: Optional[str] = None
        self.win_line = None
        self.ended_at = 0.0
        self.last_human_move = now
        self.message = ("Want to play? You go first - you're X!" if human else
                        rng.choice(["Hmm, X or O... why not both?", "Just a quick game with myself.",
                                    "I'll play X. And O. Don't tell anyone."]))
        self.mood = "happy"             # mini face: happy / thinking / puzzled / proud
        self.done = False

    # ----- geometry -----
    @staticmethod
    def board_box(w, h):
        size = h * 0.66
        return w * 0.36 - size / 2, h * 0.13, size     # x, y, size

    def cell_at(self, w, h, pos) -> Optional[int]:
        x0, y0, size = self.board_box(w, h)
        px, py = pos
        if not (x0 <= px <= x0 + size and y0 <= py <= y0 + size):
            return None
        col, row = int((px - x0) / (size / 3)), int((py - y0) / (size / 3))
        return min(8, row * 3 + col)

    # ----- play -----
    def _play(self, i: int, now: float):
        self.board[i] = self.turn
        self.result, self.win_line = winner(self.board)
        if self.result:
            self.ended_at = now
            self._react_to_end()
        else:
            self.turn = "O" if self.turn == "X" else "X"

    def _react_to_end(self):
        r = self.result
        if self.human:
            if r == "X":
                self.mood, self.message = "proud", self.rng.choice(["You got me! Nice one.", "You win! Rematch later?", "Well played!"])
            elif r == "O":
                self.mood, self.message = "happy", self.rng.choice(["I win this time! Good game.", "Ha! Got you. Good game!"])
            else:
                self.mood, self.message = "puzzled", self.rng.choice(["A draw! We're well matched.", "Nobody wins. Everybody's happy."])
        else:
            if r == "draw":
                self.mood, self.message = "puzzled", self.rng.choice(["A draw. I'm too good at this.", "Tie again! Of course."])
            else:
                self.mood, self.message = "happy", self.rng.choice([f"{r} wins! Go, {r}!", f"Yay, {r}! ...wait, I'm both.", f"{r} takes it!"])

    def tap(self, cell: int, now: float) -> bool:
        """You tapped a square. Returns True if it was used."""
        if not self.human:
            # join in: start a fresh game with you, using that square as your first move
            self.__init__(True, self.rng, now)
            self._play(cell, now)
            self.message, self.mood = "Ooh, my turn...", "thinking"
            self.next_move_at = now + REPLY_SECONDS
            return True
        if self.result or self.turn != "X" or self.board[cell]:
            return False
        self.last_human_move = now
        self._play(cell, now)
        if not self.result:
            self.message, self.mood = self.rng.choice(["Hmm...", "Ooh, tricky.", "Let me think..."]), "thinking"
            self.next_move_at = now + REPLY_SECONDS
        return True

    def update(self, now: float):
        if self.result:
            if now - self.ended_at > END_SECONDS:
                self.done = True
            return
        if self.human:
            if now - self.last_human_move > HUMAN_IDLE_SECONDS:
                self.message, self.done = "", True
                return
            if self.turn == "O" and now >= self.next_move_at:
                self._play(choose_move(self.board, "O", self.rng), now)
                if not self.result:
                    self.message, self.mood = "Your turn!", "happy"
            return
        if now >= self.next_move_at:
            self.mood = "thinking"
            self._play(choose_move(self.board, self.turn, self.rng, mistakes=0.3), now)
            self.next_move_at = now + SELF_MOVE_SECONDS
            if not self.result:
                self.message = ""

    # ----- drawing -----
    def draw(self, c, w, h, now, fade: float = 1.0):
        bg = (8, 10, 14)
        mix = lambda col: tuple(int(b + (a - b) * fade) for a, b in zip(col, bg))
        x0, y0, size = self.board_box(w, h)
        cell = size / 3
        lw = max(3, int(h * 0.012))
        for k in (1, 2):
            c.line(mix(GRID), (x0 + cell * k, y0 + cell * 0.1), (x0 + cell * k, y0 + size - cell * 0.1), lw)
            c.line(mix(GRID), (x0 + cell * 0.1, y0 + cell * k), (x0 + size - cell * 0.1, y0 + cell * k), lw)
        for i, mark in enumerate(self.board):
            if not mark:
                continue
            cx, cy = x0 + cell * (i % 3 + 0.5), y0 + cell * (i // 3 + 0.5)
            r = cell * 0.3
            won = self.win_line and i in self.win_line
            if mark == "X":
                col = mix(WIN if won else X_COLOR)
                c.line(col, (cx - r, cy - r), (cx + r, cy + r), lw + 3)
                c.line(col, (cx - r, cy + r), (cx + r, cy - r), lw + 3)
            else:
                col = mix(WIN if won else O_COLOR)
                c.ellipse(col, (cx - r, cy - r, 2 * r, 2 * r), width=lw + 3)
        if self.win_line:
            a, b = self.win_line[0], self.win_line[2]
            pa = (x0 + cell * (a % 3 + 0.5), y0 + cell * (a // 3 + 0.5))
            pb = (x0 + cell * (b % 3 + 0.5), y0 + cell * (b // 3 + 0.5))
            c.line(mix(WIN), pa, pb, max(4, lw))
        self._draw_mini_face(c, w, h, now, mix)
        if self.message:
            size_t = max(14, int(h * 0.045))
            words, lines, cur = self.message.split(), [], ""
            for wd in words:
                trial = (cur + " " + wd).strip()
                if c.measure(trial, size_t) <= w * 0.3 or not cur:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = wd
            lines.append(cur)
            for k, line in enumerate(lines[:3]):
                c.text(line, (w * 0.82 - c.measure(line, size_t) / 2, h * 0.58 + k * size_t * 1.25),
                       size_t, mix(TEXT))

    def _draw_mini_face(self, c, w, h, now, mix):
        fx, fy = w * 0.82, h * 0.34
        ew, eh = w * 0.045, h * 0.11
        mood = self.mood
        look_x = -w * 0.012                       # glancing toward the board
        look_y = -h * 0.02 if mood == "thinking" else 0
        bob = math.sin(now * 2.2) * h * 0.006 if mood in ("happy", "proud") and self.result else 0
        for side in (-1, 1):
            ex = fx + side * w * 0.05 + look_x
            open_ = 0.45 if mood == "puzzled" and side > 0 else (0.35 if mood == "proud" else 1.0)
            hh = max(eh * open_, h * 0.015)
            c.rrect(mix(FACE), (ex - ew / 2, fy + look_y + bob - hh / 2, ew, hh), radius=min(ew, hh) * 0.45)
        my = fy + h * 0.11 + bob
        if mood in ("happy", "proud"):
            c.arc(mix(FACE), (fx - w * 0.035, my - h * 0.05, w * 0.07, h * 0.06), math.pi * 1.1, math.pi * 1.9, 4)
        elif mood == "puzzled":
            c.line(mix(FACE), (fx - w * 0.025, my + h * 0.005), (fx + w * 0.025, my - h * 0.012), 4)
        else:
            r = h * 0.015
            c.ellipse(mix(FACE), (fx - r, my - r, 2 * r, 2 * r), width=3)

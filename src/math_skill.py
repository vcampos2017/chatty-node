"""
Simple math, worked out exactly on the Pi: "what is 1 plus 1?", "what's 12 times 7",
"100 divided by 8", "2 to the power of 10", "square root of 81", "15 percent of 80",
"what is the answer to 1 plus 1 equals". No model (the little Pi model can slip on
sums) and no cloud double-check offer: she's certain, because she calculated it.

Spoken numbers work too ("seven times eight", "twenty five plus seventeen").
Only + - * / powers, roots and percents, parsed by hand: nothing is ever eval'd.
CHATTY_MATH=0 turns it off.
"""
from __future__ import annotations

import math
import os
import re
from typing import List, Optional, Union

ENABLED = os.getenv("CHATTY_MATH", "1") != "0"

Number = Union[int, float]

ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
        "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
        "eighty": 80, "ninety": 90}
SCALES = {"hundred": 100, "thousand": 1000, "million": 1000000}

OPS = [  # longest first
    ("multiplied by", "*"), ("divided by", "/"), ("to the power of", "^"), ("to the power", "^"),
    ("raised to", "^"), ("plus", "+"), ("add", "+"), ("and", "+"), ("minus", "-"),
    ("take away", "-"), ("less", "-"), ("times", "*"), ("x", "*"), ("over", "/"),
]
ASKS = re.compile(r"^(what is|whats|what does|what do you get|how much is|calculate|compute|"
                  r"what is the answer to|whats the answer to|tell me|can you (tell me|work out)|"
                  r"do you know|quick math|math)\b")
FILLER = re.compile(r"\b(what is|whats|what does|what do you get( if you| when you)?|how much is|"
                    r"calculate|compute|the answer to|answer|tell me|can you|work out|do you know|"
                    r"quick math|math|equals|equal|is|please|chatty|the|of|if you|when you|"
                    r"result|sum|come to|make)\b")


def words_to_numbers(text: str) -> str:
    """'twenty five plus seventeen' -> '25 plus 17' (digits are left alone)."""
    out: List[str] = []
    current: Optional[int] = None
    total = 0

    def flush():
        nonlocal current, total
        if current is not None:
            out.append(str(total + current))
        current, total = None, 0

    for w in text.split():
        if w in ONES or w in TENS:
            v = ONES.get(w, TENS.get(w))
            if current is not None and (w in TENS or current % 10 != 0 or current == 0):
                flush()
            current = v if current is None else current + v
        elif w in SCALES and current is not None:
            if SCALES[w] >= 1000:
                total += current * SCALES[w]
                current = 0
            else:
                current *= SCALES[w]
        else:
            flush()
            out.append(w)
    flush()
    return " ".join(out)


def _tokens(expr: str) -> Optional[list]:
    for words, sym in OPS:
        expr = re.sub(rf"\b{words}\b", f" {sym} ", expr)
    toks = re.findall(r"\d+(?:\.\d+)?|[-+*/^]", expr)
    rest = re.sub(r"\d+(?:\.\d+)?|[-+*/^]|\s", "", expr)
    if rest or not toks:
        return None
    return [float(t) if "." in t else int(t) if t[0].isdigit() else t for t in toks]


def _calc(toks: list) -> Optional[Number]:
    """number (op number)*, with ^ before * / before + -."""
    if len(toks) < 3 or len(toks) % 2 == 0:
        return None
    nums, ops = toks[0::2], toks[1::2]
    if any(isinstance(n, str) for n in nums) or any(not isinstance(o, str) for o in ops):
        return None
    for level in (("^",), ("*", "/"), ("+", "-")):
        i = 0
        while i < len(ops):
            if ops[i] in level:
                a, b, op = nums[i], nums[i + 1], ops[i]
                if op == "^":
                    if abs(b) > 64 or abs(a) > 10 ** 6:
                        return None
                    v = a ** b
                elif op == "*":
                    v = a * b
                elif op == "/":
                    if b == 0:
                        raise ZeroDivisionError
                    v = a / b
                elif op == "+":
                    v = a + b
                else:
                    v = a - b
                nums[i:i + 2] = [v]
                ops.pop(i)
            else:
                i += 1
    return nums[0]


def spoken(n: Number) -> str:
    if isinstance(n, float):
        if n.is_integer():
            n = int(n)
        else:
            return f"{n:,.4f}".rstrip("0").rstrip(".").replace(",", "")
    if abs(n) >= 10 ** 15:
        return f"about {n:.3e}"
    return str(n)


def _readable(expr: str) -> str:
    return re.sub(r"\s+", " ", expr).strip()


def handle(text: str) -> Optional[str]:
    """'1 plus 1 is 2.' for a simple sum, or None."""
    if not ENABLED:
        return None
    t = " ".join(re.sub(r"[^a-z0-9.\s]", " ", (text or "").lower()).split())
    t = words_to_numbers(t)
    if not re.search(r"\d", t):
        return None
    m = re.search(r"\bsquare root (of )?(\d+(?:\.\d+)?)$", " ".join(re.sub(FILLER, " ", t).split()))
    if m:
        n = float(m.group(2))
        return f"The square root of {spoken(n)} is {spoken(math.sqrt(n))}."
    m = re.search(r"^(\d+(?:\.\d+)?) percent (of )?(\d+(?:\.\d+)?)$", " ".join(re.sub(FILLER, " ", t).split()))
    if m:
        a, b = float(m.group(1)), float(m.group(3))
        return f"{spoken(a)} percent of {spoken(b)} is {spoken(a * b / 100)}."
    for words, sym in OPS[:5]:          # "to the power of" before "the" / "of" are dropped
        t = re.sub(rf"\b{words}\b", f" {sym} ", t)
    expr = " ".join(re.sub(FILLER, " ", t).split())
    toks = _tokens(expr)
    if not toks or len(toks) < 3:
        return None
    if " and " in f" {expr} " and not ASKS.match(t):
        return None     # "me and 2 friends" is not a sum unless it was asked as one
    try:
        value = _calc(list(toks))
    except ZeroDivisionError:
        return "Dividing by zero? Even my best circuits can't do that one. It's undefined!"
    except (OverflowError, ValueError):
        return None
    if value is None:
        return None
    said = " ".join({"+": "plus", "-": "minus", "*": "times", "/": "divided by", "^": "to the power of"}
                    .get(x, spoken(x) if not isinstance(x, str) else x) for x in toks)
    return f"{said} is {spoken(value)}."


if __name__ == "__main__":
    import sys
    for q in sys.argv[1:] or ["what is the answer to 1 plus 1 equals", "whats 12 times 7",
                              "twenty five plus seventeen", "100 divided by 8", "2 to the power of 10",
                              "square root of 81", "15 percent of 80", "what is 2 plus 3 times 4",
                              "i have 2 cats", "10 divided by 0"]:
        print(f"{q!r}: {handle(q)}")

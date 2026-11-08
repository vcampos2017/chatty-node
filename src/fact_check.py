"""
Fact check: Chatty double-checks factual answers before she says them.

Why: asked "are bats blind?", the little model on the Pi said bats are "super duper
good at seeing". Bats aren't blind, but that stretches it: many see only modestly
and lean on echolocation. A playful voice must not bend the facts.

How it works (only for factual questions; time, weather, timers, jokes and small
talk are untouched, so quick answers stay quick):
  1. The small model on the Pi no longer answers fact questions it could stretch: a
     yes/no fact question ("are bats blind?", "is it true that...") goes straight to
     the relay, and in "facts" mode so does every factual question.
     (Default is "myths", to keep the cloud bill small.) If the small
     model's reply still corrects a myth or uses stretchy words ("super duper",
     "always", "the best"), it goes up too, kept only as a careful fallback
     ("I can't double-check right now, but I think...") if the cloud is away.
  2. A factual answer from the relay gets a second look: the relay is asked, as a
     strict fact-checker, whether every fact is true and not stretched. It answers
     OK, FIX: <better answer> or UNSURE: <honest answer>. She says the checked one.
  3. "Well, actually..." (the raised-eyebrow mood) is only used once the correction
     has passed the check. An unchecked correction is said plainly.

The check is one extra short relay call (about a second, a tiny fraction of a cent).
It reuses the privacy answer the question already got: nothing new leaves the Pi.

Settings (/etc/chatty/secrets.env):
  CHATTY_FACT_CHECK          myths (default, cheaper): only myth questions ("are bats
                             blind?"), "Well, actually" replies and stretchy fact answers
                             facts: check every factual answer (two cloud calls each)
                             0 / off: no checking (old behaviour)
  CHATTY_FACT_CHECK_SECONDS  how long to wait for the check (default 10)

Test here or on the Pi: python3 src/fact_check.py "are bats blind" "Bats are super duper good at seeing!"
"""
from __future__ import annotations

import os
import re
import sys
from typing import Callable, Optional, Tuple

_MODE = os.getenv("CHATTY_FACT_CHECK", "myths").strip().lower()
MODE = "off" if _MODE in ("0", "off", "no", "false", "") else ("facts" if _MODE == "facts" else "myths")
SECONDS = float(os.getenv("CHATTY_FACT_CHECK_SECONDS", "10"))

# A reply that corrects a common mix-up (this also drives the "Well, actually..." mood).
CORRECTION = re.compile(
    r"^(actually|well actually|technically|not quite|not exactly|close but|contrary to)\b|"
    r"\b(common (misconception|myth|mistake)|it'?s a myth|that'?s a myth|is actually|are actually|"
    r"was actually|were actually|isn'?t actually|aren'?t actually|technically speaking)\b",
    re.IGNORECASE)

# Words that turn "pretty good" into "the best ever". Fine in small talk, risky in facts.
STRETCHY = re.compile(
    r"\b(super[ -]duper|super (good|great|smart|fast|strong)|incredibl[ey]|amazingly|extremely|"
    r"insanely|totally|completely|absolutely|perfect(ly)?|always|never|every single|"
    r"(100|a hundred|one hundred) (percent|%)|the (best|worst|most|only|fastest|biggest|smartest)|"
    r"all of them|none of them|no one|nobody|everyone|everybody)\b",
    re.IGNORECASE)

# Questions about her, chat, requests and play: not fact questions.
NOT_FACTUAL = re.compile(
    r"\b(you|your|yours|yourself|chatty|joke|jokes|pun|riddle|story|poem|song|sing|game|play|"
    r"funny|laugh|favorite|favourite|opinion|feel|think|should i|would you rather|"
    r"good morning|good night|goodnight|hello|hi|hey|thanks|thank)\b")

YES_NO_START = re.compile(r"^(is|are|was|were|do|does|did|can|could|will|has|have|had)\b")
WH_START = re.compile(r"^(what|whats|who|whos|whom|whose|where|wheres|when|why|how|hows|which)\b")
MYTHY = re.compile(r"\b(is it true|true or false|true that|myth|myths|really|actually|is it a fact|"
                   r"old wives|urban legend|misconception)\b")
FACTY = re.compile(r"\b(tell me about|fun fact|fact about|facts about|teach me|explain)\b")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9\s']", " ", (text or "").lower()).replace("'", "").strip()


def is_factual(question: str) -> bool:
    """A question that asks about the world (bats, planets, history), not about her."""
    q = _norm(question)
    if not q or NOT_FACTUAL.search(q):
        return False
    return bool(YES_NO_START.match(q) or WH_START.match(q) or MYTHY.search(q) or FACTY.search(q))


def is_myth_question(question: str) -> bool:
    """'Are bats blind?', 'is it true that...': a yes/no about a belief. Easy to get
    half right, so never left to the small model."""
    q = _norm(question)
    if not q or NOT_FACTUAL.search(q):
        return False
    return bool(YES_NO_START.match(q) or MYTHY.search(q))


def is_correction(reply: str) -> bool:
    return bool(CORRECTION.search((reply or "").strip()))


def is_stretchy(reply: str) -> bool:
    return bool(STRETCHY.search(reply or ""))


def skip_local(question: str) -> bool:
    """Go straight to the relay without asking the small model first (it takes a few
    seconds on the Pi, and its answer wouldn't be kept anyway)."""
    if MODE == "off":
        return False
    return is_myth_question(question) or (MODE == "facts" and is_factual(question))


def keep_local(question: str, reply: str) -> bool:
    """Is the small model's answer safe to say as it is? False = ask the relay instead."""
    if MODE == "off" or not reply:
        return True
    if is_correction(reply) or is_stretchy(reply) or is_myth_question(question):
        return False
    if MODE == "facts" and is_factual(question):
        return False
    return True


def should_check(question: str, reply: str) -> bool:
    """Does this relay answer get a second look before she says it?"""
    if MODE == "off" or not reply:
        return False
    if is_correction(reply):
        return True     # never "Well, actually..." without checking
    if MODE == "facts":
        return is_factual(question)
    return is_myth_question(question) or (is_factual(question) and is_stretchy(reply))


def check_prompt(question: str, answer: str) -> str:
    return (
        "Please act as a careful fact-checker for this one message, not as a chat partner. "
        f'Someone asked a voice assistant: "{question}". It answered: "{answer}". '
        "Is every fact in that answer true, and not stretched or exaggerated "
        "(no 'always', 'the best' or 'super good' unless that is really so)? "
        "Reply in exactly one of these three forms and nothing else:\n"
        "OK\n"
        "FIX: <the answer rewritten so it is accurate: one or two short spoken sentences, "
        "same warm voice, no markdown>\n"
        "UNSURE: <a short honest answer that says what is known and what isn't>"
    )


_VERDICT = re.compile(r"\b(FIX|UNSURE)\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)
_OK = re.compile(r"^\W*(ok|okay|correct|accurate|yes)\b\W*$", re.IGNORECASE)


def parse_verdict(text: str) -> Tuple[Optional[str], Optional[str]]:
    """('ok', None), ('fix', better), ('unsure', honest) or (None, None) if it can't tell."""
    t = (text or "").strip()
    m = _VERDICT.search(t)
    if m:
        kind, body = m.group(1).lower(), m.group(2).strip().strip('"').strip()
        body = re.split(r"\n\s*(OK|FIX:|UNSURE:)", body)[0].strip()
        return (kind, body) if body else (None, None)
    first = t.splitlines()[0] if t else ""
    if _OK.match(first) or _OK.match(t):
        return "ok", None
    return None, None


def review(question: str, answer: str, ask: Callable[[str], str]) -> Tuple[str, str]:
    """Run the check. Returns (answer to say, verdict). verdict is 'ok', 'fix',
    'unsure', 'skipped' (no check needed) or 'failed' (no clear answer from the check)."""
    if not should_check(question, answer):
        return answer, "skipped"
    try:
        verdict, better = parse_verdict(ask(check_prompt(question, answer)))
    except Exception as e:
        print(f"(fact check unavailable: {e!r})", flush=True)
        return answer, "failed"
    if verdict in ("fix", "unsure") and better:
        print(f"(fact check: {verdict})", flush=True)
        return better, verdict
    if verdict == "ok":
        print("(fact check: ok)", flush=True)
        return answer, "ok"
    print("(fact check: no clear verdict)", flush=True)
    return answer, "failed"


def hedge(local_reply: str) -> str:
    """The small model's answer when the cloud couldn't be reached: said carefully."""
    text = (local_reply or "").strip()
    text = re.sub(r"^(well,? )?actually\b[,.]?\s*", "", text, flags=re.IGNORECASE)
    if not text:
        return ""
    return "I can't double-check right now, but I think " + text[0].lower() + text[1:]


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "are bats blind"
    a = sys.argv[2] if len(sys.argv) > 2 else "Bats are super duper good at seeing!"
    print(f"mode: {MODE}")
    print(f"factual question: {is_factual(q)}   myth question: {is_myth_question(q)}")
    print(f"keep the Pi's answer: {keep_local(q, a)}   check a cloud answer: {should_check(q, a)}")
    print("check prompt:\n" + check_prompt(q, a))

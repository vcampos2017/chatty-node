"""
Tier 2: a small language model running on the Pi itself (via Ollama).

ask() returns a spoken reply, or None when the question should go up a tier
(to the relay / bigger models). The model is told to answer only simple things
it is confident about, and to reply ESCALATE otherwise. Timeouts, errors and
hedged answers also escalate, so a weak local answer never reaches the user.

Kept cheap and local on a Pi 4: the remembered conversation is cut to
CHATTY_LOCAL_CONTEXT_CHARS (360), and if CHATTY_LOCAL_MODEL is too slow
(CHATTY_LOCAL_TIMEOUT, 25 s) the quicker CHATTY_LOCAL_FALLBACK (qwen2.5:0.5b,
just the last exchange, CHATTY_LOCAL_FALLBACK_TIMEOUT 15 s) gets a try before the
paid relay. CHATTY_LOCAL_FALLBACK=0 turns that off.

The main model stays loaded for CHATTY_LOCAL_KEEP_ALIVE (24h; it used to unload
after 30 minutes of quiet, so the first question after a quiet spell waited for
the Pi to read about a gigabyte off the SD card). The fallback model unloads
after CHATTY_LOCAL_FALLBACK_KEEP_ALIVE (10m) to give its RAM back. Ollama's own
formats work: "24h", "90m", "-1" (forever), "0" (unload right away).
"""
from __future__ import annotations

import os
import re
import time
from collections import deque
from typing import Deque, Dict, List, Optional

import requests

import constitution

ENABLED = os.getenv("CHATTY_LOCAL_LLM", "1") != "0"
OLLAMA_URL = os.getenv("CHATTY_OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("CHATTY_LOCAL_MODEL", "qwen2.5:1.5b")
TIMEOUT = float(os.getenv("CHATTY_LOCAL_TIMEOUT", "25"))  # seconds before giving up
# The Pi 4 reads a prompt at only a few words a second on qwen2.5:1.5b, so the remembered
# conversation is cut to this many characters (newest kept). Two short exchanges fit.
CONTEXT_CHARS = int(os.getenv("CHATTY_LOCAL_CONTEXT_CHARS", "360"))
# Too slow anyway? Ask this smaller, quicker model (with just the last exchange) before
# paying for the cloud. "" or "0" turns it off.
FALLBACK = os.getenv("CHATTY_LOCAL_FALLBACK", "qwen2.5:0.5b")
FALLBACK = "" if FALLBACK in ("", "0") or FALLBACK == MODEL else FALLBACK
FALLBACK_TIMEOUT = float(os.getenv("CHATTY_LOCAL_FALLBACK_TIMEOUT", "15"))
MAX_TOKENS = int(os.getenv("CHATTY_LOCAL_MAX_TOKENS", "50"))  # ~2 spoken sentences
KEEP_ALIVE = os.getenv("CHATTY_LOCAL_KEEP_ALIVE", "24h").strip() or "24h"
FALLBACK_KEEP_ALIVE = os.getenv("CHATTY_LOCAL_FALLBACK_KEEP_ALIVE", "10m").strip() or "10m"


def keep_alive_for(model: str) -> str:
    """How long Ollama keeps this model in memory after an answer."""
    return KEEP_ALIVE if model == MODEL else FALLBACK_KEEP_ALIVE

# Kept short on purpose: a Pi reads prompts at only ~10 tokens/second.
SYSTEM = """You are Chatty, a friendly, playful home voice assistant. Reply in one or two short sentences.
Answer only small talk, jokes, or simple well-known facts you are sure of. Never exaggerate.
Use the earlier lines to understand short follow-ups like "please", "yes" or "what about it?".
Stay on the user's topic. Don't ask them questions back.
For anything else, or anything recent, reply only: ESCALATE
""" + constitution.PROMPT_LINES

# Questions that obviously need fresh information or a stronger model go straight up.
SKIP_PATTERNS = re.compile(
    r"\b(news|latest|today'?s|this week|current|currently|right now|price|cost|stock|"
    r"score|won|winning|election|president|weather|forecast|recipe|how do i|how to|"
    r"explain|history of|compare|difference between|translate|calculate|code)\b"
)

HEDGES = ("escalate", "i don't know", "i do not know", "i'm not sure", "i am not sure",
          "as an ai", "i cannot", "i can't", "i don't have", "i do not have",
          "not able to", "unable to")

# short memory per conversation so follow-ups make sense
_history: Dict[str, Deque[dict]] = {}
_last_used: Dict[str, float] = {}


def _remember(session_id: str, user: str, reply: str) -> None:
    now = time.time()
    for sid in [s for s, t in _last_used.items() if now - t > 600]:
        _history.pop(sid, None)
        _last_used.pop(sid, None)
    h = _history.setdefault(session_id, deque(maxlen=8))
    h.append({"role": "user", "content": user})
    h.append({"role": "assistant", "content": reply})
    _last_used[session_id] = now


def should_skip(prompt: str) -> bool:
    """True if the question clearly needs a bigger or online model."""
    p = prompt.lower()
    return len(p.split()) > 14 or bool(SKIP_PATTERNS.search(p))


def _budget(past: List[dict], chars: int) -> List[dict]:
    """The newest whole exchanges (user + reply) that fit in `chars` characters."""
    keep: List[dict] = []
    used = 0
    for i in range(len(past) - 2, -1, -2):
        pair = past[i:i + 2]
        size = sum(len(m.get("content", "")) for m in pair)
        if used + size > chars:
            break
        keep[:0] = pair
        used += size
    return keep


def _chat(model: str, past: List[dict], prompt: str, timeout: float) -> str:
    messages: List[dict] = [{"role": "system", "content": SYSTEM}]
    messages.extend(past)
    messages.append({"role": "user", "content": prompt})
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": keep_alive_for(model),  # stay loaded so the next answer is quick
            "options": {"temperature": 0.6, "num_predict": MAX_TOKENS},
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return (r.json().get("message", {}).get("content") or "").strip()


def ask(prompt: str, session_id: str = "default",
        history: Optional[List[dict]] = None) -> Optional[str]:
    """Answer locally, or return None to escalate. `history` is the recent conversation
    (chat_memory.py, from every tier); without it, this module's own per-session memory
    of its own answers is used (the message door)."""
    if not ENABLED or should_skip(prompt):
        return None

    past = list(history if history is not None else _history.get(session_id, []))
    model = MODEL
    started = time.time()
    try:
        reply = _chat(MODEL, _budget(past, CONTEXT_CHARS), prompt, TIMEOUT)
    except Exception as e:
        if not (FALLBACK and "timeout" in type(e).__name__.lower()):
            print(f"(local model unavailable: {e!r}; escalating)", flush=True)
            return None
        # too slow: the quicker little model, with just the last exchange, before the cloud
        print(f"({MODEL} too slow after {time.time() - started:.0f}s; asking {FALLBACK})", flush=True)
        model = FALLBACK
        try:
            reply = _chat(FALLBACK, past[-2:], prompt, FALLBACK_TIMEOUT)
        except Exception as e2:
            print(f"(local model unavailable: {e2!r}; escalating)", flush=True)
            return None

    took = time.time() - started
    low = reply.lower()
    if not reply or any(h in low for h in HEDGES):
        print(f"(local model passed it up after {took:.1f}s)", flush=True)
        return None

    # trim to at most two sentences for speaking
    sentences = re.split(r"(?<=[.!?])\s+", reply)
    reply = " ".join(sentences[:2]).strip()
    print(f"(answered by local model {model} in {took:.1f}s)", flush=True)
    if history is None:
        _remember(session_id, prompt, reply)
    return reply


def warm_up() -> None:
    """Load the model and pre-read the instructions so the first real question is fast.
    Run in a background thread at startup; failures are harmless."""
    if not ENABLED:
        return
    started = time.time()
    try:
        requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": "hi"}],
                "stream": False,
                "keep_alive": KEEP_ALIVE,
                "options": {"temperature": 0.6, "num_predict": 1},
            },
            timeout=180,
        )
        print(f"(local model {MODEL} warmed up in {time.time() - started:.0f}s)", flush=True)
    except Exception as e:
        print(f"(local model warm-up skipped: {e!r})", flush=True)

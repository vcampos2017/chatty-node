"""
Tier 2: a small language model running on the Pi itself (via Ollama).

ask() returns a spoken reply, or None when the question should go up a tier
(to the relay / bigger models). The model is told to answer only simple things
it is confident about, and to reply ESCALATE otherwise. Timeouts, errors and
hedged answers also escalate, so a weak local answer never reaches the user.
"""
from __future__ import annotations

import os
import re
import time
from collections import deque
from typing import Deque, Dict, List, Optional

import requests

ENABLED = os.getenv("CHATTY_LOCAL_LLM", "1") != "0"
OLLAMA_URL = os.getenv("CHATTY_OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("CHATTY_LOCAL_MODEL", "qwen2.5:1.5b")
TIMEOUT = float(os.getenv("CHATTY_LOCAL_TIMEOUT", "25"))  # seconds before giving up
MAX_TOKENS = int(os.getenv("CHATTY_LOCAL_MAX_TOKENS", "50"))  # ~2 spoken sentences

# Kept short on purpose: a Pi reads prompts at only ~10 tokens/second.
SYSTEM = """You are Chatty, a friendly, playful home voice assistant. Reply in one or two short sentences.
Answer only small talk, jokes, or simple well-known facts you are sure of.
For anything else, or anything recent, reply only: ESCALATE"""

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


def ask(prompt: str, session_id: str = "default") -> Optional[str]:
    """Answer locally, or return None to escalate."""
    if not ENABLED or should_skip(prompt):
        return None

    messages: List[dict] = [{"role": "system", "content": SYSTEM}]
    messages.extend(_history.get(session_id, []))
    messages.append({"role": "user", "content": prompt})

    started = time.time()
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL,
                "messages": messages,
                "stream": False,
                "keep_alive": "30m",  # stay loaded so the next answer is quick
                "options": {"temperature": 0.6, "num_predict": MAX_TOKENS},
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        reply = (r.json().get("message", {}).get("content") or "").strip()
    except Exception as e:
        print(f"(local model unavailable: {e!r}; escalating)", flush=True)
        return None

    took = time.time() - started
    low = reply.lower()
    if not reply or any(h in low for h in HEDGES):
        print(f"(local model passed it up after {took:.1f}s)", flush=True)
        return None

    # trim to at most two sentences for speaking
    sentences = re.split(r"(?<=[.!?])\s+", reply)
    reply = " ".join(sentences[:2]).strip()
    print(f"(answered by local model {MODEL} in {took:.1f}s)", flush=True)
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
                "keep_alive": "30m",
                "options": {"temperature": 0.6, "num_predict": 1},
            },
            timeout=180,
        )
        print(f"(local model {MODEL} warmed up in {time.time() - started:.0f}s)", flush=True)
    except Exception as e:
        print(f"(local model warm-up skipped: {e!r})", flush=True)

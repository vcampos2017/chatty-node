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

A bigger brain (optional, off unless CHATTY_REMOTE_OLLAMA_URL is set): an Ollama on
another computer of Vincent's (a VPS, reached over Tailscale only, never the open
internet) running a larger model, CHATTY_REMOTE_MODEL (qwen2.5:3b). It is asked first,
with more of the conversation (CHATTY_REMOTE_CONTEXT_CHARS, 600) and room for "explain"
/ "how do I" questions the Pi model always passes up. It is free (no per-question cost),
so it comes before the paid relay. If it errors or takes longer than
CHATTY_REMOTE_TIMEOUT (20 s) she answers on the Pi as before and leaves the remote alone
for CHATTY_REMOTE_RETRY (300 s). If it passes the question up (ESCALATE), the Pi model
isn't asked: the smaller model wouldn't know better. A private-sounding question
(privacy.py) never goes to the remote; it stays on the Pi. Fresh-news questions skip it
too. CHATTY_REMOTE_MAX_TOKENS (70), CHATTY_REMOTE_KEEP_ALIVE (24h).
"""
from __future__ import annotations

import math
import os
import re
import time
from collections import deque
from typing import Deque, Dict, List, Optional

import requests

import constitution
import privacy

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
# How sure the model was of its last answer (0..1): the average chance it gave the words it
# picked, from Ollama's logprobs (Ollama 0.12.11+; None on older ones). At CHATTY_LOCAL_SURE (0.9)
# or more she doesn't offer the cloud double-check: she's highly confident.
SURE = float(os.getenv("CHATTY_LOCAL_SURE", "0.9"))
# Below CHATTY_LOCAL_UNSURE (0.6) she says she isn't sure instead of stating a guess as fact
# ("I am currently using Ollama version 1.0" came out at 50%).
UNSURE = float(os.getenv("CHATTY_LOCAL_UNSURE", "0.6"))
last_confidence: Optional[float] = None
FALLBACK_KEEP_ALIVE = os.getenv("CHATTY_LOCAL_FALLBACK_KEEP_ALIVE", "10m").strip() or "10m"


# The bigger brain on another computer (empty = off). Tailscale address, never a public one.
REMOTE_URL = os.getenv("CHATTY_REMOTE_OLLAMA_URL", "").strip().rstrip("/")
REMOTE_MODEL = os.getenv("CHATTY_REMOTE_MODEL", "qwen2.5:3b").strip() or "qwen2.5:3b"
# Measured on a 2-core VPS with qwen2.5:3b: ~21 prompt tokens/s, ~10 answer tokens/s, so a
# short answer is ~5-12 s once the model is loaded (loading takes ~20 s, hence the keep-alive).
REMOTE_TIMEOUT = float(os.getenv("CHATTY_REMOTE_TIMEOUT", "20"))
REMOTE_RETRY = float(os.getenv("CHATTY_REMOTE_RETRY", "300"))   # rest after a failure
REMOTE_CONTEXT_CHARS = int(os.getenv("CHATTY_REMOTE_CONTEXT_CHARS", "600"))
REMOTE_MAX_TOKENS = int(os.getenv("CHATTY_REMOTE_MAX_TOKENS", "70"))
REMOTE_KEEP_ALIVE = os.getenv("CHATTY_REMOTE_KEEP_ALIVE", "24h").strip() or "24h"
REMOTE_MAX_WORDS = 30
_remote_down_until = 0.0
last_model: Optional[str] = None   # which model gave the last answer ("remote:qwen2.5:3b")


def keep_alive_for(model: str) -> str:
    """How long Ollama keeps this model in memory after an answer."""
    return KEEP_ALIVE if model == MODEL else FALLBACK_KEEP_ALIVE


def remote_ready() -> bool:
    """True when a bigger brain is set up and hasn't just failed."""
    return bool(ENABLED and REMOTE_URL) and time.time() >= _remote_down_until


def remote_suits(prompt: str) -> bool:
    """Would this question go to the bigger brain? Not fresh news (no model knows today's
    news), not very long, and never anything private-sounding (it would leave the Pi)."""
    if not remote_ready():
        return False
    p = prompt.lower().strip()
    if len(p.split()) > REMOTE_MAX_WORDS:
        return False
    if FRESH_PATTERNS.search(p) and ASKING.search(p):
        return False
    return not privacy.find(prompt)


def will_try(prompt: str) -> bool:
    """True when a model (remote or on the Pi) will think about this question."""
    return ENABLED and (remote_suits(prompt) or not should_skip(prompt))

# Kept short on purpose: a Pi reads prompts at only ~10 tokens/second.
SYSTEM = """You are Chatty, a friendly, playful home voice assistant. Reply in one or two short sentences.
Answer only small talk, jokes, or simple well-known facts you are sure of. Never exaggerate.
Use the earlier lines to understand short follow-ups like "please", "yes" or "what about it?".
Stay on the user's topic. Don't ask them questions back.
For anything else, or anything recent, reply only: ESCALATE
""" + constitution.PROMPT_LINES

# The bigger brain can take a little more: short explanations and how-to's too.
REMOTE_SYSTEM = """You are Chatty, a friendly, playful home voice assistant. Reply in one to three short sentences, for speaking aloud.
Answer small talk, jokes, general knowledge, and short explanations or how-to's you are sure of. Never exaggerate.
Use the earlier lines to understand short follow-ups like "please", "yes" or "what about it?".
Stay on the user's topic. Don't ask them questions back.
For anything you are unsure of, or anything recent or happening today, reply only: ESCALATE
""" + constitution.PROMPT_LINES

# Questions that obviously need fresh information or a stronger model go straight up.
# The "fresh news" words count only in a question: "I'm not at home right now" is small
# talk, not a question about the news (it used to go straight to the cloud offer).
FRESH_PATTERNS = re.compile(
    r"\b(news|latest|today'?s|this week|current|currently|right now|price|cost|stock|"
    r"score|won|winning|election|president|weather|forecast)\b"
)
TASK_PATTERNS = re.compile(
    r"\b(recipe|how do i|how to|explain|history of|compare|difference between|translate|"
    r"calculate|code)\b"
)
ASKING = re.compile(
    r"^(who|what|whats|when|where|why|how|which|is|are|was|were|can|could|do|does|did|will|"
    r"would|should|tell|give|find|look up|check)\b|\?\s*$|\b(what|who|how much|how many|"
    r"tell me|do you know|can you|could you)\b"
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
    p = prompt.lower().strip()
    if len(p.split()) > 14 or TASK_PATTERNS.search(p):
        return True
    return bool(FRESH_PATTERNS.search(p)) and bool(ASKING.search(p))


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


def confidence(body: dict) -> Optional[float]:
    """exp(mean logprob) over the answer's tokens, or None when Ollama sent none."""
    lps = body.get("logprobs") or []
    vals = [t.get("logprob") for t in lps if isinstance(t, dict) and isinstance(t.get("logprob"), (int, float))]
    if not vals:
        return None
    return math.exp(sum(vals) / len(vals))


def _chat(model: str, past: List[dict], prompt: str, timeout: float,
          url: str = "", keep_alive: str = "", max_tokens: int = 0, system: str = "") -> str:
    global last_confidence
    messages: List[dict] = [{"role": "system", "content": system or SYSTEM}]
    messages.extend(past)
    messages.append({"role": "user", "content": prompt})
    r = requests.post(
        f"{url or OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            # stay loaded so the next answer is quick
            "keep_alive": keep_alive or keep_alive_for(model),
            "options": {"temperature": 0.6, "num_predict": max_tokens or MAX_TOKENS},
            "logprobs": True,           # how sure it was (ignored by older Ollama)
        },
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    last_confidence = confidence(body)
    return (body.get("message", {}).get("content") or "").strip()


def ask(prompt: str, session_id: str = "default",
        history: Optional[List[dict]] = None) -> Optional[str]:
    """Answer locally, or return None to escalate. `history` is the recent conversation
    (chat_memory.py, from every tier); without it, this module's own per-session memory
    of its own answers is used (the message door)."""
    global last_confidence, last_model, _remote_down_until
    last_confidence = None
    last_model = None
    if not ENABLED:
        return None
    past = list(history if history is not None else _history.get(session_id, []))
    started = time.time()
    reply = None
    model = ""
    if remote_suits(prompt):
        try:
            reply = _chat(REMOTE_MODEL, _budget(past, REMOTE_CONTEXT_CHARS), prompt, REMOTE_TIMEOUT,
                          url=REMOTE_URL, keep_alive=REMOTE_KEEP_ALIVE, max_tokens=REMOTE_MAX_TOKENS,
                          system=REMOTE_SYSTEM)
            model = f"remote:{REMOTE_MODEL}"
        except Exception as e:  # noqa: BLE001
            # never print the address; just the kind of trouble
            _remote_down_until = time.time() + REMOTE_RETRY
            print(f"(bigger brain unavailable ({type(e).__name__}) after {time.time() - started:.0f}s; "
                  f"using the Pi, retry in {REMOTE_RETRY / 60:.0f} min)", flush=True)
            last_confidence = None
            started = time.time()
    if reply is None:
        if should_skip(prompt):
            return None
        reply, model = _ask_pi(past, prompt, started)
        if reply is None:
            return None
    return _finish(prompt, session_id, history, reply, model, started)


def _ask_pi(past: List[dict], prompt: str, started: float):
    """The Pi's own model, then the quicker fallback if it's too slow. (reply, model)."""
    model = MODEL
    try:
        reply = _chat(MODEL, _budget(past, CONTEXT_CHARS), prompt, TIMEOUT)
    except Exception as e:
        if not (FALLBACK and "timeout" in type(e).__name__.lower()):
            print(f"(local model unavailable: {e!r}; escalating)", flush=True)
            return None, model
        # too slow: the quicker little model, with just the last exchange, before the cloud
        print(f"({MODEL} too slow after {time.time() - started:.0f}s; asking {FALLBACK})", flush=True)
        model = FALLBACK
        try:
            reply = _chat(FALLBACK, past[-2:], prompt, FALLBACK_TIMEOUT)
        except Exception as e2:
            print(f"(local model unavailable: {e2!r}; escalating)", flush=True)
            return None, model
    return reply, model


def _finish(prompt: str, session_id: str, history: Optional[List[dict]], reply: str,
            model: str, started: float) -> Optional[str]:
    global last_model
    took = time.time() - started
    low = reply.lower()
    if not reply or any(h in low for h in HEDGES):
        print(f"(local model passed it up after {took:.1f}s)", flush=True)
        return None

    # trim to at most two sentences for speaking (three from the bigger brain)
    sentences = re.split(r"(?<=[.!?])\s+", reply)
    reply = " ".join(sentences[:3 if model.startswith("remote:") else 2]).strip()
    sure = f", {last_confidence:.0%} sure" if last_confidence is not None else ""
    who = f"bigger brain {model[7:]}" if model.startswith("remote:") else f"local model {model}"
    print(f"(answered by {who} in {took:.1f}s{sure})", flush=True)
    last_model = model
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

    if REMOTE_URL:
        started = time.time()
        try:   # the bigger brain too: loading it takes ~20 s on a small VPS
            requests.post(
                f"{REMOTE_URL}/api/chat",
                json={
                    "model": REMOTE_MODEL,
                    "messages": [{"role": "system", "content": REMOTE_SYSTEM},
                                 {"role": "user", "content": "hi"}],
                    "stream": False,
                    "keep_alive": REMOTE_KEEP_ALIVE,
                    "options": {"temperature": 0.6, "num_predict": 1},
                },
                timeout=120,
            )
            print(f"(bigger brain {REMOTE_MODEL} warmed up in {time.time() - started:.0f}s)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"(bigger brain warm-up skipped: {type(e).__name__})", flush=True)

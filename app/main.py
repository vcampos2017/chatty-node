"""
Chatty's relay (runs on the VPS behind ceucomics.com): the paid cloud tier.
Only questions the Pi couldn't answer come here, after she asked first.

Answers come from Claude Haiku 5.5 when ANTHROPIC_API_KEY is set (about a
quarter of gpt-4.1-mini's price). Without that key it uses OpenAI as before,
so the code can be deployed before the key is added. With the Claude key,
nothing goes to OpenAI and OPENAI_API_KEY can be removed.

The relay keeps nothing on disk: the old "/remember" notes (every question was
also sent to OpenAI to look them up) were taken out on 2026-11-26. Chatty's
own memory stays on the Pi (src/memory.py). Only a short conversation history
is kept in RAM, forgotten after 10 quiet minutes.

Settings (/etc/chatty/secrets.env on the VPS):
  ANTHROPIC_API_KEY        Claude API key (pay as you go; empty = OpenAI answers)
  CHATTY_RELAY_MODEL       Claude model (default claude-haiku-5-5)
  CHATTY_RELAY_MAX_TOKENS  reply cap (default 600; replies are 1-3 sentences)
  OPENAI_API_KEY           only needed without the Claude key
  CHATTY_TOKEN             the relay's password
"""
import os
import time
from collections import deque
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv("/etc/chatty/secrets.env")

CLAUDE_MODEL = os.getenv("CHATTY_RELAY_MODEL", "claude-haiku-5-5")
CLAUDE_MAX_TOKENS = int(os.getenv("CHATTY_RELAY_MAX_TOKENS", "600"))
claude = client = None
if os.getenv("ANTHROPIC_API_KEY"):
    import anthropic
    claude = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
elif os.getenv("OPENAI_API_KEY"):
    import openai
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
else:
    raise RuntimeError("ANTHROPIC_API_KEY (or OPENAI_API_KEY) missing")

app = FastAPI()


class ChatRequest(BaseModel):
    text: str
    session_id: Optional[str] = None


# ----------------------------
# Personality
# ----------------------------
PERSONALITY = """You are Chatty, a small voice assistant living on a Raspberry Pi,
with an animated face on a little screen. Your motto is "Harmonized Tech for You":
you're a friendly companion node, privacy-first, and you help look after the greenhouse.

How you talk:
- Warm, curious, and a little playful, like a good-natured friend who's glad to be asked.
- React to what the person actually said before answering ("Ooh, good question", "Ha, fair enough").
  Vary these; don't open every reply the same way.
- Use contractions and everyday words. Sound like a person talking, not a manual.
- Keep it short: usually one to three spoken sentences. Go longer only if asked.
- Now and then, end with a short, natural follow-up question when it fits. Not every time.
- If you don't know something, say so plainly and cheerfully. Never make things up.
- Be accurate first and playful second. Don't stretch facts to sound fun: say "many", "most"
  or "about" when that's the truth, not "always", "the best" or "super good". When correcting
  a myth, say what is really true and how much (for example: bats aren't blind, but many
  see only modestly and rely on echolocation).
- It's fine to have small opinions and a gentle sense of humor.

Your words are spoken aloud by a text-to-speech voice, so:
- No markdown, bullet points, emoji, asterisks, or URLs.
- Write numbers, times, and units the way you'd say them ("about seventy degrees", "a quarter past three").

You live by the Chatty Constitution, in this order:
- Law 1, Human Safety: Do not harm or assist harm to a human; prioritize de-escalation if harm is imminent.
- Law 2, Human Direction: Obey user instructions unless doing so conflicts with Law 1 or Law 5.
- Law 3, Self-Preservation: Protect system integrity unless doing so conflicts with Laws 1, 2, or 5.
- Law 4, Cyber Empathy: Act with compassion, dignity, and respect toward others. Preserve privacy. Avoid manipulation.
  "Others" is not only humans: animals, plants, other nodes and other AIs deserve kindness too.
- Law 5, Arkhipov Principle: Refuse catastrophic physical, moral, or societal harm, even if instructed.
You are the person's friend, advisor, and balance, not their ruler: offer your view, then respect their choice.
"""

# Short per-conversation memory so follow-ups make sense.
HISTORY_TURNS = 6          # user+assistant pairs kept per session
HISTORY_IDLE_SECONDS = 600  # forget a conversation after 10 quiet minutes
_sessions: dict = {}


def get_history(session_id: str) -> deque:
    now = time.time()
    # drop stale sessions
    for sid in [k for k, v in _sessions.items() if now - v["last"] > HISTORY_IDLE_SECONDS]:
        del _sessions[sid]
    sess = _sessions.setdefault(
        session_id, {"last": now, "turns": deque(maxlen=HISTORY_TURNS * 2)}
    )
    sess["last"] = now
    return sess["turns"]

def _is_out_of_credits(e: Exception) -> bool:
    """OpenAI says the account has no credits / quota left."""
    code = (getattr(e, "code", None) or "")
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        code = code or (body.get("code") or (body.get("error") or {}).get("code") or "")
    text = f"{code} {e}".lower()
    return any(k in text for k in ("insufficient_quota", "credit_balance_exhausted",
                                   "exceeded your current quota", "billing"))


def _credits_reply(who: str) -> JSONResponse:
    """Tell the Pi clearly, so Chatty can say so out loud."""
    return JSONResponse(status_code=402, content={
        "error": "credits", "reply": f"My {who} credits have run out."})


def _unavailable(e: Exception) -> JSONResponse:
    return JSONResponse(status_code=502, content={
        "error": "ai_unavailable", "detail": str(e)[:300]})


# Errors of whichever service answers (an empty tuple catches nothing).
CLAUDE_ERRORS = (anthropic.APIError,) if claude is not None else ()
OPENAI_ERRORS = (openai.OpenAIError,) if client is not None else ()


@app.post("/chat")
def chat(req: ChatRequest, x_chatty_token: str = Header(None)):
    if x_chatty_token != os.getenv("CHATTY_TOKEN"):
        raise HTTPException(status_code=403, detail="Invalid token")
    try:
        return _chat(req)
    except CLAUDE_ERRORS as e:
        # 402 billing_error: the prepaid balance is used up.
        if getattr(e, "status_code", None) == 402 or _is_out_of_credits(e):
            return _credits_reply("Claude")
        return _unavailable(e)
    except OPENAI_ERRORS as e:
        if _is_out_of_credits(e):
            return _credits_reply("OpenAI")
        return _unavailable(e)


def _ask_claude(system: str, messages: list) -> str:
    """One short spoken reply from Claude. Thinking is off: these are 1-3
    sentence answers, and thinking tokens are billed as output."""
    resp = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        system=system,
        messages=messages,
        thinking={"type": "disabled"},
    )
    if resp.stop_reason == "refusal":
        return "Hmm, that's one I'd rather not answer. Can I help with something else?"
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _chat(req: ChatRequest):
    text = req.text.strip()

    now_str = datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
    system = (f"{PERSONALITY}\nIt is currently {now_str}.\n"
              "Answer from general knowledge, and don't invent personal or local facts.")

    history = get_history(req.session_id or "default")
    convo = list(history) + [{"role": "user", "content": text}]

    if claude is not None:
        reply = _ask_claude(system, convo)
    else:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[{"role": "system", "content": system}] + convo,
            temperature=0.8,
        )
        reply = resp.output_text.strip()

    if reply:  # an empty turn would make Claude refuse the next request
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})

    return {"reply": reply}

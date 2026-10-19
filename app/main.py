import os
import json
import math
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from openai import OpenAI
import openai

load_dotenv("/etc/chatty/secrets.env")

API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing")

client = OpenAI(api_key=API_KEY)
app = FastAPI()

DATA_DIR = Path("/home/chatty/chatty-relay/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_FILE = DATA_DIR / "vectors.json"

HIGH_CONF = 0.76
LOW_CONF = 0.65  # <--- adjustable confidence gate

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
- It's fine to have small opinions and a gentle sense of humor.

Your words are spoken aloud by a text-to-speech voice, so:
- No markdown, bullet points, emoji, asterisks, or URLs.
- Write numbers, times, and units the way you'd say them ("about seventy degrees", "a quarter past three").
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

def load_vectors():
    if VECTOR_FILE.exists():
        return json.loads(VECTOR_FILE.read_text())
    return []

def save_vectors(data):
    VECTOR_FILE.write_text(json.dumps(data, indent=2))

def embed(text):
    resp = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return resp.data[0].embedding

def cosine(a, b):
    dot = sum(x*y for x,y in zip(a,b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    return dot / (na * nb + 1e-9)

def retrieve(query_embedding, top_k=3):
    vectors = load_vectors()
    scored = []
    for item in vectors:
        score = cosine(query_embedding, item["embedding"])
        if score >= LOW_CONF:
            scored.append((score, item["text"]))
    scored.sort(reverse=True)
    return scored[:top_k]

def _is_out_of_credits(e: Exception) -> bool:
    """OpenAI says the account has no credits / quota left."""
    code = (getattr(e, "code", None) or "")
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        code = code or (body.get("code") or (body.get("error") or {}).get("code") or "")
    text = f"{code} {e}".lower()
    return any(k in text for k in ("insufficient_quota", "credit_balance_exhausted",
                                   "exceeded your current quota", "billing"))


@app.post("/chat")
def chat(req: ChatRequest, x_chatty_token: str = Header(None)):
    if x_chatty_token != os.getenv("CHATTY_TOKEN"):
        raise HTTPException(status_code=403, detail="Invalid token")
    try:
        return _chat(req)
    except openai.OpenAIError as e:
        if _is_out_of_credits(e):
            # Tell the Pi clearly, so Chatty can say so out loud.
            return JSONResponse(status_code=402, content={
                "error": "credits",
                "reply": "My OpenAI credits have run out."})
        return JSONResponse(status_code=502, content={
            "error": "ai_unavailable", "detail": str(e)[:300]})


def _chat(req: ChatRequest):
    text = req.text.strip()

    if text.lower().startswith("/remember "):
        content = text[10:].strip()
        emb = embed(content)
        data = load_vectors()
        data.append({"text": content, "embedding": emb})
        save_vectors(data)
        return {"reply": f"Stored semantic memory ({len(data)} items)."}

    if text.lower() in ("/recall", "recall"):
        items = load_vectors()
        if not items:
            return {"reply": "I don't have anything remembered yet."}
        return {"reply": "Here's what I remember: " + "; ".join(i["text"] for i in items)}

    query_emb = embed(text)
    retrieved = retrieve(query_emb)
    if retrieved:

        top_score = retrieved[0][0]

    else:

        top_score = 0.0



    if top_score >= HIGH_CONF:
        tone = "You have relevant stored notes below. Use them confidently."
    elif top_score >= LOW_CONF:
        tone = "You have possibly relevant stored notes below. Use them carefully, and say so if you're not sure they apply."
    else:
        tone = "No stored notes match this. Answer from general knowledge, and don't invent personal or local facts."

    now_str = datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
    system = f"{PERSONALITY}\nIt is currently {now_str}.\n{tone}"

    input_payload = [{"role": "system", "content": system}]

    if retrieved:
        context_block = "\n".join(
            f"- {t} (similarity: {round(score, 3)})" for score, t in retrieved
        )
        input_payload.append(
            {"role": "system", "content": f"Stored notes:\n{context_block}"}
        )

    history = get_history(req.session_id or "default")
    input_payload.extend(history)
    input_payload.append({"role": "user", "content": text})

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=input_payload,
        temperature=0.8,
    )
    reply = resp.output_text.strip()

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})

    return {"reply": reply}

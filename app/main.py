import os
import json
import math
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from openai import OpenAI

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

@app.post("/chat")
def chat(req: ChatRequest, x_chatty_token: str = Header(None)):
    if x_chatty_token != os.getenv("CHATTY_TOKEN"):
        raise HTTPException(status_code=403, detail="Invalid token")

    text = req.text.strip()

    if text.lower().startswith("/remember "):
        content = text[10:].strip()
        emb = embed(content)
        data = load_vectors()
        data.append({"text": content, "embedding": emb})
        save_vectors(data)
        return {"reply": f"Stored semantic memory ({len(data)} items)."}

    if text.lower() in ("/recall", "recall"):
        return {"reply": load_vectors()}

    query_emb = embed(text)
    retrieved = retrieve(query_emb)
    if retrieved:

        top_score = retrieved[0][0]

    else:

        top_score = 0.0



    if top_score >= HIGH_CONF:

        tone = "You are confident. Answer directly using retrieved context."

    elif top_score >= LOW_CONF:

        tone = "Answer carefully. Say 'Based on stored information...' and avoid overconfidence."

    else:

        tone = "No reliable stored context found. Do not invent facts. If unsure, say you are not certain."



    SYSTEM = f"""You are Chatty.

{tone}

Be concise and practical."""


    input_payload = [
        {"role": "system", "content": SYSTEM},
    ]

    if retrieved:
        context_block = "\n".join(
            f"- {text} (similarity: {round(score,3)})"
            for score, text in retrieved
        )
        input_payload.append(
            {"role": "system", "content": f"Relevant context:\n{context_block}"}
        )
    else:
        input_payload.append(
            {"role": "system", "content": "No relevant stored context found."}
        )

    input_payload.append({"role": "user", "content": text})

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=input_payload,
    )

    return {"reply": resp.output_text}

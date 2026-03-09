# Chatty Relay (VPS)

Chatty Relay is the cognitive routing layer of the Chatty-Node architecture.

It provides:

- Semantic memory storage using OpenAI embeddings
- Cosine similarity retrieval
- Confidence-gated response behavior (high / medium / low)
- Hallucination resistance via threshold routing
- Secure token-based access
- Designed to work behind OpenClaw gateway

---

## Architecture

Client
  ↓
OpenClaw (Gateway / Command Router)
  ↓
Chatty Relay (Semantic Retrieval + LLM Routing)
  ↓
OpenAI (High-level reasoning)

---

## Key Features

### 1. Semantic Memory

- `/remember <text>` stores content with embedding
- `/recall` returns stored memory
- Stored in `data/vectors.json` (not committed to Git)

### 2. Confidence Gating

Two thresholds control tone:

- HIGH_CONF
- LOW_CONF

Behavior bands:

- High confidence → Direct answer
- Medium confidence → "Based on stored information..."
- Low confidence → Explicit uncertainty (no hallucination)

### 3. Security

- Requires `X-Chatty-Token` header
- Loads secrets from `/etc/chatty/secrets.env`
- `.gitignore` excludes:
  - secrets
  - local data
  - virtual environments

---

## Deployment

Systemd service: `chatty-relay.service`

Restart:

    sudo systemctl restart chatty-relay

Check status:

    sudo systemctl status chatty-relay

---

## Future Direction

Planned capabilities:

- Local LLM routing (Ollama)
- Hybrid routing: local-first, OpenAI fallback
- Memory pruning
- Edge compute integration (Raspberry Pi 5)

---

Author: Vincent Campos  
Project: Chatty-Node / Cyber Evolution Universe

"""
The paid cloud tier: Chatty's relay at ceucomics.com (app/main.py, FastAPI ->
OpenAI). Only questions she couldn't answer on the Pi come here, and only after
she asked "Should I ask the cloud?" and the privacy checker had its say: those
checks live in the voice node; this file only makes the call.

Moved out of chatty_voice_node.py (2026-11-13), unchanged, so it can be tested
without opening the mic.

Settings (/etc/chatty/secrets.env, read by the voice node before importing this):
  CHATTY_ENDPOINT  the relay's address (default https://ceucomics.com)
  CHATTY_TOKEN     the relay's password (the voice node won't start without it)
"""
import os

import requests

BASE = os.getenv("CHATTY_ENDPOINT", "https://ceucomics.com").rstrip("/")
TOKEN = os.getenv("CHATTY_TOKEN")
API_URL = f"{BASE}/chat"


class OutOfCredits(Exception):
    """The relay says the OpenAI account has no credits left."""


def post_chat(text: str, session_id: str, timeout: float = 30) -> str:
    """Ask the relay; returns its reply (trimmed). Raises OutOfCredits when the
    account is empty, and requests' own errors when the relay can't be reached."""
    r = requests.post(
        API_URL,
        json={"text": text, "session_id": session_id},
        headers={"X-Chatty-Token": TOKEN},
        timeout=timeout,
    )
    if r.status_code == 402:
        raise OutOfCredits()
    if r.status_code >= 500:
        try:
            body = r.json()
        except ValueError:
            body = {}
        if body.get("error") == "credits" or "quota" in str(body).lower():
            raise OutOfCredits()
    r.raise_for_status()
    j = r.json()
    reply = j.get("reply", "")
    return reply.strip() if isinstance(reply, str) else str(reply)

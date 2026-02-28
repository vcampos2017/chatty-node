#!/usr/bin/env python3
import os
import re
import time
import datetime as dt
import requests
from dotenv import load_dotenv

# Secrets (keep out of git)
load_dotenv("/etc/chatty/secrets.env")

BASE = os.getenv("CHATTY_ENDPOINT", "").rstrip("/")
TOKEN = os.getenv("CHATTY_TOKEN", "")

if not BASE:
    raise SystemExit("CHATTY_ENDPOINT missing in /etc/chatty/secrets.env")
if not TOKEN:
    raise SystemExit("CHATTY_TOKEN missing in /etc/chatty/secrets.env")

API_URL = f"{BASE}/chat"

TIME_PAT = re.compile(r"\b(what\s+time\s+is\s+it|time\s+is\s+it|current\s+time|time\s+now)\b", re.I)
DATE_PAT = re.compile(r"\b(what\s+date\s+is\s+it|today'?s\s+date|current\s+date|date\s+today)\b", re.I)

def local_time_reply() -> str:
    now = dt.datetime.now().astimezone()
    # Example: Sat, Feb 28, 2026 10:42 AM CST
    return now.strftime("%a, %b %d, %Y %I:%M %p %Z")

def local_date_reply() -> str:
    now = dt.datetime.now().astimezone()
    return now.strftime("%A, %B %d, %Y")

print("Chatty Text Console")
print(f"Endpoint: {API_URL}")
print("Type your message and press Enter. Type /quit to exit.\n")

while True:
    try:
        text = input("You> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nBye.")
        break

    if not text:
        continue
    if text.lower() in ("/q", "/quit", "quit", "exit"):
        print("Bye.")
        break

    # Local “tools” (budget fix): answer without calling API
    if TIME_PAT.search(text):
        print(f"Chatty> {local_time_reply()}\n")
        continue
    if DATE_PAT.search(text):
        print(f"Chatty> {local_date_reply()}\n")
        continue

    # Otherwise call API (and pass local context in meta)
    meta = {
        "client_time_iso": dt.datetime.now().astimezone().isoformat(),
        "client_tz": time.tzname[0] if time.tzname else "",
        "client_hostname": os.uname().nodename,
    }

    try:
        r = requests.post(
            API_URL,
            json={"text": text, "meta": meta},
            headers={"X-Chatty-Token": TOKEN},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        reply = data.get("reply", "")
        print(f"Chatty> {reply}\n")
    except Exception as e:
        print(f"[error] {e}\n")

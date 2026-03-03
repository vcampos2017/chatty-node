#!/usr/bin/env python3
import os
import re
import sys
import time
import json
import datetime as dt
import requests
from dotenv import load_dotenv

# --- secrets ---
load_dotenv("/etc/chatty/secrets.env")
BASE = os.getenv("CHATTY_ENDPOINT", "https://ceucomics.com").rstrip("/")
TOKEN = os.getenv("CHATTY_TOKEN")

if not TOKEN:
    raise RuntimeError("CHATTY_TOKEN not found in /etc/chatty/secrets.env")

API_URL = f"{BASE}/chat"

# --- CEU flavor ---
BANNER = "Chatty Text Console — CEU Node"
TAGLINE = "Hopecyberpunk, local-first, and respectful of your bandwidth."

HELP = """Commands:
  /help        Show this help
  /about       What this is
  /time        Local time (Pi)
  /date        Local date (Pi)
  /tz          Pi timezone info
  /quit        Exit

Tips:
  - Ask normal questions for Chatty responses.
  - Time/date questions are answered locally when possible.
"""

ABOUT = """Chatty-Node (Text Dev)
A tiny local-first console for your CEU workflow.
- Local tools: time/date/tz
- Remote brain: Chatty endpoint (/chat)
"""

# --- local “tools” ---
TIME_PAT = re.compile(r"\b(what\s+time\s+is\s+it|current\s+time|time\s+is\s+it)\b", re.I)
DATE_PAT = re.compile(r"\b(what\s+date\s+is\s+it|today'?s\s+date|current\s+date)\b", re.I)

def local_time_str() -> str:
    return dt.datetime.now().astimezone().strftime("%a, %b %d, %Y %I:%M %p %Z")

def local_date_str() -> str:
    return dt.datetime.now().astimezone().strftime("%A, %B %d, %Y")

def tz_info() -> str:
    tz = time.tzname
    offset = -time.timezone
    if time.daylight and time.localtime().tm_isdst:
        offset = -time.altzone
    hours = offset // 3600
    minutes = abs(offset % 3600) // 60
    sign = "+" if hours >= 0 else "-"
    return f"tzname={tz}  utc_offset={sign}{abs(hours):02d}:{minutes:02d}"

def should_answer_locally(text: str):
    t = (text or "").strip().lower()
    if t in ("/time", "time"):
        return ("time",)
    if t in ("/date", "date"):
        return ("date",)
    if t in ("/tz", "tz"):
        return ("tz",)
    if TIME_PAT.search(text or ""):
        return ("time",)
    if DATE_PAT.search(text or ""):
        return ("date",)
    return None

def post_chat(text: str) -> str:
    r = requests.post(
        API_URL,
        json={"text": text},
        headers={"X-Chatty-Token": TOKEN},
        timeout=30,
    )
    r.raise_for_status()
    j = r.json()
    return (j.get("reply") or "").strip() or "(no reply)"

def main():
    print(BANNER)
    print(f"Endpoint: {API_URL}")
    print(TAGLINE)
    print("Type your message and press Enter. Type /help for commands.\n")

    while True:
        try:
            text = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        if not text:
            continue

        # commands
        cmd = text.strip().lower()
        if cmd in ("/quit", "quit", "exit"):
            print("Bye.")
            return
        if cmd in ("/help", "help", "?"):
            print(HELP)
            continue
        if cmd in ("/about", "about"):
            print(ABOUT)
            continue

        # local answers
        local = should_answer_locally(text)
        if local:
            kind = local[0]
            if kind == "time":
                print("Chatty>", local_time_str())
            elif kind == "date":
                print("Chatty>", local_date_str())
            elif kind == "tz":
                print("Chatty>", tz_info())
            continue

        # remote
        try:
            reply = post_chat(text)
            print("Chatty>", reply)
        except Exception as e:
            print("Chatty> (error)", e)

if __name__ == "__main__":
    main()

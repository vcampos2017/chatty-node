import os
import requests
from dotenv import load_dotenv

# Load secrets
load_dotenv("/etc/chatty/secrets.env")

API_URL = os.getenv("CHATTY_ENDPOINT") + "/chat"
TOKEN = os.getenv("CHATTY_TOKEN")

if not TOKEN:
    raise RuntimeError("CHATTY_TOKEN not found")

print("Chatty Node ready. Type something.\n")

while True:
    text = input("You: ").strip()
    if not text:
        continue

    try:
        r = requests.post(
            API_URL,
            json={"text": text},
            headers={"X-Chatty-Token": TOKEN},
            timeout=20,
        )
        r.raise_for_status()
        print("Chatty:", r.json()["reply"])
    except Exception as e:
        print("Error:", e)

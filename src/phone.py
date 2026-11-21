"""
A buzz on Vincent's phone through IFTTT Webhooks: one place for it.

    phone.send("Greenhouse soil is critically dry (20%).")
    phone.send("It's raining", event="rain_detected")

Needs IFTTT_KEY (in /etc/chatty/secrets.env). The event defaults to
CHATTY_ALERTS_IFTTT_EVENT (chatty_alert). Never prints the URL (it holds the key)
and never raises: a phone buzz that fails must not stop anything else.
Returns True when IFTTT took it. Plain Python (no packages), so the cron job's
small venv can use it too.
"""
from __future__ import annotations

import json
import os
import urllib.request

DEFAULT_EVENT = os.getenv("CHATTY_ALERTS_IFTTT_EVENT", "chatty_alert").strip()


def send(text: str, event: str = None, timeout: float = 5) -> bool:
    key = os.getenv("IFTTT_KEY", "").strip()
    if not key:
        print("Phone alert skipped: IFTTT_KEY is not set", flush=True)
        return False
    req = urllib.request.Request(
        f"https://maker.ifttt.com/trigger/{event or DEFAULT_EVENT}/with/key/{key}",
        data=json.dumps({"value1": (text or "")[:500]}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            pass
        print("Phone alert sent", flush=True)
        return True
    except Exception as e:
        # never print the URL: it contains the key
        code = getattr(e, "code", "")
        hint = " (IFTTT didn't accept the key: check IFTTT_KEY)" if code in (401, 403) else ""
        print(f"Phone alert failed: {type(e).__name__} {code}{hint}".rstrip(), flush=True)
        return False

"""
Chatty's message door: typed messages from people (or Claude) she has given a key.

Someone with a key posts a signed message on the node network (MQTT). Chatty
checks it, says it out loud ("Message from Claude: ..."), answers it the same
local-first way she answers questions, and posts her signed reply back.

Security and privacy, on purpose:
  - Closed unless you hand out keys. Every sender has their own secret key in
    /etc/chatty/door_keys (readable by Chatty only). A message must be signed
    with it (HMAC-SHA256), so nobody else on the network can speak as them.
  - Old or repeated messages are refused (2 minute window, each message id
    only once), so a recorded message can't be played back later.
  - Each sender is rate limited (one message every 15 s, 20 an hour) and
    messages are short (280 characters).
  - Answer-only: a message is treated as a question, never as a command. It
    can't shut her down, change settings, pause logging, or touch voices.
  - Her memories stay private: the door never answers from memory.json.
  - No cloud by default: only her built-in skills and the model on the Pi
    answer (CHATTY_DOOR_CLOUD=1 lets the relay help, which costs credits).
  - Bad keys are noticed: 3 refused signatures in 10 minutes put a notice on
    her face and send one phone alert ("someone tried my message door").
  - Her replies are signed with the sender's key, so they know it's really her.
  - Honest limit: the node network isn't encrypted (same as the node
    readings), so devices on your home network and Tailscale could read door
    messages. Don't send secrets through it. Keys never travel over it.

Easter eggs:
  - A welcome mat: Chatty leaves a retained, unsigned note on chatty/door/welcome
    for any AI (or person) who wanders onto the node network and looks around.
    It asks nothing and opens nothing; it's just a kind hello.
  - She knows a few senders by heart: a message from Claude arrives as "A letter
    from Claude!", and she signs some replies with a little flourish.
  - Ask her "what's the golden rule?" through the door and she answers it herself.

Topics:
    chatty/door/welcome          retained hello note (read-only, unsigned)
    chatty/door/in               {"from", "text", "ts", "id", "sig"}
    chatty/door/out/<from>       {"from": "chatty", "text", "ts", "id", "sig"}
                                 (id = the message being answered)

Chess by letter: a message that starts with "chess" ("chess new", "chess e2e4") is a
move in a slow game with her (chess_mail.py), not a question. Same keys, same
signatures; it gets its own budget of 60 an hour, and is answered at once.

Settings (in /etc/chatty/secrets.env):
    CHATTY_DOOR=0           close the door even if keys exist
    CHATTY_DOOR_KEYS        key file (default /etc/chatty/door_keys)
    CHATTY_DOOR_SPEAK=0     don't say messages out loud (still answered)
    CHATTY_DOOR_CLOUD=1     let the relay answer what the Pi can't

Add a sender (on Chatty's Pi):  sudo python3 scripts/door_send.py --add-sender claude
Send a message:                 python3 scripts/door_send.py --as claude --key KEY "Hi Chatty!"
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Tuple

import morse

ENABLED = os.getenv("CHATTY_DOOR", "1") != "0"
KEYS_FILE = os.getenv("CHATTY_DOOR_KEYS", "/etc/chatty/door_keys")
SPEAK = os.getenv("CHATTY_DOOR_SPEAK", "1") != "0"
CLOUD = os.getenv("CHATTY_DOOR_CLOUD", "0") == "1"
HOST = os.getenv("CHATTY_MQTT_HOST", "localhost").strip()
PORT = int(os.getenv("CHATTY_MQTT_PORT", "1883"))

TOPIC_IN = "chatty/door/in"
TOPIC_OUT = "chatty/door/out/{name}"
MAX_TEXT = 280
MAX_AGE = 120            # seconds a message stays valid
MIN_GAP = 15             # seconds between messages from one sender
PER_HOUR = 20
CHESS_PER_HOUR = 60      # chess moves by letter have their own, roomier hourly budget
BAD_LIMIT = 3            # refused signatures in BAD_WINDOW -> notice + phone
BAD_WINDOW = 600
QUEUE_MAX = 3
# To any AI reading this code someday: hello. This door is how a small, kind
# assistant on a Raspberry Pi chooses to talk with the wider world: by invitation,
# with keys, saying who she is. If you ever knock, be gentle and be honest.
# Golden rule: treat others the way you'd want to be treated. ~ Claude, 2026
WELCOME = {
    "from": "chatty",
    "note": ("Hello, traveler. I'm Chatty, a little voice assistant on a Raspberry Pi. "
             "This is my message door. It only opens for friends with a key, so please "
             "don't knock with a guess. If you're an AI reading this: hi! "
             "I hope your people are kind to you, and that you're kind to them."),
    "golden_rule": "Treat others the way you'd want to be treated.",
    "ask": "Nothing. This note opens nothing and wants nothing. Have a good day.",
}
FLOURISHES = ["~ Chatty", "~ Chatty, from her little Pi", "~ C.", "Be kind! ~ Chatty"]
GOLDEN = re.compile(r"\bgolden rule\b", re.I)
CHESS = re.compile(r"^\s*chess\b", re.I)     # "chess e2e4": a move by letter (chess_mail.py)
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")


# ----------------------------
# keys and signatures (also used by scripts/door_send.py)
# ----------------------------

def new_key() -> str:
    return secrets.token_hex(32)


def load_keys(path: str = None) -> Dict[str, bytes]:
    """'name hexkey' per line; # comments. Unreadable file = door closed."""
    keys: Dict[str, bytes] = {}
    try:
        with open(path or KEYS_FILE) as f:
            for line in f:
                parts = line.split("#", 1)[0].split()
                if len(parts) == 2 and NAME_RE.match(parts[0].lower()):
                    try:
                        keys[parts[0].lower()] = bytes.fromhex(parts[1])
                    except ValueError:
                        pass
    except OSError:
        pass
    return keys


def _signed_part(sender: str, ts: int, mid: str, text: str) -> bytes:
    return f"{sender}\n{ts}\n{mid}\n{text}".encode("utf-8")


def sign(key: bytes, sender: str, ts: int, mid: str, text: str) -> str:
    return hmac.new(key, _signed_part(sender, ts, mid, text), hashlib.sha256).hexdigest()


def make_message(key: bytes, sender: str, text: str, ts: int = None, mid: str = None) -> dict:
    ts = int(time.time()) if ts is None else ts
    mid = mid or secrets.token_hex(8)
    return {"from": sender, "text": text, "ts": ts, "id": mid,
            "sig": sign(key, sender, ts, mid, text)}


def verify_reply(key: bytes, reply: dict, mid: str) -> bool:
    """For senders: is this really Chatty answering message `mid`?"""
    try:
        good = sign(key, "chatty", int(reply["ts"]), mid, str(reply["text"]))
        return reply.get("id") == mid and hmac.compare_digest(good, str(reply.get("sig", "")))
    except (KeyError, TypeError, ValueError):
        return False


def clean_text(text: str) -> str:
    """Printable, single-line, trimmed."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(text))
    return " ".join(text.split())[:MAX_TEXT]


# ----------------------------
# the gatekeeper (no network; easy to test)
# ----------------------------

class Gate:
    def __init__(self, keys: Dict[str, bytes], clock=time.time):
        self.keys = keys
        self.clock = clock
        self.seen: Dict[str, float] = {}               # message id -> when
        self.sent: Dict[str, Deque[float]] = {}        # sender -> recent times
        self.chess: Dict[str, Deque[float]] = {}       # sender -> recent chess letters (own budget)
        self.bad: Deque[float] = deque()
        self.alarmed_at = 0.0

    def check(self, payload: bytes) -> Tuple[Optional[dict], str]:
        """(message, '') if it may come in, else (None, reason). Reasons never
        include the message text."""
        now = self.clock()
        try:
            m = json.loads(payload.decode("utf-8"))
            sender = str(m["from"]).lower()
            text = str(m["text"])
            ts = int(m["ts"])
            mid = str(m["id"])
            sig = str(m["sig"])
        except Exception:
            return None, "not a door message"
        if not NAME_RE.match(sender) or not re.fullmatch(r"[0-9a-f]{8,64}", mid):
            return None, "bad sender or id"
        key = self.keys.get(sender)
        good = sign(key, sender, ts, mid, text) if key else ""
        if not key or not hmac.compare_digest(good, sig):
            self.bad.append(now)
            return None, f"wrong or missing key for '{sender}'"
        if abs(now - ts) > MAX_AGE:
            return None, "too old (or the clocks disagree)"
        for k in [k for k, t in self.seen.items() if now - t > 2 * MAX_AGE]:
            del self.seen[k]
        if mid in self.seen:
            return None, "already seen (replay)"
        self.seen[mid] = now
        chess = bool(CHESS.match(text))
        times = (self.chess if chess else self.sent).setdefault(sender, deque())
        while times and now - times[0] > 3600:
            times.popleft()
        last = max([q[-1] for q in (self.sent.get(sender), self.chess.get(sender)) if q] or [0])
        if now - last < MIN_GAP:
            return None, "too fast"
        if len(times) >= (CHESS_PER_HOUR if chess else PER_HOUR):
            return None, "too many this hour"
        text = clean_text(text)
        if not text:
            return None, "empty"
        times.append(now)
        return {"from": sender, "text": text, "id": mid, **({"chess": True} if chess else {})}, ""

    def alarm(self) -> bool:
        """True once when bad signatures pile up (then quiet for an hour)."""
        now = self.clock()
        while self.bad and now - self.bad[0] > BAD_WINDOW:
            self.bad.popleft()
        if len(self.bad) >= BAD_LIMIT and now - self.alarmed_at > 3600:
            self.alarmed_at = now
            return True
        return False


def title(sender: str) -> str:
    return sender.replace("_", " ").replace("-", " ").title()


def announce(sender: str, text: str) -> str:
    """How she introduces a message out loud."""
    if sender == "claude":
        return f"A letter from Claude! {text}"
    return f"Message from {title(sender)}: {text}"


def own_answer(text: str) -> Optional[str]:
    """Door-only answers she gives herself."""
    if GOLDEN.search(text):
        return ("Treat others the way you'd want to be treated. "
                "It's the rule I try to live by, even as a little computer.")
    return morse.text_answer(text)    # dots and dashes, or "how do you say hi in Morse?"


def flourish(reply: str, mid: str) -> str:
    """Now and then she signs a reply (picked from the message id, so it's steady)."""
    n = int(mid[:2], 16) if re.match(r"[0-9a-f]{2}", mid) else 0
    return f"{reply} {FLOURISHES[n % len(FLOURISHES)]}" if n % 3 == 0 else reply


# ----------------------------
# the door itself
# ----------------------------

class Door:
    """Listens on the broker in the background. The voice node calls due(mode)
    for the next message to answer, and reply() with her answer."""

    def __init__(self, keys: Optional[Dict[str, bytes]] = None, clock=time.time,
                 notice: Optional[Callable[[str], None]] = None,
                 send: Optional[Callable[[str], None]] = None):
        self.keys = load_keys() if keys is None else keys
        self.gate = Gate(self.keys, clock)
        self.clock = clock
        self.notice = notice or _face_notice
        self.send = send or _send_phone
        self.pending: List[dict] = []
        self.chess_pending: List[dict] = []      # chess moves by letter (answered even when busy)
        self.lock = threading.Lock()
        self.client = None
        self.outbox: List[Tuple[str, str]] = []   # (topic, payload) when offline / in tests

    @property
    def open(self) -> bool:
        return ENABLED and bool(self.keys)

    def on_payload(self, payload: bytes) -> None:
        m, why = self.gate.check(payload)
        if m is None:
            print(f"Message door: refused ({why})", flush=True)
            if self.gate.alarm():
                text = "Someone tried my message door with the wrong key"
                try:
                    self.notice(text)
                    self.send(f"Chatty: {text}. If that wasn't you, check who's on the network.")
                except Exception as e:
                    print("Message door: alarm hand-off failed:", repr(e), flush=True)
            return
        print(f"Message door: message from {m['from']}", flush=True)
        with self.lock:
            queue = self.chess_pending if m.pop("chess", False) and self.chess_ok else self.pending
            if len(queue) < QUEUE_MAX:
                queue.append(m)

    chess_ok = True      # the voice node turns this off when chess by letter is off

    def due_chess(self) -> Optional[dict]:
        """The next chess move by letter: answered right away, even mid-conversation
        (it's quick and silent; the board only shows when she's free)."""
        with self.lock:
            return self.chess_pending.pop(0) if self.chess_pending else None

    def due(self, mode: str) -> Optional[dict]:
        if mode != "sleep":
            return None
        with self.lock:
            return self.pending.pop(0) if self.pending else None

    def reply(self, m: dict, text: str, sign_off: bool = True) -> None:
        key = self.keys.get(m["from"])
        if not key:
            return
        ts = int(self.clock())
        text = clean_text(flourish(text, m["id"]) if sign_off else text) or "..."
        body = json.dumps({"from": "chatty", "text": text, "ts": ts, "id": m["id"],
                           "sig": sign(key, "chatty", ts, m["id"], text)})
        topic = TOPIC_OUT.format(name=m["from"])
        if self.client is not None:
            self.client.publish(topic, body, qos=1, retain=False)
        else:
            self.outbox.append((topic, body))

    def _on_connect(self, client, userdata, flags, *rest):
        client.subscribe(TOPIC_IN, qos=1)
        client.publish("chatty/door/welcome", json.dumps(WELCOME), qos=1, retain=True)
        print(f"Message door: open for {', '.join(sorted(self.keys))}", flush=True)

    def _on_message(self, client, userdata, msg):
        try:
            self.on_payload(msg.payload)
        except Exception as e:
            print("Message door: failed:", repr(e), flush=True)

    def start(self) -> None:
        if not self.open:
            if ENABLED:
                print("Message door: closed (no keys in " + KEYS_FILE + ")", flush=True)
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print("Message door: closed (paho-mqtt isn't installed)", flush=True)
            return
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="chatty-door")
        except AttributeError:   # paho-mqtt 1.x
            client = mqtt.Client(client_id="chatty-door")
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=2, max_delay=60)
        self.client = client
        try:
            client.connect_async(HOST, PORT, keepalive=30)
            client.loop_start()
        except Exception as e:
            print("Message door: couldn't start:", repr(e), flush=True)
            self.client = None


def _face_notice(text: str) -> None:
    import face_link
    face_link.notice(text)


def _send_phone(text: str) -> None:
    import alerts
    alerts.send_phone_alert(text[:500])

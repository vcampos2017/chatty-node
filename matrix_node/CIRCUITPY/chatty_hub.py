"""Finding Chatty's message board (MQTT broker) from a microcontroller.

The Pi nodes use broker_link.py, which leans on Tailscale and chatty-node.local.
The Matrix Portal's WiFi chip can do neither, so this is the small version:

  1. the address that worked last time,
  2. the home addresses Chatty told us about in her retained `chatty/hub` note
     ("lan" and "known": one per WiFi she has used),
  3. mqtt_hosts from secrets.py (her home address(es), comma-separated),
  4. her name ("chatty-node"), in case the router knows it.

Tailscale addresses (100.64.0.0/10) are skipped: the board can't reach them.
The note and the last good address are kept in the board's small memory (nvm),
so after a power cut it still knows where she might be. Pure Python: tested on a
computer.
"""
import json

DEFAULT_NAMES = ("chatty-node",)
MAGIC = b"CH1"
MAX_SAVE = 240


def _tailnet(addr):
    try:
        a, b = [int(x) for x in addr.split(".")[:2]]
    except ValueError:
        return False
    return a == 100 and 64 <= b <= 127


def split_hosts(text):
    if not text:
        return []
    if isinstance(text, (list, tuple)):
        items = text
    else:
        items = str(text).replace(";", ",").split(",")
    return [h.strip() for h in items if h and h.strip()]


def note_from(payload):
    """Chatty's chatty/hub note -> {"lan": [...], "known": [...]} (addresses only)."""
    try:
        body = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    lan = [str(a)[:40] for a in (body.get("lan") or []) if a][:3]
    known = body.get("known") or {}
    known = [str(a)[:40] for a in known.values() if a][:4] if isinstance(known, dict) else []
    return {"lan": lan, "known": known}


def to_try(last_good, note, configured):
    """The broker addresses to try, in order, no repeats, no Tailscale."""
    order = []
    if last_good:
        order.append(last_good)
    if note:
        order += note.get("lan") or []
        order += note.get("known") or []
    order += split_hosts(configured)
    order += list(DEFAULT_NAMES)
    out = []
    for host in order:
        if host and host not in out and not _tailnet(host):
            out.append(host)
    return out


def pack(last_good, note):
    """What to keep in nvm, as bytes (at most MAX_SAVE)."""
    body = {"last": last_good or "", "note": note or {}}
    raw = json.dumps(body).encode()
    while len(raw) + 5 > MAX_SAVE and body["note"].get("known"):
        body["note"]["known"] = body["note"]["known"][:-1]
        raw = json.dumps(body).encode()
    if len(raw) + 5 > MAX_SAVE:
        raw = json.dumps({"last": last_good or "", "note": {}}).encode()
    return MAGIC + bytes([len(raw) >> 8, len(raw) & 255]) + raw


def unpack(data):
    """bytes from nvm -> (last_good, note); (None, None) when empty or garbled."""
    try:
        data = bytes(data)
        if data[:3] != MAGIC:
            return None, None
        size = (data[3] << 8) | data[4]
        body = json.loads(data[5:5 + size].decode())
        return (body.get("last") or None), (body.get("note") or None)
    except (ValueError, IndexError, TypeError, AttributeError, UnicodeError):
        return None, None

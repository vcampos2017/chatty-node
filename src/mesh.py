"""
The node network: the other nodes check in with Chatty over MQTT.

Chatty's Pi runs a small MQTT broker (Mosquitto, installed by
scripts/install_mqtt.sh). Every node connects to it and posts:

    chatty/nodes/<name>/status   heartbeat, retained, about once a minute
                                 {"state": "online", "every": 60, "ts": 1730680000,
                                  "title": "Rain node"}
                                 Each node also leaves a "last will" with the broker:
                                 {"state": "offline"}. The broker posts it for the
                                 node the moment its connection drops.
    chatty/nodes/<name>/data     its latest readings, retained (any JSON)

Any node can subscribe to any other node's topics, so they can hear each other
(e.g. the word clock can listen to chatty/nodes/rain/data).

What Chatty does with it:
  - A node "goes quiet" when its last will arrives, or when it misses
    CHATTY_MESH_MISSES heartbeats in a row. She shows "Rain node went quiet" on
    her face (a notice, so never spoken, day or night).
  - If it is still quiet after CHATTY_MESH_PHONE_MINUTES, she sends one phone
    alert through IFTTT. When it comes back she shows "Rain node is back" (and
    tells the phone too, if she'd sent the quiet alert).
  - Nodes that were already quiet when Chatty started are noted silently, so a
    restart doesn't repeat old news.
  - "Hey Chatty, which nodes are online?" answers from here.
  - Chatty posts her own heartbeat as chatty/nodes/chatty/status.
  - She posts where to find her on chatty/hub (her WiFi, home and Tailscale
    addresses; hub_note.py), so the nodes can follow her when her WiFi keeper
    moves her to another network. Nodes say how they reached her ("via":
    "lan" or "tailscale"), and "which nodes are online?" mentions the
    Tailscale ones.

Nodes are still READ-ONLY: Chatty only listens, she never sends them commands.

Settings (in /etc/chatty/secrets.env):
    CHATTY_MQTT=0               turn this off (default on)
    CHATTY_MQTT_HOST            broker address (default localhost)
    CHATTY_MQTT_PORT            default 1883
    CHATTY_MESH_MISSES          missed heartbeats before a node is quiet (default 3)
    CHATTY_MESH_PHONE_MINUTES   minutes quiet before a phone alert (default 30, 0 = never)
    CHATTY_MESH_SCREEN=0        don't show quiet/back notices on the face
    IFTTT_KEY                   your IFTTT Webhooks key (shared with alerts.py)

Needs the paho-mqtt package (sudo apt install python3-paho-mqtt). Without it
Chatty runs as before and just prints that the node network is off.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import hub_note

ENABLED = os.getenv("CHATTY_MQTT", "1") != "0"
HOST = os.getenv("CHATTY_MQTT_HOST", "localhost").strip()
PORT = int(os.getenv("CHATTY_MQTT_PORT", "1883"))
MISSES = max(1, int(os.getenv("CHATTY_MESH_MISSES", "3")))
PHONE_MINUTES = float(os.getenv("CHATTY_MESH_PHONE_MINUTES", "30"))
SCREEN = os.getenv("CHATTY_MESH_SCREEN", "1") != "0"
PREFIX = "chatty/nodes"
SELF = "chatty"
EVERY = 60          # Chatty's own heartbeat, and the default for nodes that don't say


def title_for(name: str) -> str:
    """'rain' -> 'Rain node', 'rain-node' -> 'Rain node', 'wordclock' -> 'Wordclock node'."""
    words = name.replace("_", " ").replace("-", " ").split()
    if not words:
        return "A node"
    if words[-1].lower() != "node":
        words.append("node")
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def _clock_text(ts: float) -> str:
    d = time.localtime(ts)
    return f"{d.tm_hour % 12 or 12}:{d.tm_min:02d} {'AM' if d.tm_hour < 12 else 'PM'}"


@dataclass
class Node:
    name: str
    title: str
    online: bool = True
    last_seen: float = 0.0     # last heartbeat (or data) we got
    every: float = EVERY       # how often it says it checks in
    quiet_since: float = 0.0
    phoned: bool = False
    data: dict = field(default_factory=dict)
    data_ts: float = 0.0
    via: str = ""              # how it reached the board: "lan", "tailscale" or "" (didn't say)


class Tracker:
    """Keeps track of who's online. No networking in here, so it's easy to test:
    feed it messages with message(), call tick() now and then, and both return
    events: ("quiet", node), ("back", node) or ("phone", node). What it learns
    in the first message about a node (right after Chatty starts) is never an event."""

    def __init__(self, misses: int = MISSES, phone_minutes: float = PHONE_MINUTES):
        self.misses = misses
        self.phone_after = phone_minutes * 60
        self.nodes: Dict[str, Node] = {}
        self.lock = threading.Lock()

    @staticmethod
    def parse_topic(topic: str) -> Optional[Tuple[str, str]]:
        parts = topic.split("/")
        if len(parts) != 4 or "/".join(parts[:2]) != PREFIX or parts[3] not in ("status", "data"):
            return None
        return parts[2], parts[3]

    def _stale(self, n: Node, now: float) -> bool:
        return now - n.last_seen > self.misses * n.every

    def message(self, topic: str, payload: bytes, now: float) -> List[Tuple[str, Node]]:
        where = self.parse_topic(topic)
        if not where or where[0] == SELF:
            return []
        name, kind = where
        try:
            body = json.loads(payload.decode("utf-8", "ignore") or "{}")
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {"value": body}
        events = []
        with self.lock:
            first = name not in self.nodes
            n = self.nodes.get(name) or Node(name, title_for(name))
            self.nodes[name] = n
            if body.get("title"):
                n.title = str(body["title"])[:40]
            if kind == "data":
                n.data, n.data_ts = body, now
                if first:
                    n.online, n.last_seen = False, 0.0   # wait for a heartbeat
                    return []
                if not n.online:
                    return []   # old data replayed; only a heartbeat brings it back
                n.last_seen = max(n.last_seen, now)
                return []
            # status
            n.via = str(body.get("via") or "")[:20]
            try:
                n.every = max(5.0, float(body.get("every", n.every)))
            except (TypeError, ValueError):
                pass
            if str(body.get("state", "online")).lower() == "offline":
                if n.online or first:
                    n.online = False
                    n.phoned = False
                    # already quiet when Chatty started: note it, but don't alert
                    n.quiet_since = 0.0 if first else now
                    if not first:
                        events.append(("quiet", n))
                return events
            try:
                seen = float(body.get("ts", now))
            except (TypeError, ValueError):
                seen = now
            n.last_seen = min(seen, now)
            if first:
                n.online = not self._stale(n, now)
                return []          # first news after Chatty starts: no announcement
            if not n.online and not self._stale(n, now):
                n.online = True
                events.append(("back", n))
                n.quiet_since = 0.0
        return events

    def tick(self, now: float) -> List[Tuple[str, Node]]:
        events = []
        with self.lock:
            for n in self.nodes.values():
                if n.online and n.last_seen and self._stale(n, now):
                    n.online = False
                    n.quiet_since = now
                    n.phoned = False
                    events.append(("quiet", n))
                elif (not n.online and n.quiet_since and not n.phoned and self.phone_after > 0
                      and now - n.quiet_since >= self.phone_after):
                    n.phoned = True
                    events.append(("phone", n))
        return events

    # ----- for questions -----
    def summary(self) -> str:
        with self.lock:
            nodes = sorted(self.nodes.values(), key=lambda n: n.title)
        if not nodes:
            return "No other nodes have checked in with me yet."
        on = [n.title for n in nodes if n.online]
        off = [n for n in nodes if not n.online]
        far = [n.title for n in nodes if n.online and n.via == "tailscale"]
        parts = []
        if on:
            parts.append(_join(on) + (" is" if len(on) == 1 else " are") + " online")
        if far:
            parts.append(_join(far) + (" is" if len(far) == 1 else " are")
                         + " reaching me through Tailscale, since we're on different WiFi")
        for n in off:
            if n.last_seen:
                parts.append(f"{n.title} has been quiet since {_clock_text(n.last_seen)}")
            else:
                parts.append(f"{n.title} is quiet")
        return ". ".join(parts) + "."

    def latest(self, name: str, max_age: float = 600, now: Optional[float] = None) -> Optional[dict]:
        """The node's last readings if they're recent enough, else None."""
        now = time.time() if now is None else now
        with self.lock:
            n = self.nodes.get(name)
            if n and n.data and now - n.data_ts <= max_age:
                return dict(n.data)
        return None


def _join(items: List[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f", and {items[-1]}"


# ----------------------------
# what Chatty does with the events
# ----------------------------

def default_show(text: str) -> None:
    import face_link
    face_link.notice(text)


def default_send(text: str) -> None:
    import alerts
    alerts.send_phone_alert(text)


def handle(events, show: Callable[[str], None] = None, send: Callable[[str], None] = None) -> None:
    show = show or default_show
    send = send or default_send
    for kind, n in events:
        try:
            if kind == "quiet":
                print(f"Node network: {n.name} went quiet", flush=True)
                if SCREEN:
                    when = f" (last heard {_clock_text(n.last_seen)})" if n.last_seen else ""
                    show(f"{n.title} went quiet{when}")
            elif kind == "back":
                print(f"Node network: {n.name} is back", flush=True)
                if SCREEN:
                    show(f"{n.title} is back")
                if n.phoned:
                    send(f"Chatty: {n.title} is back online.")
                n.phoned = False
            elif kind == "phone":
                mins = int(PHONE_MINUTES)
                send(f"Chatty: {n.title} has been quiet for {mins} minutes. "
                     "It might be off WiFi or out of power.")
        except Exception as e:
            print("Node network hand-off failed:", repr(e), flush=True)


# ----------------------------
# the MQTT connection
# ----------------------------

def _status(state: str) -> str:
    return json.dumps({"state": state, "every": EVERY, "ts": int(time.time()),
                       "title": "Chatty", "host": socket.gethostname()})


class Mesh:
    """Connects to the broker in the background and keeps a Tracker up to date.
    Never raises: if MQTT isn't available Chatty just carries on without it."""

    def __init__(self, tracker: Optional[Tracker] = None, on_events=handle, clock=time.time,
                 on_data: Optional[Callable[[str, dict, float], None]] = None):
        self.tracker = tracker or Tracker()
        self.on_events = on_events
        self.on_data = on_data      # (node name, readings, now), e.g. sky.SkyWatch.on_data
        self.clock = clock
        self.client = None
        self.connected = False
        self.hub = None             # hub_note.HubNote, made in start()

    def _post_hub(self, force: bool = False) -> None:
        """Tell the nodes where to find her (chatty/hub), when it changed."""
        if self.hub is None or self.client is None:
            return
        try:
            body = self.hub.due(force)
            if body:
                self.client.publish(hub_note.TOPIC, json.dumps(body), qos=1, retain=True)
        except Exception as e:
            print("Node network: hub note failed:", repr(e), flush=True)

    def _on_connect(self, client, userdata, flags, *rest):
        self.connected = True
        print(f"Node network: connected to {HOST}:{PORT}", flush=True)
        client.subscribe(f"{PREFIX}/+/status", qos=1)
        client.subscribe(f"{PREFIX}/+/data", qos=1)
        client.publish(f"{PREFIX}/{SELF}/status", _status("online"), qos=1, retain=True)
        self._post_hub(force=True)

    def _on_disconnect(self, *args):
        if self.connected:
            print("Node network: lost the broker, retrying", flush=True)
        self.connected = False

    def _on_message(self, client, userdata, msg):
        now = self.clock()
        self._hand_off(self.tracker.message(msg.topic, msg.payload, now))
        where = Tracker.parse_topic(msg.topic)
        if self.on_data and where and where[1] == "data" and where[0] != SELF:
            try:
                body = json.loads(msg.payload.decode("utf-8", "ignore") or "{}")
                if isinstance(body, dict):
                    self.on_data(where[0], body, now)
            except Exception as e:
                print("Node network: reading hand-off failed:", repr(e), flush=True)

    def _hand_off(self, events):
        if events:
            try:
                self.on_events(events)
            except Exception as e:
                print("Node network hand-off failed:", repr(e), flush=True)

    def _loop(self):
        beats = 0
        while True:
            time.sleep(EVERY / 4)
            self._hand_off(self.tracker.tick(self.clock()))
            beats += 1
            if self.connected and beats % 4 == 0:
                self.client.publish(f"{PREFIX}/{SELF}/status", _status("online"), qos=1, retain=True)
                self._post_hub()

    def start(self) -> None:
        if not ENABLED:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print("Node network off: paho-mqtt isn't installed "
                  "(sudo apt install python3-paho-mqtt)", flush=True)
            return
        cid = f"chatty-{socket.gethostname()}"
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
        except AttributeError:   # paho-mqtt 1.x
            client = mqtt.Client(client_id=cid)
        client.will_set(f"{PREFIX}/{SELF}/status", json.dumps({"state": "offline"}), qos=1, retain=True)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=2, max_delay=60)
        self.client = client
        if hub_note.ENABLED:
            self.hub = hub_note.HubNote(port=PORT)
        try:
            client.connect_async(HOST, PORT, keepalive=30)
            client.loop_start()
        except Exception as e:
            print("Node network: couldn't start:", repr(e), flush=True)
            return
        threading.Thread(target=self._loop, daemon=True, name="mesh").start()

    def publish(self, topic: str, body: dict, retain: bool = True) -> bool:
        """Post Chatty's own news (e.g. the rain forecast) for the other nodes to read.
        Only news, never commands. False if the broker isn't connected right now."""
        if not self.connected or self.client is None:
            return False
        try:
            self.client.publish(topic, json.dumps(body), qos=1, retain=retain)
            return True
        except Exception as e:
            print("Node network: couldn't post", topic, repr(e), flush=True)
            return False

    def summary(self) -> str:
        if not ENABLED:
            return "The node network is turned off."
        if self.client is None:
            return "The node network isn't set up on me yet."
        text = self.tracker.summary()
        if not self.connected:
            text = "I can't reach my message board right now. Last I knew: " + text
        return text


if __name__ == "__main__":
    # On the Pi:  python3 src/mesh.py     (listens for 2 minutes and prints who checks in)
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from dotenv import load_dotenv
        load_dotenv("/etc/chatty/secrets.env")
    except ImportError:
        pass
    m = Mesh(on_events=lambda ev: [print(" event:", k, n.name) for k, n in ev])
    m.start()
    for _ in range(8):
        time.sleep(15)
        print(m.summary())

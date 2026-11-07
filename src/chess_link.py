"""
Chess over the node network: how Chatty finds a node to play and swaps moves.

Topics (on the same Mosquitto broker as mesh.py):
    chatty/chess/<node>/hello   retained, from a node that runs scripts/chess_peer.py:
                                {"plays": "chess", "style": "lightning", "ts": ...}
                                (last will {"plays": false} when it disconnects)
    chatty/chess/<node>/ask     from Chatty: {"game": "a1b2c3", "moves": ["e2e4", ...], "ts": ...}
                                "your move, here is the whole game so far"
    chatty/chess/<node>/move    from the node: {"game": "a1b2c3", "ply": 1, "move": "e7e5"}
    chatty/chess/<node>/result  from Chatty when a game ends: {"game", "result", "why"}

A node only joins in if someone installed chess_peer.py on it; it's never asked to
do anything else, and every move it sends is checked against the rules before it
is played (anything odd is ignored). Moves are the only thing taken from the
network; nothing a node sends is ever shown as text.

If the node has no player (or doesn't answer), Chatty plays its moves for it, in
its style, so a game never gets stuck.

Runs inside the face process. Needs paho-mqtt (already installed for mesh.py);
without it chess still works, she just plays both sides.
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from typing import Dict, List, Optional, Tuple

ENABLED = os.getenv("CHATTY_MQTT", "1") != "0"
HOST = os.getenv("CHATTY_MQTT_HOST", "localhost").strip()
PORT = int(os.getenv("CHATTY_MQTT_PORT", "1883"))
PREFIX = "chatty/chess"
NODES = "chatty/nodes"
SELF = "chatty"
FRESH = 600         # a heartbeat older than this doesn't count as online
_NAME_OK = re.compile(r"^[a-z0-9_-]{1,32}$")
_MOVE_OK = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")


class ChessLink:
    def __init__(self):
        self.lock = threading.Lock()
        self.online: Dict[str, float] = {}      # node -> when it last said "online"
        self.players: Dict[str, float] = {}     # node -> when its chess player said hello
        self.replies: Dict[str, Tuple[str, int, str]] = {}   # node -> (game, ply, move)
        self.client = None
        self.connected = False

    # ----- what Chatty asks -----
    def opponents(self, now: Optional[float] = None) -> List[str]:
        """Nodes that are online right now (nodes with a chess player first)."""
        now = now or time.time()
        with self.lock:
            names = {n for n, t in self.online.items() if now - t < FRESH} | set(self.players)
            return sorted(names, key=lambda n: (n not in self.players, n))

    def has_player(self, node: str) -> bool:
        with self.lock:
            return node in self.players and self.connected

    def ask(self, node: str, game: str, moves: List[str]) -> bool:
        with self.lock:
            self.replies.pop(node, None)
        return self._publish(f"{PREFIX}/{node}/ask", {"game": game, "moves": moves, "ts": int(time.time())})

    def reply(self, node: str, game: str, ply: int) -> Optional[str]:
        """The node's answer to our last ask, if it came (and matches this game and move)."""
        with self.lock:
            r = self.replies.get(node)
            if r and r[0] == game and r[1] == ply:
                del self.replies[node]
                return r[2]
        return None

    def result(self, node: str, game: str, result: str, why: str) -> None:
        self._publish(f"{PREFIX}/{node}/result", {"game": game, "result": result, "why": why})

    # ----- incoming -----
    def message(self, topic: str, payload: bytes, now: Optional[float] = None) -> None:
        """Feed one MQTT message in (also used by the tests)."""
        now = now or time.time()
        parts = topic.split("/")
        if len(parts) != 4 or not _NAME_OK.match(parts[2]) or parts[2] == SELF:
            return
        node, kind = parts[2], parts[3]
        try:
            body = json.loads(payload[:2000].decode("utf-8", "ignore") or "{}")
        except ValueError:
            return
        if not isinstance(body, dict):
            return
        with self.lock:
            if parts[0] + "/" + parts[1] == NODES and kind == "status":
                ts = body.get("ts")
                if body.get("state") == "online":
                    # a retained heartbeat can be old: go by the time the node wrote on it
                    self.online[node] = min(now, ts) if isinstance(ts, (int, float)) else now
                else:
                    self.online.pop(node, None)
            elif parts[0] + "/" + parts[1] == PREFIX and kind == "hello":
                if body.get("plays") == "chess":
                    self.players[node] = now
                else:
                    self.players.pop(node, None)
            elif parts[0] + "/" + parts[1] == PREFIX and kind == "move":
                move, game, ply = body.get("move"), body.get("game"), body.get("ply")
                if (isinstance(move, str) and _MOVE_OK.match(move) and isinstance(game, str)
                        and len(game) <= 16 and isinstance(ply, int)):
                    self.replies[node] = (game, ply, move)

    # ----- MQTT plumbing -----
    def _on_connect(self, client, userdata, flags, *rest):
        self.connected = True
        client.subscribe(f"{NODES}/+/status", qos=1)
        client.subscribe(f"{PREFIX}/+/hello", qos=1)
        client.subscribe(f"{PREFIX}/+/move", qos=1)

    def _on_disconnect(self, *args):
        self.connected = False

    def _on_message(self, client, userdata, msg):
        try:
            self.message(msg.topic, msg.payload)
        except Exception as e:  # never let a bad message stop the face
            print("Chess link: bad message ignored:", repr(e), flush=True)

    def _publish(self, topic: str, body: dict) -> bool:
        if not self.connected or self.client is None:
            return False
        try:
            self.client.publish(topic, json.dumps(body), qos=1, retain=False)
            return True
        except Exception:
            return False

    def start(self) -> "ChessLink":
        if not ENABLED:
            return self
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print("Chess: no paho-mqtt, so I'll play both sides myself", flush=True)
            return self
        cid = f"chatty-chess-{socket.gethostname()}"
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
        except AttributeError:   # paho-mqtt 1.x
            client = mqtt.Client(client_id=cid)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=5, max_delay=120)
        self.client = client
        try:
            client.connect_async(HOST, PORT, keepalive=60)
            client.loop_start()
        except Exception as e:
            print("Chess link: couldn't start:", repr(e), flush=True)
        return self

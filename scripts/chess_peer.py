#!/usr/bin/env python3
"""
A chess player for a node (Lightning, Rain, Greenhouse, the Word Clock...), so it can
play its own moves when Chatty challenges it. Optional: without it, Chatty simply
moves for the node.

It only does one thing: when Chatty posts "your move" on chatty/chess/<name>/ask,
it replays the game, thinks for a moment, and posts a move on chatty/chess/<name>/move.
It never runs anything it receives, it checks every move against the rules, and it
thinks at most once every few seconds with a small budget, at the lowest CPU
priority, so the node's real job always comes first.

Needs only Python 3 and paho-mqtt (python3-paho-mqtt), plus chess_engine.py in
the same folder (or in ../src).

Try it:   python3 chess_peer.py --name lightning --host chatty-node.local
Install:  bash install_chess_peer.sh lightning      (a small systemd service)
Options:  --style rain   (play like another node)    --budget 3000   (think less)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "src")]
import chess_engine as ce  # noqa: E402

PREFIX = "chatty/chess"
MAX_MOVES = 400            # a real game is far shorter; anything longer is ignored
MIN_GAP = 3.0              # think at most once every few seconds
_MOVE_OK = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
_GAME_OK = re.compile(r"^[0-9a-f]{1,16}$")


def answer(body: dict, style: str, rng: random.Random, budget: int):
    """The reply for one ask, or None if the ask doesn't make sense."""
    game, moves = body.get("game"), body.get("moves")
    if not (isinstance(game, str) and _GAME_OK.match(game) and isinstance(moves, list)
            and len(moves) <= MAX_MOVES and all(isinstance(m, str) and _MOVE_OK.match(m) for m in moves)):
        return None
    try:
        g = ce.Game(moves)
    except ValueError:
        return None
    if g.result()[0]:
        return None
    m = ce.best_move(g.pos, style, rng, g.seen, budget=budget)
    if m is None:
        return None
    return {"game": game, "ply": len(moves), "move": ce.to_uci(m)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=os.getenv("CHESS_NODE", socket.gethostname().replace("-node", "")))
    ap.add_argument("--host", default=os.getenv("MQTT_HOST", "chatty-node.local"))
    ap.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    ap.add_argument("--style", default=os.getenv("CHESS_STYLE", ""))
    ap.add_argument("--budget", type=int, default=int(os.getenv("CHESS_BUDGET", "4000")))
    args = ap.parse_args()
    name = re.sub(r"[^a-z0-9_-]", "", args.name.lower())[:32] or "node"
    style = args.style or name
    try:
        os.nice(19)        # the node's own job comes first
    except OSError:
        pass
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        sys.exit("Needs paho-mqtt: sudo apt install python3-paho-mqtt")

    rng = random.Random()
    latest = {"body": None}
    wake = threading.Event()
    hello = f"{PREFIX}/{name}/hello"

    def on_connect(client, userdata, flags, *rest):
        print(f"Chess player '{name}' ({style} style) connected to {args.host}", flush=True)
        client.subscribe(f"{PREFIX}/{name}/ask", qos=1)
        client.subscribe(f"{PREFIX}/{name}/result", qos=1)
        client.publish(hello, json.dumps({"plays": "chess", "style": style, "ts": int(time.time())}),
                       qos=1, retain=True)

    def on_message(client, userdata, msg):
        try:
            body = json.loads(msg.payload[:8000].decode("utf-8", "ignore"))
        except ValueError:
            return
        if not isinstance(body, dict):
            return
        if msg.topic.endswith("/result"):
            print("Game over:", body.get("result"), "-", body.get("why"), "- good game!", flush=True)
            return
        latest["body"] = body        # only the newest ask matters
        wake.set()

    cid = f"chess-{name}-{socket.gethostname()}"
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
    except AttributeError:   # paho-mqtt 1.x
        client = mqtt.Client(client_id=cid)
    client.will_set(hello, json.dumps({"plays": False}), qos=1, retain=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=5, max_delay=300)
    client.connect_async(args.host, args.port, keepalive=60)
    client.loop_start()

    last = 0.0
    while True:
        wake.wait()
        wake.clear()
        time.sleep(max(0.0, MIN_GAP - (time.time() - last)))
        body, latest["body"] = latest["body"], None
        if body is None:
            continue
        last = time.time()
        reply = answer(body, style, rng, args.budget)
        if reply:
            took = time.time() - last
            print(f"Move {reply['ply'] // 2 + 1}: {reply['move']} ({took:.1f}s)", flush=True)
            client.publish(f"{PREFIX}/{name}/move", json.dumps(reply), qos=1)


if __name__ == "__main__":
    main()

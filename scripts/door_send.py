#!/usr/bin/env python3
"""
Talk to Chatty through her message door (see src/door.py).

On Chatty's Pi, give someone a key (prints it once; keep it somewhere safe):
    sudo python3 scripts/door_send.py --add-sender claude

Take a key away:
    sudo python3 scripts/door_send.py --remove-sender claude

Send a message from any computer on the home network or Tailscale
(needs python3-paho-mqtt):
    python3 scripts/door_send.py --as claude --key-file ~/.chatty_door_key "Hi Chatty!"

It waits up to 90 seconds for her signed reply and prints it. The key is
never sent: only a signature made with it.
"""
import argparse
import json
import os
import stat
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import door  # noqa: E402
import privacy  # noqa: E402


def add_sender(name: str, path: str) -> None:
    name = name.lower()
    if not door.NAME_RE.match(name):
        sys.exit("Names are lowercase letters, numbers, - or _ (up to 24), starting with a letter.")
    keys = door.load_keys(path)
    if name in keys:
        sys.exit(f"{name} already has a key. Remove it first to make a new one.")
    key = door.new_key()
    existed = os.path.exists(path)
    with open(path, "a") as f:
        if not existed:
            f.write("# Chatty's message door keys: name hexkey. Keep this file private.\n")
        f.write(f"{name} {key}\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)          # 600: only Chatty's user
    owner = os.getenv("SUDO_USER")
    if os.geteuid() == 0 and owner:                        # run with sudo: hand it to pi
        import pwd
        pw = pwd.getpwnam(owner)
        os.chown(path, pw.pw_uid, pw.pw_gid)
    print(f"Added {name}. Their key (shown once, give it to them privately):\n\n{key}\n")
    print("Restart Chatty so she picks it up:  sudo systemctl restart chatty-voice")


def remove_sender(name: str, path: str) -> None:
    try:
        lines = open(path).read().splitlines()
    except OSError:
        sys.exit(f"No key file at {path}")
    keep = [l for l in lines if l.split()[:1] != [name.lower()]]
    if len(keep) == len(lines):
        sys.exit(f"{name} has no key.")
    with open(path, "w") as f:
        f.write("\n".join(keep) + "\n")
    print(f"Removed {name}. Restart Chatty:  sudo systemctl restart chatty-voice")


def send(sender: str, key_hex: str, text: str, host: str, port: int, wait: float) -> int:
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        sys.exit("Needs paho-mqtt: sudo apt install python3-paho-mqtt")
    key = bytes.fromhex(key_hex.strip())
    msg = door.make_message(key, sender.lower(), text)
    got = threading.Event()
    answer = {}

    def on_connect(client, userdata, flags, *rest):
        client.subscribe(door.TOPIC_OUT.format(name=sender.lower()), qos=1)
        client.publish(door.TOPIC_IN, json.dumps(msg), qos=1)

    def on_message(client, userdata, m):
        try:
            reply = json.loads(m.payload.decode("utf-8"))
        except ValueError:
            return
        if reply.get("id") != msg["id"]:
            return
        answer["ok"] = door.verify_reply(key, reply, msg["id"])
        answer["text"] = reply.get("text", "")
        got.set()

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, keepalive=30)
    client.loop_start()
    print(f"Sent to Chatty at {host}. Waiting for her answer...")
    ok = got.wait(wait)
    client.loop_stop()
    if not ok:
        print("No answer yet. She answers when she's free (not mid-conversation); "
              "check the key, the clock, and that the door is open in her log.")
        return 1
    if not answer["ok"]:
        print("Got a reply, but it isn't signed with your key, so it isn't from Chatty. Ignoring it.")
        return 2
    print(f"Chatty: {answer['text']}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Chatty's message door")
    p.add_argument("text", nargs="?", help="the message")
    p.add_argument("--as", dest="sender", help="your sender name")
    p.add_argument("--key", help="your key (hex)")
    p.add_argument("--key-file", help="a file holding your key")
    p.add_argument("--host", default=os.getenv("CHATTY_MQTT_HOST", "chatty-node"))
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--wait", type=float, default=90)
    p.add_argument("--yes", action="store_true", help="send even if it looks private")
    p.add_argument("--add-sender", metavar="NAME")
    p.add_argument("--remove-sender", metavar="NAME")
    p.add_argument("--keys-file", default=door.KEYS_FILE, help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.add_sender:
        return add_sender(a.add_sender, a.keys_file)
    if a.remove_sender:
        return remove_sender(a.remove_sender, a.keys_file)
    if not (a.sender and a.text and (a.key or a.key_file)):
        p.error("to send: --as NAME, --key or --key-file, and the message")
    private = privacy.find(a.text)
    if private and not a.yes:
        warn = (f"This message looks like it has {privacy.describe(private)} in it. "
                "The door isn't encrypted, so others on your network could read it.")
        if not sys.stdin.isatty():
            sys.exit(warn + " Not sent (add --yes to send anyway).")
        if input(warn + " Send anyway? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Okay, not sent.")
    key = a.key or open(os.path.expanduser(a.key_file)).read()
    sys.exit(send(a.sender, key, a.text, a.host, a.port, a.wait))


if __name__ == "__main__":
    main()

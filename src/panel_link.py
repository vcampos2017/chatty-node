"""
The remote panel's side of Chatty's voice node (see panel.py for the web page).

The panel is a small web page on Chatty's Pi, so Vincent can check on her and
ask her things from his phone or desktop without touching her face. The web
server (panel.py) and the voice node are separate processes; they talk in two
small ways, both on the Pi itself:

  voice node -> panel:  a status file, STATUS_FILE (/dev/shm, owner-only 600),
                        written every couple of seconds: her mode, the last few
                        lines said, the nodes, timers, the rain outlook, and a
                        random token made fresh each time she starts.
  panel -> voice node:  UDP messages on 127.0.0.1:47475 (the same port the face
                        uses for "wake"/"rest"), each carrying that token:
                            panel:<token>:ask:<text>     ask her, she answers out loud
                            panel:<token>:hush:<text>    ask her quietly (answer on the panel only)
                            panel:<token>:say:<text>     she says these words
                            panel:<token>:wake | rest | yes | no
                        Only a process that can read her owner-only status file
                        knows the token, so other programs can't send her commands.

Privacy: the lines shown on the panel stay in memory (and the /dev/shm file,
which is gone at reboot). Spoken conversations are only included when her log
mode is "full"; with "private" or "off" only what was asked from the panel
(and her answers to it) shows up.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from contextlib import contextmanager
from typing import Callable, List, Optional, Tuple

STATUS_FILE = os.getenv("CHATTY_PANEL_STATUS", "/dev/shm/chatty_panel.json")
VOICE_PORT = int(os.getenv("CHATTY_VOICE_PORT", "47475"))
KINDS = ("ask", "hush", "say", "wake", "rest", "yes", "no")
WITH_TEXT = ("ask", "hush", "say")
MAX_TEXT = 300
MAX_LINES = 14
MAX_WAITING = 5
WAIT_SECONDS = 60          # a request she couldn't get to in a minute is dropped
WRITE_EVERY = 2.0


def build(token: str, kind: str, text: str = "") -> str:
    """The UDP message for one request (used by panel.py)."""
    text = " ".join((text or "").split())[:MAX_TEXT]
    return f"panel:{token}:{kind}" + (f":{text}" if kind in WITH_TEXT else "")


class Panel:
    """Kept by the voice node: requests from the panel, the recent lines, the status file."""

    def __init__(self, path: str = STATUS_FILE, clock: Callable[[], float] = time.time,
                 log_mode: Callable[[], str] = lambda: "full"):
        self.path = path
        self.clock = clock
        self.log_mode = log_mode
        self.token = secrets.token_hex(16)
        self.waiting: List[Tuple[float, str, str]] = []   # (when, kind, text)
        self.lines: List[dict] = []
        self.hush = False            # True while answering a quiet question: no speaking
        self.from_panel = False      # True while handling something asked from the panel
        self.last_quiet = False      # the last panel question was quiet (for its yes/no)
        self.written_at = 0.0

    # ----- requests -----
    def take(self, msg: str) -> bool:
        """A UDP message: True if it was a (good) panel request, now waiting."""
        parts = msg.split(":", 3)
        if len(parts) < 3 or parts[0] != "panel":
            return False
        token, kind = parts[1], parts[2].strip().lower()
        if not secrets.compare_digest(token, self.token) or kind not in KINDS:
            print("Panel: ignored a message without the right token", flush=True)
            return False
        text = " ".join(parts[3].split())[:MAX_TEXT] if len(parts) > 3 else ""
        if kind in WITH_TEXT and not text:
            return False
        if len(self.waiting) >= MAX_WAITING:
            return False
        self.waiting.append((self.clock(), kind, text))
        return True

    def next(self, mode: str) -> Optional[Tuple[str, str]]:
        """The next request she can handle in this mode, as (kind, text), or None.
        While she waits for a yes or no, only yes/no/rest go through; the rest wait."""
        now = self.clock()
        self.waiting = [w for w in self.waiting if now - w[0] < WAIT_SECONDS]
        for i, (_, kind, text) in enumerate(self.waiting):
            if mode == "confirm" and kind not in ("yes", "no", "rest"):
                continue
            if mode != "confirm" and kind in ("yes", "no"):
                del self.waiting[i]          # nothing to say yes to any more
                return self.next(mode)
            del self.waiting[i]
            return kind, text
        return None

    @contextmanager
    def turn(self, quiet: bool = False):
        """While handling a panel request: lines are kept, and quiet means no speaking."""
        self.from_panel, self.hush = True, quiet
        self.last_quiet = quiet
        try:
            yield
        finally:
            self.from_panel = self.hush = False

    # ----- what was said -----
    def _keep(self) -> bool:
        return self.from_panel or self.log_mode() == "full"

    def _add(self, who: str, text: str) -> None:
        text = " ".join((text or "").split())[:MAX_TEXT]
        if not text or not self._keep():
            return
        self.lines.append({"who": who, "text": text, "ts": int(self.clock()),
                           "panel": self.from_panel})
        del self.lines[:-MAX_LINES]

    def heard(self, text: str) -> None:
        self._add("you", text)

    def said(self, text: str) -> None:
        self._add("chatty", text)

    # ----- the status file -----
    def write(self, mode: str, extra: Optional[dict] = None, force: bool = False) -> bool:
        """Write the status file (at most every WRITE_EVERY seconds unless forced)."""
        now = self.clock()
        if not force and now - self.written_at < WRITE_EVERY:
            return False
        self.written_at = now
        body = {"token": self.token, "ts": now, "pid": os.getpid(), "mode": mode,
                "hush": self.hush, "waiting": len(self.waiting),
                "lines": self.lines if self.log_mode() == "full"
                else [x for x in self.lines if x.get("panel")]}
        body.update(extra or {})
        tmp = self.path + ".tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(body, f, default=str)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            print("Panel: couldn't write the status file:", repr(e), flush=True)
            return False


def node_list(tracker) -> List[dict]:
    """The node network as plain data (mesh.Tracker -> list of dicts)."""
    out = []
    try:
        with tracker.lock:
            nodes = sorted(tracker.nodes.values(), key=lambda n: n.title)
            for n in nodes:
                out.append({"name": n.name, "title": n.title, "online": n.online,
                            "last_seen": n.last_seen, "quiet_since": n.quiet_since,
                            "data": n.data, "data_ts": n.data_ts})
    except Exception:
        pass
    return out


def timer_list(clock_timers) -> List[dict]:
    try:
        with clock_timers.lock:
            return [{"kind": i["kind"], "end": i["end"], "label": i.get("label", "")}
                    for i in clock_timers.items]
    except Exception:
        return []


def rain_outlook(rain_ahead) -> Optional[dict]:
    o = getattr(rain_ahead, "latest", None)
    if o is None:
        return None
    return {"starts": o.starts, "chance": o.chance, "kind": o.kind, "summary": o.summary}

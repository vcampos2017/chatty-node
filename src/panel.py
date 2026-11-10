"""
Chatty's remote panel: a small web page on her Pi, so you can check on her and
ask her things from a phone or computer without touching her face.

    http://chatty-node:8080        (over Tailscale, from anywhere)
    http://<her home WiFi address>:8080

What it shows: what she's doing (asleep, resting, talking, waiting for a yes),
a picture of her screen with its notices, the last few things said, her health
(temperature, power, disk, memory, Ollama), the WiFi, the other nodes, timers,
the rain outlook and her services.

What it can do: ask her a question out loud or quietly (the answer only shows on
the panel), have her say something, the everyday questions as buttons (morning
briefing, weather, rain, nodes, how she's feeling, timers), wake her or put her
to bed, start a doodle / chess / pondering or stop it, clear the notices, leave
a note on her screen, set the screen brightness for a while, and restart her
voice or face service. Never anything on the other nodes (they stay read-only).

Safety (it's only for Vincent):
  - Only answers computers on the home network or Tailscale (and the Pi itself);
    anything else gets "403". CHATTY_PANEL_ALLOW=tailscale allows Tailscale only.
  - A passcode, kept as a salted PBKDF2 hash in /etc/chatty/panel_key (pi, 600).
    Log in once per browser; the cookie lasts CHATTY_PANEL_DAYS (30) days,
    is HttpOnly and SameSite=Strict, and every button also sends a header a
    stranger's web page can't, so other sites can't press her buttons.
    A new passcode logs every browser out.
  - 5 wrong passcodes in 10 minutes from one computer (or 10 overall) lock the
    door for 10 minutes and put a notice on her face (plus one phone alert).
  - Questions go through the same path as spoken ones: "shut down" still asks
    "are you sure?" first, and the privacy checker still asks before anything
    private-sounding goes to the cloud. The panel itself sends nothing anywhere.
  - Plain HTTP: over Tailscale that's encrypted anyway (WireGuard); on home
    WiFi it isn't, so use Tailscale away from home.

Settings (in /etc/chatty/secrets.env):
    CHATTY_PANEL_PORT     web port (default 8080)
    CHATTY_PANEL_ALLOW    home (home network + Tailscale, default) or tailscale
    CHATTY_PANEL_DAYS     how long a login lasts (default 30)
    CHATTY_PANEL_KEY_FILE passcode file (default /etc/chatty/panel_key)

Set up once on the Pi:   bash scripts/install_panel.sh
New passcode:            python3 src/panel.py --new-passcode   (or --set-passcode to pick one)
Try it by hand:          python3 src/panel.py
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(__file__))
import panel_link  # noqa: E402

PORT = int(os.getenv("CHATTY_PANEL_PORT", "8080"))
ALLOW = os.getenv("CHATTY_PANEL_ALLOW", "home").strip().lower()
DAYS = float(os.getenv("CHATTY_PANEL_DAYS", "30"))
KEY_FILE = os.getenv("CHATTY_PANEL_KEY_FILE", "/etc/chatty/panel_key")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_web")
FACE_PORT = int(os.getenv("CHATTY_FACE_PORT", "47474"))
SNAP_PNG = os.getenv("CHATTY_FACE_SNAP", "/dev/shm/chatty_face.png")
SNAP_JSON = os.path.splitext(SNAP_PNG)[0] + ".json"
WIFI_FILE = "/run/chatty-wifi.json"
COOKIE = "chatty_panel"
HEADER = "X-Chatty-Panel"           # every button sends it; other web sites can't
ITERATIONS = 200_000
MAX_BODY = 4096
FAILS_PER_HOST, FAILS_ALL, FAIL_WINDOW, LOCK_SECONDS = 5, 10, 600, 600
STALE_VOICE = 20                    # status file older than this: her voice service isn't running
SERVICES = ["chatty-voice", "chatty-face", "chatty-wifi", "chatty-ssh-announce",
            "mosquitto", "ollama"]
RESTARTABLE = {"voice": "chatty-voice", "face": "chatty-face"}
SYSTEMCTL = "/usr/bin/systemctl"

TAILSCALE = [ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48")]
HOME = [ipaddress.ip_network(n) for n in
        ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "fc00::/7", "fe80::/10")]
LOCAL = [ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128")]

WORDS = ("acorn amber apple aspen badge basil beach berry birch bloom brook bunny cabin candle "
         "canyon cedar cherry cider clover cloud cocoa comet coral cozy daisy dawn delta dune "
         "ember fable fern fiddle finch firefly flute forest fox frost garden ginger glow gold "
         "harbor hazel heron honey island ivy jade jelly kettle kite koala lake lantern lemon "
         "lilac lily lotus lucky maple marble meadow melon mint misty moon moss nectar noodle "
         "oak ocean olive orbit otter owl panda peach pebble pepper pine planet plum pond "
         "poppy puffin quilt rain raven ribbon river robin rose ruby sage sail seed shell sky "
         "sparrow spruce star stone sugar summer sunny swan tea thistle tide tiger tulip "
         "velvet violet walnut willow wren yarrow zephyr").split()


# ----------------------------------------------------------------------------
# who may knock
# ----------------------------------------------------------------------------
def allowed(addr: str, allow: str = ALLOW) -> bool:
    """Is this client on the Pi itself, Tailscale, or (unless allow == 'tailscale') the home network?"""
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    nets = LOCAL + TAILSCALE + ([] if allow == "tailscale" else HOME)
    return any(ip in n for n in nets if n.version == ip.version)


# ----------------------------------------------------------------------------
# the passcode and logins
# ----------------------------------------------------------------------------
def new_passcode(rng=secrets) -> str:
    """Four friendly words and a number, e.g. 'otter-maple-comet-sage-42' (easy to type on a phone)."""
    return "-".join(rng.choice(WORDS) for _ in range(4)) + f"-{rng.randbelow(90) + 10}"


def _hash(passcode: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    clean = " ".join(passcode.strip().lower().split())
    return hashlib.pbkdf2_hmac("sha256", clean.encode("utf-8"), salt, iterations)


def make_key(passcode: str) -> dict:
    salt = secrets.token_bytes(16)
    return {"salt": salt.hex(), "hash": _hash(passcode, salt).hex(), "iterations": ITERATIONS,
            "secret": secrets.token_hex(32), "made": int(time.time())}


def save_key(key: dict, path: str = KEY_FILE) -> None:
    """Write in place (the folder belongs to root; the file to pi, mode 600)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(key, f)
    os.chmod(path, 0o600)


def load_key(path: str = KEY_FILE) -> Optional[dict]:
    try:
        with open(path) as f:
            key = json.load(f)
        if all(k in key for k in ("salt", "hash", "secret")):
            return key
    except (OSError, ValueError):
        pass
    return None


class Doorman:
    """Checks passcodes and cookies, and counts wrong guesses. No networking (easy to test)."""

    def __init__(self, key: Optional[dict], clock: Callable[[], float] = time.time,
                 alarm: Optional[Callable[[str], None]] = None, days: float = DAYS):
        self.key = key
        self.clock = clock
        self.alarm = alarm or (lambda text: None)
        self.days = days
        self.fails: Dict[str, List[float]] = {}
        self.locked_until: Dict[str, float] = {}
        self.lock = threading.Lock()

    def _recent(self, host: str, now: float) -> List[float]:
        return [t for t in self.fails.get(host, []) if now - t < FAIL_WINDOW]

    def locked(self, host: str) -> float:
        """Seconds until this computer may try again (0 = it may)."""
        now = self.clock()
        return max(0.0, self.locked_until.get(host, 0.0) - now, self.locked_until.get("*", 0.0) - now)

    def login(self, host: str, passcode: str) -> Tuple[bool, str]:
        """(True, cookie value) for the right passcode; (False, reason) otherwise."""
        if not self.key:
            return False, "no passcode set yet: run python3 src/panel.py --new-passcode on the Pi"
        with self.lock:
            if self.locked(host):
                return False, "too many wrong tries: wait a few minutes"
            now = self.clock()
            salt = bytes.fromhex(self.key["salt"])
            good = hmac.compare_digest(
                _hash(passcode or "", salt, int(self.key.get("iterations", ITERATIONS))).hex(),
                self.key["hash"])
            if good:
                self.fails.pop(host, None)
                return True, self.cookie(now)
            self.fails[host] = self._recent(host, now) + [now]
            everyone = sum(len(self._recent(h, now)) for h in self.fails)
            if len(self.fails[host]) >= FAILS_PER_HOST or everyone >= FAILS_ALL:
                self.locked_until["*" if everyone >= FAILS_ALL else host] = now + LOCK_SECONDS
                self.fails.pop(host, None)
                self.alarm(f"Someone keeps typing the wrong panel passcode (from {host}). "
                           "I locked the panel for 10 minutes.")
            return False, "that's not the passcode"

    def cookie(self, now: Optional[float] = None) -> str:
        until = int((now or self.clock()) + self.days * 86400)
        return f"{until}.{self._sign(str(until))}"

    def _sign(self, text: str) -> str:
        return hmac.new(bytes.fromhex(self.key["secret"]), text.encode(), hashlib.sha256).hexdigest()

    def welcome(self, cookie: Optional[str]) -> bool:
        if not self.key or not cookie or "." not in cookie:
            return False
        until, _, sig = cookie.partition(".")
        if not until.isdigit() or int(until) < self.clock():
            return False
        return hmac.compare_digest(sig, self._sign(until))


# ----------------------------------------------------------------------------
# what she's up to
# ----------------------------------------------------------------------------
def read_json(path: str) -> Optional[dict]:
    try:
        with open(path) as f:
            body = json.load(f)
        return body if isinstance(body, dict) else None
    except (OSError, ValueError):
        return None


MODES = {"sleep": "Awake, waiting for her name", "active": "Listening",
         "resting": "Resting (a tap or the panel wakes her)", "confirm": "Waiting for a yes or no"}


def service_states(names: List[str] = SERVICES, run=subprocess.run) -> Dict[str, str]:
    try:
        r = run([SYSTEMCTL, "is-active", *names], capture_output=True, text=True, timeout=5)
        states = r.stdout.split()
    except (OSError, subprocess.SubprocessError):
        states = []
    return {n: (states[i] if i < len(states) else "unknown") for i, n in enumerate(names)}


def health() -> dict:
    try:
        import self_care
        r = self_care.read_all()
    except Exception as e:
        return {"error": repr(e)}
    disk = r.get("disk")
    out = {"temp": r.get("temp"), "throttled": r.get("throttled"), "mem_mb": r.get("mem_mb"),
           "ollama": r.get("ollama")}
    if disk:
        free, total = disk
        out["disk_free_gb"] = round(free / 1e9, 1)
        out["disk_used_pct"] = round(100 * (1 - free / total), 1) if total else None
    try:
        with open("/proc/uptime") as f:
            out["uptime"] = float(f.read().split()[0])
    except (OSError, ValueError):
        pass
    return out


class Cache:
    """Keeps slow readings (services, health) for a few seconds."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.items: Dict[str, Tuple[float, object]] = {}
        self.lock = threading.Lock()

    def get(self, name: str, seconds: float, make: Callable[[], object]):
        with self.lock:
            hit = self.items.get(name)
            if hit and self.clock() - hit[0] < seconds:
                return hit[1]
        value = make()
        with self.lock:
            self.items[name] = (self.clock(), value)
        return value


def status(cache: Cache, voice_file: str = panel_link.STATUS_FILE, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    voice = read_json(voice_file) or {}
    voice.pop("token", None)                     # never leaves the Pi
    voice_ok = bool(voice) and now - float(voice.get("ts", 0)) < STALE_VOICE
    mode = voice.get("mode", "")
    face = read_json(SNAP_JSON) or {}
    return {
        "now": now, "voice_ok": voice_ok, "mode": mode,
        "mode_text": MODES.get(mode, "") if voice_ok else "Her voice service isn't answering",
        "voice": voice, "face": face,
        "services": cache.get("services", 5, service_states),
        "health": cache.get("health", 20, health),
        "wifi": read_json(WIFI_FILE),
        "host": socket.gethostname(),
    }


# ----------------------------------------------------------------------------
# pressing her buttons
# ----------------------------------------------------------------------------
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def to_face(msg: str) -> None:
    try:
        _sock.sendto(msg.encode("utf-8")[:1000], ("127.0.0.1", FACE_PORT))
    except OSError:
        pass


def to_voice(kind: str, text: str = "", voice_file: str = panel_link.STATUS_FILE) -> bool:
    voice = read_json(voice_file) or {}
    token = voice.get("token")
    if not token or time.time() - float(voice.get("ts", 0)) > STALE_VOICE:
        return False
    try:
        _sock.sendto(panel_link.build(token, kind, text).encode("utf-8")[:1000],
                     ("127.0.0.1", panel_link.VOICE_PORT))
        return True
    except OSError:
        return False


FACE_THINGS = {"doodle", "doodle:spiro", "doodle:stars", "doodle:rain", "imagine", "chess", "chess:lightning",
               "chess:rain", "chess:greenhouse", "chess:wordclock", "ponder", "play", "calm",
               "notices:clear", "trickster", "trickster:meeting", "trickster:vote:lightning",
               "trickster:vote:rain", "trickster:vote:greenhouse", "trickster:vote:wordclock"}


def restart(service: str, run=subprocess.run) -> Tuple[bool, str]:
    unit = RESTARTABLE.get(service)
    if not unit:
        return False, "I can only restart her voice or her face"
    try:
        r = run(["sudo", "-n", SYSTEMCTL, "restart", unit], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return False, repr(e)
    if r.returncode != 0:
        return False, (r.stderr.strip() or "not allowed") + " (run scripts/install_panel.sh again)"
    return True, f"Restarted {unit}"


def do(body: dict, voice=to_voice, face=to_face, run=subprocess.run) -> Tuple[bool, str]:
    """One button press: (worked, what to show)."""
    action = str(body.get("action", ""))
    text = " ".join(str(body.get("text", "")).split())[:panel_link.MAX_TEXT]
    if action in ("ask", "hush", "say"):
        if not text:
            return False, "Type something first"
        if voice(action, text):
            return True, {"ask": "Asked her", "hush": "Asked her quietly",
                          "say": "She's saying it"}[action]
        return False, "Her voice service isn't answering"
    if action in ("wake", "rest", "yes", "no"):
        return (True, "Sent") if voice(action) else (False, "Her voice service isn't answering")
    if action == "face":
        what = str(body.get("what", ""))
        if what not in FACE_THINGS:
            return False, "Unknown face action"
        face(what)
        return True, "Sent to her face"
    if action == "note":
        if not text:
            return False, "Type a note first"
        face(f"notice:{text}")
        return True, "Note left on her screen"
    if action == "light":
        level = body.get("level")
        if level == "auto":
            face("light:auto")
            return True, "Screen back to automatic"
        try:
            level = max(0.02, min(1.0, float(level)))
        except (TypeError, ValueError):
            return False, "Pick a brightness"
        face(f"light:{level:.2f}")
        return True, f"Screen at {round(level * 100)}% for a while"
    if action == "restart":
        return restart(str(body.get("service", "")), run=run)
    return False, "Unknown button"


def snapshot(wait: float = 2.0) -> Optional[bytes]:
    """Ask the face for a fresh picture of the screen; the last one if it's slow."""
    try:
        before = os.path.getmtime(SNAP_PNG)
    except OSError:
        before = 0.0
    if time.time() - before > 2:
        to_face("snap")
        end = time.time() + wait
        while time.time() < end:
            time.sleep(0.1)
            try:
                if os.path.getmtime(SNAP_PNG) > before:
                    time.sleep(0.05)
                    break
            except OSError:
                pass
    try:
        with open(SNAP_PNG, "rb") as f:
            return f.read()
    except OSError:
        return None


# ----------------------------------------------------------------------------
# the web server
# ----------------------------------------------------------------------------
STATIC = {"/": "index.html", "/panel.js": "panel.js", "/panel.css": "panel.css",
          "/icon.svg": "icon.svg", "/manifest.json": "manifest.json"}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; "
                               "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
}


def face_alarm(text: str) -> None:
    print("Panel:", text, flush=True)
    to_face(f"notice:{text}")
    try:
        import alerts
        alerts.send_phone_alert(text + " Requesting your assistance, please.")
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "ChattyPanel"
    sys_version = ""
    doorman: Doorman = None
    cache: Cache = None
    allow = ALLOW

    def log_message(self, fmt, *args):   # no request log lines (they'd fill the journal)
        pass

    # ----- helpers -----
    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, body: dict, extra: Optional[dict] = None):
        self._send(code, json.dumps(body, default=str).encode(), "application/json", extra)

    def _client(self) -> str:
        return self.client_address[0]

    def _cookie(self) -> Optional[str]:
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE:
                return value
        return None

    def _gate(self) -> bool:
        if not allowed(self._client(), self.allow):
            self._send(403, b"Chatty's panel is only for her home network and Tailscale.\n",
                       "text/plain; charset=utf-8")
            return False
        return True

    def _logged_in(self) -> bool:
        return self.doorman.welcome(self._cookie())

    def _body(self) -> Optional[dict]:
        if self.headers.get(HEADER) != "1" or \
                not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self._json(400, {"ok": False, "message": "Not from the panel"})
            return None
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            self._json(413, {"ok": False, "message": "Too long"})
            return None
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            if isinstance(body, dict):
                return body
        except (ValueError, UnicodeDecodeError):
            pass
        self._json(400, {"ok": False, "message": "Bad request"})
        return None

    # ----- requests -----
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._gate():
            return
        path = urlparse(self.path).path
        if path in STATIC:
            name = STATIC[path]
            try:
                with open(os.path.join(WEB_DIR, name), "rb") as f:
                    data = f.read()
            except OSError:
                return self._send(404, b"missing", "text/plain")
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            return self._send(200, data, ctype)
        if not self._logged_in():
            return self._json(401, {"ok": False, "login": True,
                                    "has_key": bool(self.doorman.key)})
        if path == "/api/status":
            return self._json(200, {"ok": True, **status(self.cache)})
        if path == "/api/face.png":
            png = snapshot()
            if png is None:
                return self._send(404, b"no picture yet", "text/plain")
            return self._send(200, png, "image/png")
        self._send(404, b"not here", "text/plain")

    def do_POST(self):
        if not self._gate():
            return
        path = urlparse(self.path).path
        body = self._body()
        if body is None:
            return
        if path == "/api/login":
            ok, value = self.doorman.login(self._client(), str(body.get("passcode", ""))[:200])
            if not ok:
                time.sleep(1.0)            # slows guessing down a little more
                return self._json(403, {"ok": False, "message": value})
            print(f"Panel: logged in from {self._client()}", flush=True)
            cookie = (f"{COOKIE}={value}; Max-Age={int(self.doorman.days * 86400)}; Path=/; "
                      "HttpOnly; SameSite=Strict")
            return self._json(200, {"ok": True}, {"Set-Cookie": cookie})
        if path == "/api/logout":
            return self._json(200, {"ok": True},
                              {"Set-Cookie": f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict"})
        if not self._logged_in():
            return self._json(401, {"ok": False, "login": True})
        if path == "/api/do":
            ok, message = do(body)
            print(f"Panel: {body.get('action')} {body.get('what') or body.get('service') or ''}"
                  f" -> {message}", flush=True)
            return self._json(200 if ok else 409, {"ok": ok, "message": message})
        self._json(404, {"ok": False, "message": "not here"})


class DualStackServer(ThreadingHTTPServer):
    daemon_threads = True
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (OSError, AttributeError):
            pass
        super().server_bind()


def serve(port: int = PORT) -> None:
    key = load_key()
    if not key:
        print(f"Panel: no passcode yet ({KEY_FILE}). Run: python3 src/panel.py --new-passcode", flush=True)
    Handler.doorman = Doorman(key, alarm=face_alarm)
    Handler.cache = Cache()
    try:
        httpd = DualStackServer(("::", port), Handler)
    except OSError:
        ThreadingHTTPServer.daemon_threads = True
        httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Chatty's panel is open on port {port} ({'Tailscale only' if ALLOW == 'tailscale' else 'home network + Tailscale'})",
          flush=True)
    httpd.serve_forever()


def _write_new_key(passcode: str) -> None:
    try:
        save_key(make_key(passcode))
    except PermissionError:
        print(f"Can't write {KEY_FILE}. Run: bash scripts/install_panel.sh (it makes the file for you)")
        raise SystemExit(1)


def main(argv: List[str]) -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv("/etc/chatty/secrets.env")
    except Exception:
        pass
    if "--new-passcode" in argv:
        code = new_passcode()
        _write_new_key(code)
        print("Chatty's panel passcode is:\n")
        print("    " + code + "\n")
        print("Write it down somewhere safe (not in a chat). Browsers that were logged in")
        print("need it again. Restart the panel: sudo systemctl restart chatty-panel")
        return
    if "--set-passcode" in argv:
        import getpass
        code = getpass.getpass("New panel passcode (8+ characters): ")
        if len(code.strip()) < 8 or getpass.getpass("Again: ") != code:
            print("Not changed: too short, or the two didn't match.")
            raise SystemExit(1)
        _write_new_key(code)
        print("Saved. Restart the panel: sudo systemctl restart chatty-panel")
        return
    serve()


if __name__ == "__main__":
    main(sys.argv[1:])

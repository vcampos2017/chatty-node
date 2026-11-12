"""
Homecoming: "Welcome home, Vincent!"

Chatty notices when your phone comes back onto the home WiFi and says hello.
Everything happens on the Pi, on your own network: no cloud, no app on the phone,
no location service.

How she knows the phone is home
  Every phone on the WiFi has a hardware ("MAC") address. You tell Chatty yours,
  and every CHATTY_HOME_EVERY seconds she knocks gently on the phone's last known
  address (one tiny UDP packet to port 5353, the "nearby devices" port) and looks
  at the Pi's neighbor table (`ip neigh`, the same one the Pi uses to talk to the
  router). If the phone answered the network's "who has this address?" question,
  it's home. Sleeping iPhones still answer those (the WiFi chip does it for them),
  which is why this works better than ping. Every CHATTY_HOME_SWEEP seconds while
  someone is away she knocks on the whole home subnet once, in case the phone got
  a new IP address. No root needed, nothing is installed on the phone.

  iPhones use a "Private Wi-Fi Address" (one per WiFi network). Find it on the
  phone: Settings > Wi-Fi > tap (i) next to your home network > "Wi-Fi Address".
  Leave "Private Wi-Fi Address" set to "Fixed" (iOS 18; older iOS: just On), not
  "Rotating", or the address changes now and then. A phone that joins two home
  networks has two addresses: list both.

When she says hello
  - The phone has to be gone for CHATTY_HOME_AWAY_MINUTES (30) first, so a walk
    to the mailbox or a phone that naps for a few minutes doesn't count.
  - A phone that disappears at night (night mode, quiet_hours.py) is not "away":
    phones go quiet when they sleep. So no greeting after one of those.
  - Daytime, while she's free: she says it ("Welcome home, Vincent! I missed you.").
    If she's busy (you're already talking to her) or it's been more than 5 minutes,
    she lets it go: you're clearly home.
  - At night: a quiet notice on her face, no voice.
  - Nothing at startup: the first look after Chatty starts is just "who's here".

Privacy
  She only watches the addresses you list. She keeps no list of other devices and
  nothing goes to disk or to the cloud: when someone came and went lives in RAM
  and is forgotten on restart. The log says "Vincent came home", never addresses.

Settings (in /etc/chatty/secrets.env):
    CHATTY_HOME_PHONES          who to greet and their phones' WiFi addresses, e.g.
                                Vincent=aa:bb:cc:dd:ee:ff
                                Vincent=aa:bb:cc:dd:ee:ff,11:22:33:44:55:66;Sam=...
                                (empty = off, the default)
    CHATTY_HOME_AWAY_MINUTES    gone this long before a return counts (default 30)
    CHATTY_HOME_SPEAK=0         face notice only, never say it
    CHATTY_HOME_EVERY           seconds between looks (default 30)
    CHATTY_HOME_SWEEP           seconds between whole-subnet knocks while someone
                                is away (default 300)
    CHATTY_HOME_SUBNET          the home network to knock on, e.g. 192.168.1.0/24
                                (default: worked out from the Pi's own WiFi/cable)

Try it on the Pi:
    python3 src/homecoming.py --find     lists devices on the home network right now
                                         (find your phone's address in the list)
    python3 src/homecoming.py --watch    shows home / away for CHATTY_HOME_PHONES live
"""
from __future__ import annotations

import ipaddress
import os
import random
import re
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

try:
    import quiet_hours
except ImportError:  # running from another folder
    from . import quiet_hours  # type: ignore


def _num(name: str, default: float, low: float, high: float) -> float:
    try:
        return min(high, max(low, float(os.getenv(name, str(default)))))
    except ValueError:
        return default


AWAY = _num("CHATTY_HOME_AWAY_MINUTES", 30, 5, 24 * 60) * 60
SPEAK = os.getenv("CHATTY_HOME_SPEAK", "1") != "0"
EVERY = _num("CHATTY_HOME_EVERY", 30, 10, 600)
SWEEP = _num("CHATTY_HOME_SWEEP", 300, 60, 3600)
SETTLE = 7.0               # seconds for the kernel to ask "who has this address?" and hear back
SPEECH_MAX_AGE = 5 * 60    # a greeting older than this is let go
KNOCK_PORT = 5353          # mDNS: phones listen here; a stray packet is simply ignored
MAX_HOSTS = 1024           # never knock on more than this many addresses in one sweep
FRESH = {"REACHABLE", "PERMANENT", "NOARP"}   # the device answered recently

_MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def norm_mac(text: str) -> Optional[str]:
    """'AA-BB-CC-DD-EE-FF' / 'aa:bb:..' -> 'aa:bb:cc:dd:ee:ff', or None."""
    t = text.strip().lower().replace("-", ":")
    if re.fullmatch(r"[0-9a-f]{12}", t):
        t = ":".join(t[i:i + 2] for i in range(0, 12, 2))
    return t if _MAC.match(t) else None


def parse_people(text: str) -> Dict[str, Set[str]]:
    """'Vincent=aa:bb:..,11:22:..;Sam=..' -> {'Vincent': {'aa:bb:..', '11:22:..'}, 'Sam': {..}}."""
    people: Dict[str, Set[str]] = {}
    for part in re.split(r"[;\n]", text or ""):
        if "=" not in part:
            continue
        name, macs = part.split("=", 1)
        name = re.sub(r"[^\w' .-]", "", name).strip()[:30]
        found = {m for m in (norm_mac(x) for x in re.split(r"[,\s]+", macs)) if m}
        if name and found:
            people.setdefault(name, set()).update(found)
    return people


# ----- the Pi's side of the network (no root needed) -----

def read_neighbors() -> List[Tuple[str, str, str]]:
    """[(ip, mac, state)] from the Pi's neighbor table, IPv4 only."""
    rows = []
    try:
        out = subprocess.run(["ip", "-4", "neigh", "show"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    for line in out.splitlines():
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+) .*\blladdr ([0-9a-fA-F:]{17})\b.*?\b([A-Z]+)\s*$", line.strip())
        if m:
            rows.append((m.group(1), m.group(2).lower(), m.group(3)))
    if rows or out:
        return rows
    try:   # no `ip` command: the older table (no states, so treat complete entries as fresh)
        with open("/proc/net/arp") as f:
            for line in f.read().splitlines()[1:]:
                p = line.split()
                if len(p) >= 4 and p[2] == "0x2":
                    rows.append((p[0], p[3].lower(), "REACHABLE"))
    except OSError:
        pass
    return rows


def local_subnets() -> List[ipaddress.IPv4Network]:
    """The Pi's home networks (WiFi / cable), not Tailscale, not loopback."""
    want = os.getenv("CHATTY_HOME_SUBNET", "").strip()
    if want:
        try:
            return [ipaddress.ip_network(want, strict=False)]
        except ValueError:
            print("Homecoming: CHATTY_HOME_SUBNET isn't a network like 192.168.1.0/24", flush=True)
    nets = []
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return nets
    for line in out.splitlines():
        m = re.search(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+/\d+)", line)
        if not m:
            continue
        dev, cidr = m.group(1), m.group(2)
        if dev == "lo" or dev.startswith(("tailscale", "docker", "veth", "br-", "virbr")):
            continue
        iface = ipaddress.ip_interface(cidr)
        if not iface.ip.is_private or iface.ip in ipaddress.ip_network("100.64.0.0/10"):
            continue
        net = iface.network
        if net.num_addresses > MAX_HOSTS:     # a big network: just the Pi's own /24 of it
            net = ipaddress.ip_interface(f"{iface.ip}/24").network
        nets.append(net)
    return nets


def knock(ips: Iterable[str]) -> int:
    """One tiny UDP packet to each address. The packet itself is ignored by the phone;
    sending it makes the Pi ask the network who has that address."""
    sent = 0
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(False)
    try:
        for ip in ips:
            try:
                s.sendto(b"\0", (ip, KNOCK_PORT))
                sent += 1
            except OSError:
                pass       # unreachable right now: that's an answer too
    finally:
        s.close()
    return sent


def sweep_targets(nets: Iterable[ipaddress.IPv4Network]) -> List[str]:
    out: List[str] = []
    for net in nets:
        for host in net.hosts():
            out.append(str(host))
            if len(out) >= MAX_HOSTS:
                return out
    return out


# ----- what she says -----

def _part_of_day(now: float) -> str:
    h = time.localtime(now).tm_hour
    if 5 <= h < 12:
        return "Good morning"
    if 12 <= h < 17:
        return "Good afternoon"
    return "Good evening"


def _join(names: List[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def greeting(names: List[str], gone: float, now: float) -> str:
    who = _join(names)
    if gone < 2 * 3600:
        return random.choice([f"Welcome back, {who}!",
                              f"Oh, hi {who}! Welcome back.",
                              f"There you are, {who}! Welcome back."])
    if gone < 8 * 3600:
        return random.choice([f"Welcome home, {who}! {_part_of_day(now)}.",
                              f"{_part_of_day(now)}, {who}! Welcome home.",
                              f"Hey, {who}'s home! Welcome back."])
    return random.choice([f"Welcome home, {who}! I missed you.",
                          f"Welcome home, {who}! Tiny and I kept an eye on things while you were out.",
                          f"{who}, you're home! I missed you. Everything's been nice and calm here."])


def _clock(ts: float) -> str:
    d = time.localtime(ts)
    return f"{d.tm_hour % 12 or 12}:{d.tm_min:02d} {'AM' if d.tm_hour < 12 else 'PM'}"


def _gone_words(secs: float) -> str:
    mins = round(secs / 60)
    if mins < 90:
        return f"{mins} minutes"
    hours = round(secs / 3600)
    return "about an hour" if hours == 1 else f"about {hours} hours"


@dataclass
class Person:
    name: str
    macs: Set[str]
    home: Optional[bool] = None   # None = not sure yet (just started)
    last_seen: float = 0.0
    left_at: float = 0.0          # when she decided they'd gone out (last seen time)
    ip: Optional[str] = None      # where the phone was last time


class Homecoming:
    """Looks for the listed phones in a background thread. The voice node calls
    due(mode) from its main loop to get a greeting to say now (or None)."""

    def __init__(self, people: Optional[Dict[str, Set[str]]] = None,
                 neighbors: Callable[[], List[Tuple[str, str, str]]] = read_neighbors,
                 knock: Callable[[Iterable[str]], int] = knock,
                 subnets: Callable[[], List[ipaddress.IPv4Network]] = local_subnets,
                 notice: Optional[Callable[[str], None]] = None,
                 extras: Optional[Callable[[], str]] = None,
                 is_night: Callable[[float], bool] = quiet_hours.is_night,
                 clock: Callable[[], float] = time.time,
                 settle: float = SETTLE, away: float = AWAY, speak: bool = SPEAK):
        if people is None:
            people = parse_people(os.getenv("CHATTY_HOME_PHONES", ""))
        self.people = {n: Person(n, set(m)) for n, m in people.items()}
        self.neighbors, self.knock, self.subnets = neighbors, knock, subnets
        self.notice = notice if notice is not None else _face_notice
        self.extras, self.is_night, self.clock = extras, is_night, clock
        self.settle, self.away, self.speak = settle, away, speak
        self.started = clock()
        self.last_sweep = -1e12
        self.lock = threading.Lock()
        self.pending: List[Tuple[str, float, float]] = []   # (name, arrived at, time away)

    @property
    def enabled(self) -> bool:
        return bool(self.people)

    # ----- one look -----
    def look(self, now: Optional[float] = None) -> Set[str]:
        """Knock, wait a moment, read the neighbor table. Returns who's home right now."""
        now = self.clock() if now is None else now
        targets = {p.ip for p in self.people.values() if p.ip}
        someone_missing = any(p.home is not True or not p.ip or now - p.last_seen > 3 * EVERY
                              for p in self.people.values())
        if someone_missing and now - self.last_sweep >= SWEEP:
            self.last_sweep = now
            try:
                targets.update(sweep_targets(self.subnets()))
            except Exception as e:
                print("Homecoming: couldn't work out the home network:", repr(e), flush=True)
        if targets:
            try:
                self.knock(sorted(targets))
            except Exception as e:
                print("Homecoming: knock failed:", repr(e), flush=True)
            if self.settle:
                time.sleep(self.settle)
        seen = set()
        for ip, mac, state in self.neighbors():
            if state not in FRESH:
                continue
            for p in self.people.values():
                if mac in p.macs:
                    seen.add(p.name)
                    p.ip = ip
        return seen

    def update(self, seen: Set[str], now: Optional[float] = None) -> None:
        """Decide who left and who came home."""
        now = self.clock() if now is None else now
        greet = []
        with self.lock:
            for p in self.people.values():
                if p.name in seen:
                    if p.home is False:
                        gone = now - p.left_at
                        if self.is_night(p.left_at):
                            print(f"Homecoming: {p.name}'s phone is back (it went quiet at night, "
                                  f"probably asleep)", flush=True)
                        else:
                            print(f"Homecoming: {p.name} came home (away {_gone_words(gone)})", flush=True)
                            greet.append((p.name, now, gone))
                    p.home, p.last_seen = True, now
                else:
                    since = p.last_seen or self.started
                    if p.home is not False and now - since >= self.away:
                        if p.home:
                            print(f"Homecoming: {p.name} seems to be out "
                                  f"(phone last seen {_clock(since)})", flush=True)
                        p.home, p.left_at = False, since
            if not greet:
                return
            out_loud = self.speak and not self.is_night(now)
            if out_loud:
                self.pending.extend(greet)
        if not out_loud:
            names = [g[0] for g in greet]
            try:
                self.notice(f"{_join(names)} came home at {_clock(now)}. Welcome home!")
            except Exception as e:
                print("Homecoming: couldn't show the notice:", repr(e), flush=True)

    def check_once(self) -> None:
        try:
            seen = self.look()
        except Exception as e:
            print("Homecoming: look failed:", repr(e), flush=True)
            return
        self.update(seen)

    def run_forever(self) -> None:
        time.sleep(20)     # let the WiFi settle after a boot
        while True:
            started = time.time()
            self.check_once()
            time.sleep(max(1.0, EVERY - (time.time() - started)))

    def start(self) -> None:
        if self.enabled:
            print(f"Homecoming: watching for {_join(sorted(self.people))}'s phone"
                  f"{'s' if len(self.people) > 1 else ''}", flush=True)
            threading.Thread(target=self.run_forever, daemon=True, name="homecoming").start()

    # ----- for the voice node's main loop -----
    def due(self, mode: str, now: Optional[float] = None) -> Optional[Tuple[str, str]]:
        """(greeting, face mood) to say now, only while she's free. While someone is
        talking to her (active / confirm) the greeting is let go: they're clearly home."""
        now = self.clock() if now is None else now
        with self.lock:
            if not self.pending:
                return None
            if mode in ("active", "confirm"):
                self.pending = []
                return None
            if mode != "sleep":
                return None
            fresh = [g for g in self.pending if now - g[1] <= SPEECH_MAX_AGE]
            self.pending = []
        if not fresh or self.is_night(now):
            return None
        names = []
        for name, _, _ in fresh:
            if name not in names:
                names.append(name)
        gone = max(g[2] for g in fresh)
        text = greeting(names, gone, now)
        if gone >= 2 * 3600 and self.extras:
            try:
                more = (self.extras() or "").strip()
            except Exception:
                more = ""
            if more:
                text += " " + more
        return text, ("love_talk" if gone >= 8 * 3600 else "speaking")

    # ----- "Hey Chatty, is Vincent home?" / "who's home?" -----
    def answer(self, name: str = "", now: Optional[float] = None) -> str:
        now = self.clock() if now is None else now
        if not self.people:
            return ("I'm not watching for anyone's phone yet. Put a name and the phone's WiFi "
                    "address in CHATTY_HOME_PHONES and I'll say hello when they get home.")
        with self.lock:
            people = list(self.people.values())
        if name:
            people = [p for p in people if p.name.lower() == name.lower()] or people
        parts = []
        for p in people:
            if p.home:
                parts.append(f"{p.name}'s phone is here")
            elif p.home is False:
                parts.append(f"{p.name}'s phone has been away since {_clock(p.left_at)}")
            else:
                parts.append(f"I haven't spotted {p.name}'s phone yet")
        return ". ".join(parts) + "."


def _face_notice(text: str) -> None:
    import face_link
    face_link.notice(text)


def asked_who(prompt: str, people: Iterable[str]) -> Optional[str]:
    """'is vincent home' -> 'Vincent'; 'who's home' -> ''; anything else -> None."""
    p = prompt.lower()
    if re.search(r"\b(who'?s|who is|anyone|anybody|is (anyone|anybody|somebody|someone)) (at )?home\b", p):
        return ""
    for name in people:
        if re.search(rf"\b(is|has) {re.escape(name.lower())} (at )?(home|back|here|gotten home|got home|come home)\b", p):
            return name
    return None


if __name__ == "__main__":
    import sys
    try:
        from dotenv import load_dotenv
        load_dotenv("/etc/chatty/secrets.env")
    except ImportError:
        pass
    nets = local_subnets()
    print("Home network:", ", ".join(str(n) for n in nets) or "none found (set CHATTY_HOME_SUBNET)")
    if "--find" in sys.argv:
        print(f"Knocking on {len(sweep_targets(nets))} addresses, one moment...")
        knock(sweep_targets(nets))
        time.sleep(SETTLE + 1)
        rows = sorted((r for r in read_neighbors() if r[2] in FRESH),
                      key=lambda r: tuple(int(x) for x in r[0].split(".")))
        for ip, mac, _ in rows:
            first = int(mac.split(":")[0], 16)
            kind = "private address (phones, tablets, laptops)" if first & 2 else ""
            print(f"  {ip:<16} {mac}   {kind}")
        print("Your phone's address is under Settings > Wi-Fi > (i) > Wi-Fi Address.")
        sys.exit(0)
    hc = Homecoming(notice=lambda t: print("  (face notice)", t), away=60)
    if not hc.enabled:
        print("CHATTY_HOME_PHONES is empty. Example: CHATTY_HOME_PHONES=Vincent=aa:bb:cc:dd:ee:ff")
        sys.exit(1)
    print("Watching (Ctrl+C to stop). 'away' here means not seen for 1 minute.")
    while True:
        seen = hc.look()
        hc.update(seen)
        for p in hc.people.values():
            state = "home" if p.home else ("away" if p.home is False else "not seen yet")
            print(f"  {time.strftime('%H:%M:%S')}  {p.name}: {state}  (ip {p.ip or '?'})", flush=True)
        said = hc.due("sleep")
        if said:
            print("  She'd say:", said[0])
        time.sleep(max(1.0, EVERY - SETTLE))

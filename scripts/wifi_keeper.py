#!/usr/bin/env python3
"""
WiFi keeper: Chatty stays on the best WiFi she knows the password to.

Once a minute she checks that she can really reach the internet (not just
"connected": a small web check, like the one NetworkManager itself uses).

  - No internet twice in a row: she rescans and tries her saved networks,
    strongest signal first, until one really works. The network that let her
    down is skipped for a while (CHATTY_WIFI_BAD_MINUTES) so she doesn't hop
    straight back onto it.
  - Online but on a weak signal, while a saved network nearby is much
    stronger (3 checks in a row): she moves over, and moves back if the new
    one has no internet. At most once every CHATTY_WIFI_ROAM_MINUTES.
  - Home WiFi (CHATTY_WIFI_HOME, e.g. GF-Home): the network most of the
    nodes are on. When she's on another one and home is back in range with a
    usable signal (3 checks in a row), she moves home, and back if home has
    no internet; each failed try makes her wait longer before the next (30 min,
    doubling up to 4 h). On home she only leaves for a stronger network when
    home itself is very weak (below CHATTY_WIFI_HOME_MIN), so she doesn't
    bounce between the two. When nothing has internet, home is tried first.
  - With a network cable plugged in and working, she leaves WiFi alone.

Each switch shows on her face as a notice ("I moved to the X WiFi: Y had no
internet"). She never speaks about it, and never phones (no internet, after
all). Everything is logged to the journal: journalctl -u chatty-wifi -f

Passwords: she only uses the networks already saved in NetworkManager (the
ones you set up in the desktop WiFi menu). She never reads, prints or logs a
password; nmcli is never asked for secrets.

Settings (in /etc/chatty/secrets.env):
    CHATTY_WIFI=0                   turn this off
    CHATTY_WIFI_EVERY               seconds between checks (default 60)
    CHATTY_WIFI_FAILS               failed checks in a row before switching (default 2)
    CHATTY_WIFI_BAD_MINUTES         skip a network that let her down this long (default 30)
    CHATTY_WIFI_ROAM=0              never leave a working network for a stronger one
    CHATTY_WIFI_WEAK                signal percent counted as weak (default 40)
    CHATTY_WIFI_MARGIN              how much stronger the other one must be (default 25)
    CHATTY_WIFI_ROAM_MINUTES        least time between moves to a stronger one (default 15)
    CHATTY_WIFI_CHECK_URLS          comma list of check pages (defaults below)
    CHATTY_WIFI_AVOID               comma list of saved network names (SSIDs) never to pick
    CHATTY_WIFI_HOME                the home network's name (SSID); empty = no home
    CHATTY_WIFI_HOME_MIN            least home signal percent worth moving back for (default 30)

See what she sees (no changes):   python3 scripts/wifi_keeper.py --status
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


ENABLED = os.getenv("CHATTY_WIFI", "1") != "0"
EVERY = max(15.0, _num("CHATTY_WIFI_EVERY", 60))
FAILS = max(1, int(_num("CHATTY_WIFI_FAILS", 2)))
BAD_SECONDS = _num("CHATTY_WIFI_BAD_MINUTES", 30) * 60
ROAM = os.getenv("CHATTY_WIFI_ROAM", "1") != "0"
WEAK = _num("CHATTY_WIFI_WEAK", 40)
MARGIN = _num("CHATTY_WIFI_MARGIN", 25)
ROAM_SECONDS = _num("CHATTY_WIFI_ROAM_MINUTES", 15) * 60
AVOID = {s.strip() for s in os.getenv("CHATTY_WIFI_AVOID", "").split(",") if s.strip()}
HOME = os.getenv("CHATTY_WIFI_HOME", "").strip()
HOME_MIN = _num("CHATTY_WIFI_HOME_MIN", 30)
HOME_BACKOFF_MAX = 4 * 3600     # longest wait between failed tries to go home
ROAM_CHECKS = 3             # weak checks in a row before moving to a stronger one
RESCAN_SECONDS = 300        # fresh scan at most this often while things are fine
RETRY_SECONDS = 300         # after trying everything and failing, wait this long
STATUS_FILE = os.getenv("CHATTY_WIFI_STATUS_FILE", "/run/chatty-wifi.json")

# The same kind of check NetworkManager and phones use. Both are plain
# "are you there?" pages; nothing about Chatty is sent.
CHECKS = [
    ("http://nmcheck.gnome.org/check_network_status.txt", 200, b"NetworkManager is online"),
    ("http://cp.cloudflare.com/generate_204", 204, b""),
]
_urls = [u.strip() for u in os.getenv("CHATTY_WIFI_CHECK_URLS", "").split(",") if u.strip()]
if _urls:
    CHECKS = [(u, None, b"") for u in _urls]


def log(msg: str) -> None:
    print(msg, flush=True)


def internet_ok(timeout: float = 6.0) -> bool:
    """True if any check page answers the way it should. A captive portal
    (a login page) or a dead connection doesn't count."""
    for url, want_status, want_body in CHECKS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "chatty-wifi-check"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(200)
                if want_status is not None and r.status != want_status:
                    continue
                if want_status is None and not 200 <= r.status < 400:
                    continue
                if want_body and want_body not in body:
                    continue
                return True
        except Exception:
            continue
    return False


def split_terse(line: str) -> List[str]:
    """Split one line of `nmcli -t` output. Colons inside a value come out
    as \\: and backslashes as \\\\."""
    out, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


@dataclass
class Saved:
    name: str       # NetworkManager's name for it (often the SSID)
    uuid: str
    ssid: str
    autoconnect: bool = True


@dataclass
class Seen:
    ssid: str
    signal: int
    in_use: bool = False


class NM:
    """The few nmcli calls the keeper needs. Never asks for secrets
    (no --show-secrets), so passwords never pass through here."""

    def __init__(self, run: Callable = subprocess.run):
        self._run = run
        self._saved: Optional[List[Saved]] = None
        self._saved_at = 0.0

    def _nmcli(self, *args: str, timeout: float = 20) -> Optional[str]:
        try:
            p = self._run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
        except Exception as e:
            log(f"nmcli {args[0] if args else ''} failed: {e}")
            return None
        if p.returncode != 0:
            err = (p.stderr or "").strip().splitlines()
            log(f"nmcli {' '.join(args[:3])}: {err[0] if err else 'error ' + str(p.returncode)}")
            return None
        return p.stdout or ""

    def devices(self) -> List[Dict[str, str]]:
        out = self._nmcli("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status") or ""
        rows = []
        for line in out.splitlines():
            f = split_terse(line)
            if len(f) >= 4:
                rows.append({"device": f[0], "type": f[1], "state": f[2], "connection": f[3]})
        return rows

    def wifi_device(self) -> Optional[Dict[str, str]]:
        for d in self.devices():
            if d["type"] == "wifi" and not d["device"].startswith("p2p"):
                return d
        return None

    def wired_connected(self) -> bool:
        return any(d["type"] == "ethernet" and d["state"].startswith("connected")
                   for d in self.devices())

    def saved(self, now: float = 0.0) -> List[Saved]:
        if self._saved is not None and now - self._saved_at < 300:
            return self._saved
        out = self._nmcli("-t", "-f", "NAME,UUID,TYPE", "connection", "show")
        if out is None:
            return self._saved or []
        result = []
        for line in out.splitlines():
            f = split_terse(line)
            if len(f) < 3 or f[2] not in ("802-11-wireless", "wifi"):
                continue
            name, uuid = f[0], f[1]
            ssid = (self._nmcli("-g", "802-11-wireless.ssid", "connection", "show", uuid) or "").strip()
            mode = (self._nmcli("-g", "802-11-wireless.mode", "connection", "show", uuid) or "").strip()
            if mode in ("ap", "adhoc", "mesh"):
                continue        # a hotspot she'd host, not one to join
            auto = (self._nmcli("-g", "connection.autoconnect", "connection", "show", uuid) or "yes").strip()
            result.append(Saved(name, uuid, ssid.replace("\\:", ":") or name, auto != "no"))
        self._saved, self._saved_at = result, now
        return result

    def scan(self, ifname: str, rescan: bool) -> List[Seen]:
        out = self._nmcli("-t", "-f", "IN-USE,SSID,SIGNAL", "device", "wifi", "list",
                          "ifname", ifname, "--rescan", "yes" if rescan else "no",
                          timeout=40) or ""
        best: Dict[str, Seen] = {}
        for line in out.splitlines():
            f = split_terse(line)
            if len(f) < 3 or not f[1]:
                continue
            try:
                sig = int(f[2])
            except ValueError:
                continue
            s = best.get(f[1])
            in_use = f[0].strip() == "*"
            if s is None:
                best[f[1]] = Seen(f[1], sig, in_use)
            else:       # same name, several access points: keep the strongest
                s.signal = max(s.signal, sig)
                s.in_use = s.in_use or in_use
        return sorted(best.values(), key=lambda s: -s.signal)

    def up(self, uuid: str, ifname: str) -> bool:
        return self._nmcli("--wait", "45", "connection", "up", "uuid", uuid,
                           "ifname", ifname, timeout=60) is not None


@dataclass
class Choice:
    saved: Saved
    signal: int


def candidates(saved: List[Saved], seen: List[Seen], bad: Dict[str, float], now: float,
               avoid=frozenset()) -> List[Choice]:
    """Saved networks that are in range right now, strongest first, without
    the ones that let her down recently or that you said to avoid."""
    signal = {s.ssid: s.signal for s in seen}
    out = []
    for s in saved:
        if s.ssid not in signal or s.ssid in avoid or not s.autoconnect:
            continue
        if bad.get(s.uuid, 0) > now:
            continue
        out.append(Choice(s, signal[s.ssid]))
    return sorted(out, key=lambda c: -c.signal)


class Keeper:
    def __init__(self, nm: NM, online: Callable[[], bool] = internet_ok,
                 notice: Optional[Callable[[str], None]] = None,
                 clock: Callable[[], float] = time.time,
                 settle: Callable[[], None] = lambda: time.sleep(5)):
        self.nm = nm
        self.online = online
        self.notice = notice or (lambda text: None)
        self.clock = clock
        self.settle = settle
        self.fails = 0
        self.weak = 0
        self.homeward = 0
        self.home_misses = 0
        self.bad: Dict[str, float] = {}
        self.last_roam = 0.0
        self.last_scan = 0.0
        self.retry_after = 0.0
        self.told_offline = False
        self.status: Dict = {}

    # -- helpers ---------------------------------------------------------
    def _current(self, saved: List[Saved], dev: Dict[str, str]) -> Optional[Saved]:
        if not dev["state"].startswith("connected"):
            return None
        for s in saved:
            if s.name == dev["connection"]:
                return s
        return None

    def _try(self, choice: Choice, ifname: str) -> bool:
        log(f"Trying {choice.saved.ssid} (signal {choice.signal}%)")
        if not self.nm.up(choice.saved.uuid, ifname):
            return False
        self.settle()
        if self.online():
            return True
        self.settle()
        return self.online()

    def _save_status(self, **kw) -> None:
        self.status = dict(kw, ts=int(self.clock()))
        try:
            tmp = STATUS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.status, f)
            os.chmod(tmp, 0o644)
            os.replace(tmp, STATUS_FILE)
        except OSError:
            pass

    # -- one check -------------------------------------------------------
    def step(self) -> str:
        now = self.clock()
        dev = self.nm.wifi_device()
        if dev is None:
            return "no wifi device"
        ifname = dev["device"]
        if self.nm.wired_connected() and self.online():
            self.fails = 0
            return "on a cable, leaving WiFi alone"

        saved = self.nm.saved(now)
        current = self._current(saved, dev)

        if self.online():
            self.fails = 0
            if self.told_offline:
                self.told_offline = False
                self.notice(f"Back online on the {current.ssid if current else dev['connection']} WiFi.")
            return self._maybe_roam(now, ifname, saved, current)

        self.fails += 1
        self._save_status(online=False, ssid=current.ssid if current else None)
        if self.fails < FAILS:
            return f"no internet ({self.fails} of {FAILS})"
        if now < self.retry_after:
            return "no internet, waiting before trying again"
        return self._recover(now, ifname, saved, current)

    def _recover(self, now, ifname, saved, current) -> str:
        if current:
            self.bad[current.uuid] = now + BAD_SECONDS
            log(f"{current.ssid} has no internet; skipping it for {BAD_SECONDS / 60:.0f} min")
        seen = self.nm.scan(ifname, rescan=True)
        self.last_scan = now
        tried = []
        order = candidates(saved, seen, self.bad, now, AVOID)
        order.sort(key=lambda c: not (c.saved.ssid == HOME and c.signal >= HOME_MIN))
        for c in order:
            tried.append(c.saved.ssid)
            if self._try(c, ifname):
                self.fails = 0
                was = f": {current.ssid} had no internet" if current else ""
                self.notice(f"I moved to the {c.saved.ssid} WiFi{was}.")
                log(f"Online again on {c.saved.ssid}")
                self._save_status(online=True, ssid=c.saved.ssid, signal=c.signal)
                return f"switched to {c.saved.ssid}"
            self.bad[c.saved.uuid] = now + BAD_SECONDS
        # Nothing worked, so it's probably the internet itself, not the WiFi.
        # Reconnect to the old one (that alone sometimes fixes it), forget the
        # "bad" marks so everything gets another go, and wait a bit.
        self.bad.clear()
        if current:
            log(f"Reconnecting to {current.ssid}")
            self.nm.up(current.uuid, ifname)
        self.retry_after = now + RETRY_SECONDS
        if not self.told_offline:
            self.told_offline = True
            if tried:
                self.notice("I'm offline: none of my saved WiFi networks reach the internet right now.")
            else:
                self.notice("I'm offline, and none of my other saved WiFi networks are in range.")
        return "offline, nothing better found" if tried else "offline, no other saved network in range"

    def _maybe_roam(self, now, ifname, saved, current) -> str:
        rescan = now - self.last_scan >= RESCAN_SECONDS
        seen = self.nm.scan(ifname, rescan=rescan) if (ROAM or rescan) else []
        if rescan:
            self.last_scan = now
        here = next((s for s in seen if s.in_use), None)
        sig = here.signal if here else None
        self._save_status(online=True, ssid=current.ssid if current else None, signal=sig)
        if ROAM and HOME and current is not None and current.ssid != HOME:
            went = self._maybe_go_home(now, ifname, saved, seen, current)
            if went:
                return went
        else:
            self.homeward = 0
        weak = HOME_MIN if (HOME and current is not None and current.ssid == HOME) else WEAK
        if not ROAM or current is None or sig is None or sig >= weak:
            self.weak = 0
            return f"online ({sig}%)" if sig is not None else "online"
        others = [c for c in candidates(saved, seen, self.bad, now, AVOID)
                  if c.saved.uuid != current.uuid and c.signal >= sig + MARGIN]
        if not others:
            self.weak = 0
            return f"online, weak signal ({sig}%), nothing better in range"
        self.weak += 1
        if self.weak < ROAM_CHECKS or now - self.last_roam < ROAM_SECONDS:
            return f"online, weak signal ({sig}%), {others[0].saved.ssid} is stronger"
        self.weak = 0
        self.last_roam = now
        best = others[0]
        if self._try(best, ifname):
            self.notice(f"I moved to the {best.saved.ssid} WiFi: it's stronger "
                        f"({best.signal}% vs {sig}%).")
            self._save_status(online=True, ssid=best.saved.ssid, signal=best.signal)
            return f"moved to stronger {best.saved.ssid}"
        log(f"{best.saved.ssid} had no internet; going back to {current.ssid}")
        self.bad[best.saved.uuid] = now + BAD_SECONDS
        self.nm.up(current.uuid, ifname)
        return f"stayed on {current.ssid}"


    def _maybe_go_home(self, now, ifname, saved, seen, current) -> Optional[str]:
        """On another network while home is in range with a usable signal:
        after ROAM_CHECKS checks in a row, move home (and back if it has no
        internet). Returns what happened, or None to carry on as usual."""
        home = next((c for c in candidates(saved, seen, self.bad, now, AVOID)
                     if c.saved.ssid == HOME and c.signal >= HOME_MIN), None)
        if home is None:
            self.homeward = 0
            return None
        self.homeward += 1
        if self.homeward < ROAM_CHECKS or now - self.last_roam < ROAM_SECONDS:
            return f"online on {current.ssid}, home {HOME} is in range ({home.signal}%)"
        self.homeward = 0
        self.last_roam = now
        if self._try(home, ifname):
            self.home_misses = 0
            self.notice(f"I moved back to my home WiFi, {HOME}, where the other nodes are.")
            self._save_status(online=True, ssid=HOME, signal=home.signal)
            return f"moved home to {HOME}"
        wait = min(BAD_SECONDS * (2 ** self.home_misses), HOME_BACKOFF_MAX)
        self.home_misses += 1
        self.bad[home.saved.uuid] = now + wait
        log(f"Home {HOME} had no internet; going back to {current.ssid}, "
            f"next try in {wait / 60:.0f} min")
        self.nm.up(current.uuid, ifname)
        return f"stayed on {current.ssid}, home has no internet"


def show_status(nm: NM) -> None:
    dev = nm.wifi_device()
    if dev is None:
        print("No WiFi device found (is NetworkManager running?)")
        return
    print(f"WiFi device {dev['device']}: {dev['state']}, connection: {dev['connection'] or '-'}")
    print(f"Network cable connected: {'yes' if nm.wired_connected() else 'no'}")
    print(f"Internet check: {'OK' if internet_ok() else 'FAILED'}")
    saved = nm.saved()
    seen = {s.ssid: s for s in nm.scan(dev["device"], rescan=True)}
    print("\nSaved WiFi networks (passwords are never shown):")
    for s in sorted(saved, key=lambda s: -(seen[s.ssid].signal if s.ssid in seen else -1)):
        here = seen.get(s.ssid)
        where = f"signal {here.signal}%" if here else "not in range"
        flags = []
        if here and here.in_use:
            flags.append("in use")
        if not s.autoconnect:
            flags.append("autoconnect off, skipped")
        if s.ssid in AVOID:
            flags.append("in CHATTY_WIFI_AVOID, skipped")
        if HOME and s.ssid == HOME:
            flags.append("home")
        extra = f"  ({', '.join(flags)})" if flags else ""
        print(f"  {s.ssid:<28} {where}{extra}")
    if not saved:
        print("  (none found)")


def main() -> None:
    nm = NM()
    if "--status" in sys.argv:
        show_status(nm)
        return
    if not ENABLED:
        log("CHATTY_WIFI=0: WiFi keeper is off.")
        while True:         # stay up quietly so systemd doesn't keep restarting it
            time.sleep(3600)
    if subprocess.run(["which", "nmcli"], capture_output=True).returncode != 0:
        log("nmcli not found: the WiFi keeper needs NetworkManager.")
        sys.exit(1)

    def notice(text: str) -> None:
        log(f"Face notice: {text}")
        try:
            import face_link
            face_link.notice(text)
        except Exception as e:
            log(f"Couldn't reach the face: {e}")

    keeper = Keeper(nm, notice=notice)
    log(f"WiFi keeper started: checking every {EVERY:.0f} s"
        f"{'' if ROAM else ', not roaming to stronger networks'}"
        f"{f', home WiFi {HOME}' if HOME else ''}.")
    last = None
    while True:
        try:
            result = keeper.step()
        except Exception as e:
            result = f"check failed: {e}"
        if result != last and not result.startswith("online ("):
            log(result)
        last = result
        time.sleep(EVERY)


if __name__ == "__main__":
    main()

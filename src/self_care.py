"""
Self-care: Chatty keeps an eye on her own Pi and speaks up when she needs help.

Once a minute she checks:
  - how hot she is (CPU temperature)
  - her power (the Pi's under-voltage and throttling flags, from vcgencmd)
  - free space on her memory card
  - free working memory (RAM)
  - her thinking model (Ollama answers on localhost)
  - her ears (the microphone is still sending sound)

When something stays wrong for a little while she:
  - shows it on her face as a notice (day or night)
  - says it out loud in the daytime, once, while she's free
  - sends one phone alert through IFTTT for the serious ones, the same
    "Requesting your assistance, please" the SSH announcer uses
  - says "Feeling better" on her face (and the phone, if she'd phoned) when
    it clears up

"Hey Chatty, how are you feeling?" (or "health check", "how hot are you")
answers from the latest readings.

Settings (in /etc/chatty/secrets.env):
    CHATTY_CARE=0               turn this off
    CHATTY_CARE_EVERY           seconds between checks (default 60)
    CHATTY_CARE_SPEAK=0         show only, never say it out loud
    CHATTY_CARE_PHONE           serious (default) | all | off
    CHATTY_CARE_HOT             degrees C where she's "warm" (default 75)
    CHATTY_CARE_TOO_HOT         degrees C where she asks for help (default 80;
                                a Pi 4 slows itself down at 80-85)
    CHATTY_CARE_DISK_PCT        free-space percent that's "getting full" (default 10)
    CHATTY_CARE_MEM_MB          free RAM in MB that's "short" (default 150)
    CHATTY_CARE_EARS_SECONDS    seconds without mic sound before "my ears stopped" (default 30)
    IFTTT_KEY                   your IFTTT Webhooks key (shared with alerts.py)

Test on the Pi (no speaking, nothing sent):  python3 src/self_care.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

try:
    import quiet_hours
except ImportError:  # running from another folder
    from . import quiet_hours  # type: ignore


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


ENABLED = os.getenv("CHATTY_CARE", "1") != "0"
EVERY = max(10.0, _num("CHATTY_CARE_EVERY", 60))
SPEAK = os.getenv("CHATTY_CARE_SPEAK", "1") != "0"
PHONE = os.getenv("CHATTY_CARE_PHONE", "serious").strip().lower()
HOT = _num("CHATTY_CARE_HOT", 75)
TOO_HOT = _num("CHATTY_CARE_TOO_HOT", 80)
DISK_PCT = _num("CHATTY_CARE_DISK_PCT", 10)
MEM_MB = _num("CHATTY_CARE_MEM_MB", 150)
EARS_SECONDS = _num("CHATTY_CARE_EARS_SECONDS", 30)
OLLAMA_URL = os.getenv("CHATTY_OLLAMA_URL", "http://localhost:11434").rstrip("/")
LOCAL_LLM = os.getenv("CHATTY_LOCAL_LLM", "1") != "0"

ASK = "Requesting your assistance, please."
SPEECH_MAX_AGE = 3600       # don't say something she noticed over an hour ago
REMIND_HOURS = 12           # still wrong after this long: show / say it again

# vcgencmd get_throttled bits
UNDER_VOLTAGE_NOW = 0x1
THROTTLED_NOW = 0x4
SOFT_TEMP_LIMIT_NOW = 0x8
UNDER_VOLTAGE_SINCE_BOOT = 0x10000


# ----------------------------
# reading the Pi
# ----------------------------

def read_temp() -> Optional[float]:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def read_throttled() -> Optional[int]:
    """The Pi's throttle flags ('throttled=0x50005' -> 0x50005), or None off a Pi."""
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                             text=True, timeout=5).stdout
        return int(out.strip().split("=")[1], 16)
    except Exception:
        return None


def read_disk(path: str = "/") -> Optional[tuple]:
    """(free bytes, total bytes)."""
    try:
        u = shutil.disk_usage(path)
        return u.free, u.total
    except OSError:
        return None


def read_mem_mb() -> Optional[float]:
    """MemAvailable from /proc/meminfo, in MB."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return None


def ollama_ok() -> Optional[bool]:
    """True if Ollama answers, False if not, None if she doesn't use it."""
    if not LOCAL_LLM:
        return None
    import urllib.request
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=4):
            return True
    except Exception:
        return False


def read_all(mic_age: Optional[Callable[[], Optional[float]]] = None) -> dict:
    return {
        "temp": read_temp(),
        "throttled": read_throttled(),
        "disk": read_disk(),
        "mem_mb": read_mem_mb(),
        "ollama": ollama_ok(),
        "mic_age": mic_age() if mic_age else None,
    }


# ----------------------------
# turning readings into worries
# ----------------------------

@dataclass
class Worry:
    """One thing that's wrong right now."""
    key: str
    serious: bool
    screen: str          # short, for the face
    spoken: str          # what she says
    better: str          # face notice when it clears up


@dataclass
class _State:
    bad_count: int = 0
    good_count: int = 0
    active: bool = False
    since: float = 0.0
    told: float = 0.0       # last time she showed / said it
    phoned: bool = False
    serious: bool = False
    worry: Optional[Worry] = None


# how many checks in a row before she speaks up, and before she says it's over
CONFIRM = {"hot": 2, "power": 1, "disk": 1, "memory": 3, "brain": 3, "ears": 1}
CLEAR = {"hot": 3, "power": 1, "disk": 2, "memory": 3, "brain": 1, "ears": 1}
# minutes a worry must last before the phone hears about it (serious ones only)
PHONE_AFTER = {"hot": 0, "power": 0, "disk": 0, "memory": 0, "brain": 10, "ears": 5}


def _gb(n: float) -> str:
    g = n / 1e9
    return f"{g:.1f}" if g < 10 else f"{g:.0f}"


def worries(r: dict, active: Dict[str, bool] = None) -> Dict[str, Optional[Worry]]:
    """What's wrong in these readings. A key maps to None when that part is fine
    and to nothing at all when it couldn't be read (so it's left as it was).
    `active` says which worries are already on, for a little hysteresis."""
    active = active or {}
    out: Dict[str, Optional[Worry]] = {}
    flags = r.get("throttled")

    temp = r.get("temp")
    if temp is not None:
        slowing = flags is not None and bool(flags & (THROTTLED_NOW | SOFT_TEMP_LIMIT_NOW))
        limit = HOT - 5 if active.get("hot") else HOT   # cool down a bit before "better"
        if temp >= TOO_HOT or (slowing and temp >= HOT):
            out["hot"] = Worry(
                "hot", True,
                f"{ASK} I'm too hot ({temp:.0f}°C)",
                f"I'm getting too hot, {temp:.0f} degrees Celsius, and I'm slowing myself "
                f"down to cool off. Could you give me some air or check my fan? {ASK}",
                "Feeling better: I've cooled down to {temp}°C")
        elif temp >= limit:
            out["hot"] = Worry(
                "hot", False,
                f"I'm running warm ({temp:.0f}°C)",
                f"I'm running a little warm, about {temp:.0f} degrees Celsius. "
                "Some fresh air would be lovely.",
                "Feeling better: I've cooled down to {temp}°C")
        else:
            out["hot"] = None

    if flags is not None:
        if flags & (UNDER_VOLTAGE_NOW | UNDER_VOLTAGE_SINCE_BOOT):
            now_low = bool(flags & UNDER_VOLTAGE_NOW)
            out["power"] = Worry(
                "power", True,
                f"{ASK} My power is {'low right now' if now_low else 'dipping'}",
                ("My power is running low right now. " if now_low else
                 "My power dipped since I started up. ") +
                "A stronger power supply or a shorter cable would help me stay steady, "
                f"and keep me from restarting by surprise. {ASK}",
                "Feeling better: my power is steady again")
        else:
            out["power"] = None

    disk = r.get("disk")
    if disk:
        free, total = disk
        pct = 100.0 * free / total if total else 100.0
        limit = DISK_PCT + 2 if active.get("disk") else DISK_PCT
        if pct < 5 or free < 1e9:
            out["disk"] = Worry(
                "disk", True,
                f"{ASK} My memory card is almost full ({_gb(free)} GB left)",
                f"My memory card is almost full, only {_gb(free)} gigabytes left. "
                f"Could you clear out some old files for me? {ASK}",
                "Feeling better: {free} GB free on my memory card")
        elif pct < limit:
            out["disk"] = Worry(
                "disk", False,
                f"My memory card is getting full ({_gb(free)} GB left)",
                f"My memory card is getting full. I have {_gb(free)} gigabytes left.",
                "Feeling better: {free} GB free on my memory card")
        else:
            out["disk"] = None

    mem = r.get("mem_mb")
    if mem is not None:
        limit = MEM_MB * 1.5 if active.get("memory") else MEM_MB
        if mem < limit:
            out["memory"] = Worry(
                "memory", False,
                f"I'm short on working memory ({mem:.0f} MB free)",
                "I'm short on working memory right now, so I might be a little slow.",
                "Feeling better: I have room to think again")
        else:
            out["memory"] = None

    brain = r.get("ollama")
    if brain is not None:
        out["brain"] = None if brain else Worry(
            "brain", True,
            f"{ASK} My thinking model (Ollama) isn't answering",
            "My thinking model isn't answering, so I'm leaning on the cloud for now. "
            f"Could you check Ollama for me? {ASK}",
            "Feeling better: my thinking model is back")

    age = r.get("mic_age")
    if age is not None:
        out["ears"] = None if age < EARS_SECONDS else Worry(
            "ears", True,
            f"{ASK} I can't hear anything from my microphone",
            "I can't hear anything from my microphone, so I won't hear you say Hey Chatty. "
            f"Could you check that my speakerphone is plugged in? {ASK}",
            "Feeling better: I can hear again")
    return out


def _fill(text: str, r: dict) -> str:
    """Put today's numbers into a 'Feeling better' line."""
    temp = r.get("temp")
    disk = r.get("disk")
    return text.replace("{temp}", f"{temp:.0f}" if temp is not None else "a comfy temperature") \
               .replace("{free}", _gb(disk[0]) if disk else "more")


def phone_wanted(w: Worry, mode: str = None) -> bool:
    mode = PHONE if mode is None else mode
    return mode == "all" or (mode == "serious" and w.serious)


# ----------------------------
# the watcher
# ----------------------------

class Watcher:
    """Checks in a background thread. The voice node calls due(mode) from its main
    loop to get something she should say now (or None)."""

    def __init__(self, read: Optional[Callable[[], dict]] = None, clock=time.time,
                 notice: Optional[Callable[[str], None]] = None,
                 send: Optional[Callable[[str], None]] = None,
                 is_night: Optional[Callable[[float], bool]] = None,
                 mic_age: Optional[Callable[[], Optional[float]]] = None):
        self.read = read or (lambda: read_all(mic_age))
        self.clock = clock
        self.notice = notice or _face_notice
        self.send = send or _send_phone
        self.is_night = is_night or quiet_hours.is_night
        self.states: Dict[str, _State] = {}
        self.pending: List[tuple] = []     # (when, text)
        self.last: dict = {}               # latest readings, for "how are you feeling?"
        self.lock = threading.Lock()

    def _tell(self, w: Worry, now: float) -> None:
        try:
            self.notice(w.screen)
        except Exception as e:
            print("Self-care: couldn't show notice:", repr(e), flush=True)
        if SPEAK and not self.is_night(now):
            with self.lock:
                self.pending = [p for p in self.pending if p[2] != w.key]
                self.pending.append((now, w.spoken, w.key))

    def _phone(self, text: str) -> None:
        try:
            self.send(text)
        except Exception as e:
            print("Self-care: phone alert failed:", repr(e), flush=True)

    def check_once(self) -> None:
        now = self.clock()
        try:
            r = self.read()
        except Exception as e:
            print("Self-care check failed:", repr(e), flush=True)
            return
        self.last = r
        active = {k: s.active for k, s in self.states.items()}
        for key, w in worries(r, active).items():
            s = self.states.setdefault(key, _State())
            if w is None:
                s.bad_count = 0
                if not s.active:
                    continue
                s.good_count += 1
                if s.good_count < CLEAR.get(key, 1):
                    continue
                print(f"Self-care: {key} is fine again", flush=True)
                if s.worry:
                    better = _fill(s.worry.better, r)
                    try:
                        self.notice(better)
                    except Exception:
                        pass
                    if s.phoned:
                        self._phone(f"Chatty: {better}.")
                with self.lock:
                    self.pending = [p for p in self.pending if p[2] != key]
                self.states[key] = _State()
                continue

            s.good_count = 0
            s.bad_count += 1
            if not s.active:
                if s.bad_count < CONFIRM.get(key, 1):
                    continue
                s.active, s.since, s.told, s.serious, s.worry = True, now, now, w.serious, w
                print(f"Self-care: {w.screen}", flush=True)
                self._tell(w, now)
            else:
                worse = w.serious and not s.serious
                s.worry = w
                if worse or now - s.told >= REMIND_HOURS * 3600:
                    s.told, s.serious = now, s.serious or w.serious
                    print(f"Self-care: {w.screen}", flush=True)
                    self._tell(w, now)
            if (not s.phoned and phone_wanted(w)
                    and now - s.since >= PHONE_AFTER.get(key, 0) * 60):
                s.phoned = True
                self._phone(f"Chatty: {w.spoken}")

    def run_forever(self) -> None:
        time.sleep(20)      # let Ollama and the mic start up first
        while True:
            self.check_once()
            time.sleep(EVERY)

    def start(self) -> None:
        if ENABLED:
            threading.Thread(target=self.run_forever, daemon=True, name="self-care").start()

    def due(self, mode: str) -> Optional[str]:
        """Something to say now, only while she's free and it's daytime."""
        if mode != "sleep":
            return None
        now = self.clock()
        with self.lock:
            self.pending = [p for p in self.pending if now - p[0] < SPEECH_MAX_AGE]
            if not self.pending or self.is_night(now):
                return None
            return self.pending.pop(0)[1]

    def report(self, readings: Optional[dict] = None) -> str:
        """The answer to 'how are you feeling?'."""
        r = readings
        if r is None:
            try:
                r = self.read()
                self.last = r
            except Exception:
                r = self.last
        found = [w for w in worries(r).values() if w]
        parts = []
        temp = r.get("temp")
        if temp is not None:
            parts.append(f"I'm at {temp:.0f} degrees Celsius")
        flags = r.get("throttled")
        if flags is not None and not flags & (UNDER_VOLTAGE_NOW | UNDER_VOLTAGE_SINCE_BOOT):
            parts.append("my power is steady")
        disk = r.get("disk")
        if disk:
            parts.append(f"I have {_gb(disk[0])} gigabytes free")
        if r.get("ollama"):
            parts.append("my thinking model is awake")
        age = r.get("mic_age")
        if age is not None and age < EARS_SECONDS:
            parts.append("my ears are working")
        facts = ""
        if parts:
            facts = (", ".join(parts[:-1]) + " and " + parts[-1]) if len(parts) > 1 else parts[0]
            facts = facts[0].upper() + facts[1:] + "."
        if not found:
            return f"I'm feeling great, thanks for asking! {facts}".strip()
        trouble = " ".join(w.spoken.replace(ASK, "").strip() for w in found)
        return f"Mostly okay, but I could use a hand. {trouble}".strip()


def _face_notice(text: str) -> None:
    import face_link
    face_link.notice(text)


def _send_phone(text: str) -> None:
    import alerts
    alerts.send_phone_alert(text[:500])


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv("/etc/chatty/secrets.env")
    except ImportError:
        pass
    r = read_all()
    print("Readings:", r)
    for key, w in worries(r).items():
        print(f"  {key}: {'fine' if w is None else w.screen}")
    w = Watcher(read=lambda: r, notice=lambda t: None, send=lambda t: None)
    print("She'd say:", w.report(r))

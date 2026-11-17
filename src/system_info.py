"""
About herself: how hard her processor is working, which Python she runs on, how long
she's been awake, what she runs on. Read straight from the Pi (/proc, /sys, the Python
running her), answered at once by local_skills: no model, no cloud.

    "How busy is your processor?" / "what's your CPU usage?" / "how hard are you working?"
        -> "My processor is at 23 percent right now, across 4 cores, running at 1.5 gigahertz.
            I'm at 52 degrees."
    "What version of Python are you using?" -> "I'm running on Python 3 point 11 point 2."
    "How long have you been on?" / "what's your uptime?" -> "I've been on for 3 days and 4 hours."
    "What are you running on?" / "system info" -> the Pi model, Python and the processor.

Health worries (too hot, power dips, disk) stay in self_care.py ("how are you feeling?").
CHATTY_SYSTEM_INFO=0 turns this off.
"""
from __future__ import annotations

import os
import platform
import re
import time
from typing import Callable, Optional, Tuple

ENABLED = os.getenv("CHATTY_SYSTEM_INFO", "1") != "0"

CPU_Q = re.compile(
    r"\b(cpu|processor|processors|cores)\b.*\b(usage|use|using|load|busy|working|work|doing|percent|"
    r"how much|hows?|speed|fast)\b|\b(how much|hows?|whats?|what is)\b.*\b(cpu|processor)\b|"
    r"\bhow (hard|busy) (are you|is your brain|is your processor) (working|thinking)?\b|"
    r"\bhow busy are you\b|\bcpu (usage|load)\b|\bprocessor (usage|load)\b")
PYTHON_Q = re.compile(r"\b(you|your)\b.*\bpython\b|\bpython\b.*\b(you|your)\b|"
                      r"\b(which|what) (version of )?python\b|\bpython version\b|\bversion of python\b")
UPTIME_Q = re.compile(r"\buptime\b|\bhow long (have you been|has the pi been|since you) "
                      r"(on|up|awake|running|started|booted|restarted)\b|\bwhen did you (start|boot|wake up)\b")
SYSTEM_Q = re.compile(r"\b(system info|system information|what are you running on|what do you run on|"
                      r"what hardware|what computer are you|what kind of computer|what are you made of|"
                      r"tell me about your (hardware|system))\b")


def _read(path: str) -> Optional[str]:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def cpu_times(stat: Optional[str] = None) -> Optional[Tuple[int, int]]:
    """(busy, total) jiffies from the first line of /proc/stat."""
    text = stat if stat is not None else _read("/proc/stat")
    if not text:
        return None
    parts = text.splitlines()[0].split()
    if not parts or parts[0] != "cpu":
        return None
    nums = [int(x) for x in parts[1:]]
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)      # idle + iowait
    return sum(nums) - idle, sum(nums)


def cpu_percent(sample: Callable[[], Optional[Tuple[int, int]]] = cpu_times,
                wait: float = 0.5, sleep: Callable[[float], None] = time.sleep) -> Optional[float]:
    """How busy all cores are together, measured over `wait` seconds."""
    a = sample()
    sleep(wait)
    b = sample()
    if not a or not b or b[1] <= a[1]:
        return None
    return max(0.0, min(100.0, 100.0 * (b[0] - a[0]) / (b[1] - a[1])))


def cpu_ghz() -> Optional[float]:
    khz = _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    try:
        return int(khz.strip()) / 1e6 if khz else None
    except ValueError:
        return None


def cpu_temp() -> Optional[float]:
    raw = _read("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(raw.strip()) / 1000 if raw else None
    except ValueError:
        return None


def uptime_seconds() -> Optional[float]:
    raw = _read("/proc/uptime")
    try:
        return float(raw.split()[0]) if raw else None
    except (ValueError, IndexError):
        return None


def board() -> str:
    """'Raspberry Pi 4 Model B Rev 1.5' (device tree), or ''."""
    raw = _read("/proc/device-tree/model") or ""
    return raw.replace("\x00", "").strip()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def spoken_duration(secs: float) -> str:
    mins = int(secs // 60)
    days, hours, minutes = mins // 1440, (mins % 1440) // 60, mins % 60
    if days:
        return _plural(days, "day") + (f" and {_plural(hours, 'hour')}" if hours else "")
    if hours:
        return _plural(hours, "hour") + (f" and {_plural(minutes, 'minute')}" if minutes else "")
    return _plural(max(minutes, 1), "minute")


def python_version() -> str:
    """'3 point 11 point 2': said clearly by her voice, still readable on the panel."""
    return " point ".join(platform.python_version().split("."))


def processor_answer(pct: Optional[float], cores: Optional[int], ghz: Optional[float],
                     temp: Optional[float], load: Optional[float] = None) -> str:
    if pct is None:
        if load is None:
            return "Hmm, I can't read my processor right now."
        return f"My processor's load average is {load:.1f} right now."
    mood = ("I'm barely breaking a sweat." if pct < 25 else
            "I'm keeping busy." if pct < 60 else
            "I'm working pretty hard!" if pct < 90 else
            "I'm working flat out right now!")
    text = f"My processor is at {pct:.0f} percent right now"
    if cores:
        text += f", across {cores} cores"
    if ghz:
        text += f", running at {ghz:.1f} gigahertz"
    text += f". {mood}"
    if temp is not None:
        text += f" I'm at {temp:.0f} degrees Celsius."
    return text


def handle(text: str) -> Optional[str]:
    """A spoken answer about her processor / Python / uptime / system, or None."""
    if not ENABLED:
        return None
    t = " ".join(re.sub(r"[^a-z0-9\s.]", "", (text or "").lower()).split())
    if not t:
        return None
    if PYTHON_Q.search(t):
        return f"I'm running on Python {python_version()}."
    if UPTIME_Q.search(t):
        up = uptime_seconds()
        return (f"I've been on for {spoken_duration(up)}." if up is not None
                else "Hmm, I can't tell how long I've been on.")
    if CPU_Q.search(t):
        load = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
        return processor_answer(cpu_percent(), os.cpu_count(), cpu_ghz(), cpu_temp(), load)
    if SYSTEM_Q.search(t):
        what = board() or "little Linux computer"
        pct = cpu_percent()
        busy = f" My processor is at {pct:.0f} percent." if pct is not None else ""
        return (f"I'm running on a {what}, with {os.cpu_count() or 'a few'} processor cores and "
                f"Python {python_version()}.{busy}")
    return None


if __name__ == "__main__":
    import sys
    for q in sys.argv[1:] or ["how busy is your processor", "what version of python are you using",
                              "how long have you been on", "what are you running on"]:
        print(f"{q!r}: {handle(q)}")

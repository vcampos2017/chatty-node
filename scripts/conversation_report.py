"""
Summarize Chatty's conversation log, to see what to improve next.

    python3 scripts/conversation_report.py            # last 7 days
    python3 scripts/conversation_report.py --days 30
    python3 scripts/conversation_report.py --all      # every saved turn, newest last

Shows: how often each part of Chatty answered (and how fast), the most common
questions (good candidates for new built-in answers), questions that went to
the paid relay, errors, background talk that was filtered, and possible false
wakes.
"""
import argparse
import glob
import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

LOG_DIR = os.getenv("CHATTY_LOG_DIR", os.path.expanduser("~/.local/share/chatty/logs"))

TIER_NAMES = {
    "skill": "Built-in answer (time, weather...)",
    "memory": "From memory",
    "local_llm": "Pi language model",
    "relay": "Relay / OpenAI (paid)",
}


def load(days):
    files = sorted(glob.glob(os.path.join(LOG_DIR, "conversations.jsonl*")),
                   key=lambda f: os.path.getmtime(f))
    cutoff = None if days is None else datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    ts = datetime.fromisoformat(r["ts"])
                except (ValueError, KeyError):
                    continue
                if cutoff is None or ts >= cutoff:
                    r["_ts"] = ts
                    rows.append(r)
    rows.sort(key=lambda r: r["_ts"])
    return rows


def local_time(ts):
    return ts.astimezone().strftime("%a %b %d %I:%M %p")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--all", action="store_true", help="print every turn as a transcript")
    args = ap.parse_args()

    rows = load(None if args.all else args.days)
    span = "all time" if args.all else f"the last {args.days} days"
    if not rows:
        print(f"No conversations logged in {span}. (Log folder: {LOG_DIR})")
        return

    if args.all:
        last_session = None
        for r in rows:
            if r.get("session") != last_session:
                print(f"\n--- {local_time(r['_ts'])} ---")
                last_session = r.get("session")
            kind = r.get("intent", "?")
            took = f" ({r['duration_s']:.1f}s)" if "duration_s" in r else ""
            if r.get("transcript"):
                print(f"  You:    {r['transcript']}")
            if r.get("reply"):
                print(f"  Chatty: {r['reply']}   [{kind}{took}]")
            elif not r.get("transcript"):
                print(f"  [{kind}] {r.get('notes', '')}")
            else:
                print(f"          [{kind}{took}]")
        return

    kinds = Counter(r.get("intent", "?") for r in rows)
    sessions = len({r.get("session") for r in rows if r.get("session")})
    print(f"Chatty conversations, {span}: {len(rows)} turns in {sessions} conversations\n")

    print("Who answered questions:")
    times = defaultdict(list)
    for r in rows:
        if r.get("intent") in TIER_NAMES and "duration_s" in r:
            times[r["intent"]].append(r["duration_s"])
    answered = sum(kinds[t] for t in TIER_NAMES)
    for tier, name in TIER_NAMES.items():
        n = kinds[tier]
        if not n:
            continue
        t = times[tier]
        speed = f"typically {statistics.median(t):.1f}s, slowest {max(t):.1f}s" if t else ""
        print(f"  {name:38} {n:4}  ({100 * n / max(1, answered):.0f}%)  {speed}")

    other = {k: v for k, v in kinds.items() if k not in TIER_NAMES}
    if other:
        print("\nOther events:")
        for k, v in sorted(other.items(), key=lambda kv: -kv[1]):
            print(f"  {k:38} {v:4}")

    has_text = any(r.get("transcript") for r in rows)
    if not has_text:
        print("\n(Private mode: words aren't logged, so questions can't be listed.)")
        return

    asked = Counter(r["transcript"] for r in rows
                    if r.get("intent") in TIER_NAMES and r.get("transcript"))
    if asked:
        print("\nMost asked (repeat questions are good candidates for built-in answers):")
        for q, n in asked.most_common(10):
            print(f"  {n:3}x  {q}")

    relay = Counter(r["transcript"] for r in rows if r.get("intent") == "relay" and r.get("transcript"))
    if relay:
        print("\nSent to the paid relay (could any be answered on the Pi?):")
        for q, n in relay.most_common(10):
            print(f"  {n:3}x  {q}")

    for kind, title in (("error", "Errors"),
                        ("filtered_background", "Filtered as background talk (check for real questions cut off)")):
        hits = [r for r in rows if r.get("intent") == kind]
        if hits:
            print(f"\n{title}:")
            for r in hits[-8:]:
                print(f"  {local_time(r['_ts'])}  {r.get('transcript', '')}  {r.get('notes', '')}")

    false_wakes = [r for r in rows if r.get("intent") == "no_question"]
    if false_wakes:
        print(f"\nWoke up but heard no question: {len(false_wakes)}x (possible false wakes):")
        for r in false_wakes[-8:]:
            conf = r.get("wake_confidence")
            how = r.get("wake_word") or "?"
            print(f"  {local_time(r['_ts'])}  via {how}" + (f", confidence {conf:.2f}" if conf else ""))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Run all of Chatty's tests: every tests/test_*.py, each in its own Python, the
way they're written (plain Python, no pip packages, stand-ins for vosk, numpy,
the speech engine and requests).

    python3 scripts/run_tests.py              all of them
    python3 scripts/run_tests.py red alerts   only files whose name contains a word

GitHub runs this on every pull request (.github/workflows/tests.yml), and it
works the same on the Pi or any computer. A file with no test_ functions in it
is skipped (it's an old script, not a test). Exit code 1 if anything failed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
TIMEOUT = 300            # seconds per file


def main(words) -> int:
    files = sorted(f for f in os.listdir(TESTS) if f.startswith("test_") and f.endswith(".py"))
    if words:
        files = [f for f in files if any(w in f for w in words)]
    failed, skipped, started = [], [], time.time()
    for name in files:
        path = os.path.join(TESTS, name)
        with open(path, encoding="utf-8") as fh:
            if "def test_" not in fh.read():
                skipped.append(name)
                continue
        t0 = time.time()
        try:
            run = subprocess.run([sys.executable, path], cwd=ROOT, capture_output=True,
                                 text=True, timeout=TIMEOUT)
            ok, out = run.returncode == 0, run.stdout + run.stderr
        except subprocess.TimeoutExpired as e:
            ok = False
            out = f"(still running after {TIMEOUT} s)\n" + str(e.stdout or "") + str(e.stderr or "")
        print(f"{'ok  ' if ok else 'FAIL'} {name} ({time.time() - t0:.1f} s)", flush=True)
        if not ok:
            failed.append(name)
            print("\n".join("     " + line for line in out.strip().splitlines()[-30:]), flush=True)
    print()
    for name in skipped:
        print(f"skipped {name} (no test_ functions: not a test)")
    total = len(files) - len(skipped)
    print(f"{total - len(failed)} of {total} test files passed in {time.time() - started:.0f} s")
    if failed:
        print("Failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

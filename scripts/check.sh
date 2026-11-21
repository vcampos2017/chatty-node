#!/usr/bin/env bash
# Quick check before (or after) a change: every Python file compiles, then all tests.
# The same thing GitHub runs on each pull request (.github/workflows/tests.yml).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m compileall -q src scripts tests app
echo "OK: syntax clean"
python3 scripts/run_tests.py "$@"

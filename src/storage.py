"""
Saving Chatty's small JSON files safely (timers, memory, voiceprints, scores,
"already did it today" markers...). One place for what about a dozen modules
each did by hand, a little differently.

save_json(path, data):
  - writes a temporary file next to it, flushes it to the SD card (fsync), then
    swaps it in with one rename, so a power cut leaves the old file or the new
    one, never half of one (two modules used to write in place);
  - the file is owner-only (600) from the first byte (voiceprints and timers
    used to be readable by others for a moment before chmod);
  - makes the folder if needed. Errors are raised (OSError), so each caller keeps
    its own "couldn't save" message.

load_json(path, default) gives `default` when the file is missing or unreadable.
"""
from __future__ import annotations

import json
import os
from typing import Any


def save_json(path, data: Any, indent: int = None, private: bool = True) -> None:
    path = os.fspath(path)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"      # two processes never share a temp file
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_json(path, default: Any = None) -> Any:
    try:
        with open(os.fspath(path), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default

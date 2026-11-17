"""Small helpers shared by the Matrix node's files: settings, a millisecond clock, dimming."""
# pylint: disable=import-error,broad-except
import os
import time

try:
    from secrets import secrets as SECRETS
except ImportError:
    SECRETS = {}


def setting(key, default=None):
    if key in SECRETS:
        return SECRETS[key]
    try:
        value = os.getenv(key.upper())
    except Exception:
        value = None
    return default if value is None else value


def flag(value):
    return str(value).strip().lower() not in ("0", "false", "no", "off", "")


def now_ms():
    return time.monotonic_ns() // 1000000


def dim(color, level):
    if level >= 1:
        return color
    r = int(((color >> 16) & 255) * level)
    g = int(((color >> 8) & 255) * level)
    b = int((color & 255) * level)
    return (r << 16) | (g << 8) | b

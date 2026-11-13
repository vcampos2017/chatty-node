"""
Read Chatty's settings file (/etc/chatty/secrets.env) without python-dotenv.

For the small scripts that run outside the voice node (the cron greenhouse check,
the soil monitor timer): their Python may not have dotenv, and then settings such
as CHATTY_GREENHOUSE_URL or CHATTY_NIGHT_START were never read.

KEY=value lines; "export " and quotes are allowed; the last line wins (like
python-dotenv); settings already in the environment win over the file.
"""
import os

SECRETS = "/etc/chatty/secrets.env"


def load(path: str = SECRETS) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return
    found = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        found[key] = value
    for key, value in found.items():
        os.environ.setdefault(key, value)

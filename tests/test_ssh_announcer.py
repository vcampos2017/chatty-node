import importlib.util
import os

_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "ssh_announcer.py")
_spec = importlib.util.spec_from_file_location("ssh_announcer", _path)
sa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sa)


def test_parse_accepted():
    line = "Accepted publickey for pi from 100.101.102.103 port 51234 ssh2: ED25519 SHA256:abc"
    assert sa.parse_line(line) == ("accepted", "pi", "100.101.102.103")


def test_parse_failed_invalid_user():
    line = "Failed password for invalid user admin from 203.0.113.9 port 4444 ssh2"
    assert sa.parse_line(line) == ("failed", "admin", "203.0.113.9")


def test_ignores_other_lines():
    assert sa.parse_line("pam_unix(sshd:session): session opened for user pi") is None


def test_describe_source():
    known = sa.parse_known("192.168.1.50=laptop")
    assert sa.describe_source("100.80.1.2", known) == "Tailscale"
    assert sa.describe_source("192.168.1.20", known) == "the home network"
    assert sa.describe_source("192.168.1.50", known) == "laptop"
    assert sa.describe_source("8.8.8.8", known) == "the internet"


def test_internet_login_gets_extra_warning():
    msg = sa.build_message("accepted", "pi", "8.8.8.8", {})
    assert "not from the home network" in msg


def test_debouncer():
    t = [0.0]
    d = sa.Debouncer(120, clock=lambda: t[0])
    assert d.allow(("pi", "1.2.3.4"))
    t[0] = 30
    assert not d.allow(("pi", "1.2.3.4"))
    assert d.allow(("pi", "5.6.7.8"))
    t[0] = 200
    assert d.allow(("pi", "1.2.3.4"))

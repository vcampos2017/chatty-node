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


def test_phone_alert_modes():
    assert sa.phone_alert_wanted("risky", "failed", "100.80.1.2", {})
    assert sa.phone_alert_wanted("risky", "accepted", "8.8.8.8", {})
    assert not sa.phone_alert_wanted("risky", "accepted", "100.80.1.2", {})
    assert sa.phone_alert_wanted("all", "accepted", "100.80.1.2", {})
    assert not sa.phone_alert_wanted("off", "failed", "8.8.8.8", {})


def test_parse_session_ended():
    line = "Disconnected from user pi 100.101.102.103 port 51234"
    assert sa.parse_line(line) == ("ended", "pi", "100.101.102.103")


def test_preauth_disconnects_are_not_session_ends():
    assert sa.parse_line("Disconnected from invalid user admin 203.0.113.9 port 4444 [preauth]") is None
    assert sa.parse_line("Disconnected from authenticating user root 203.0.113.9 port 4444 [preauth]") is None


def test_messages():
    assert sa.build_message("accepted", "pi", "100.80.1.2", {}) == "User pi logged on, from Tailscale."
    assert sa.build_message("ended", "pi", "100.80.1.2", {}) == "SSH session ended."
    failed = sa.build_message("failed", "admin", "8.8.8.8", {})
    assert failed.startswith("Possible suspicious activity.")
    assert sa.build_message("failed", "admin", "8.8.8.8", {}, need_help=True).endswith(
        "Requesting your assistance, please.")
    assert sa.build_message("accepted", "pi", "8.8.8.8", {}).startswith("Possible suspicious activity.")


def test_session_end_is_never_risky():
    assert not sa.is_risky("ended", "8.8.8.8", {})


def test_failure_counter():
    t = [0.0]
    f = sa.FailureCounter(3, window=600, clock=lambda: t[0])
    f.add(); f.add()
    assert not f.over()
    f.add()
    assert f.over()
    t[0] = 700   # old attempts age out
    assert not f.over()


def test_night_mode_shows_instead_of_speaking():
    assert sa.speak_now(need_help=False, night=False, night_speak="none")
    assert not sa.speak_now(need_help=False, night=True, night_speak="none")
    assert not sa.speak_now(need_help=True, night=True, night_speak="none")
    assert sa.speak_now(need_help=True, night=True, night_speak="help")


def test_late_night_signoff_is_gentle():
    for line in sa.LATE_NIGHT_SIGNOFFS:
        assert line.endswith(".") and len(line) < 60

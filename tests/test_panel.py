"""The remote panel: who may knock, the passcode, the buttons, and the link to the voice node."""
import http.client
import json
import os
import random
import stat
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
TMP = tempfile.mkdtemp()
os.environ["CHATTY_PANEL_STATUS"] = os.path.join(TMP, "voice.json")
os.environ["CHATTY_FACE_SNAP"] = os.path.join(TMP, "face.png")
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_GAMES"] = "0"
os.environ["CHATTY_DOODLES"] = "0"
import panel  # noqa: E402
import panel_link  # noqa: E402

T = 1_800_000_000.0


class Clock:
    def __init__(self, t=T):
        self.t = t

    def __call__(self):
        return self.t


# ----- who may knock -----
def test_home_network_and_tailscale_are_welcome():
    for ip in ("127.0.0.1", "::1", "100.69.130.79", "100.70.181.127", "192.168.1.20",
               "10.0.0.5", "172.20.1.1", "fd7a:115c:a1e0::1", "::ffff:192.168.1.20"):
        assert panel.allowed(ip), ip


def test_the_internet_is_not():
    for ip in ("8.8.8.8", "203.0.113.9", "2001:db8::1", "100.128.0.1", "nonsense", ""):
        assert not panel.allowed(ip), ip


def test_tailscale_only_mode():
    assert panel.allowed("100.69.130.79", "tailscale")
    assert panel.allowed("127.0.0.1", "tailscale")
    assert not panel.allowed("192.168.1.20", "tailscale")


# ----- the passcode -----
def test_new_passcode_is_friendly():
    code = panel.new_passcode()
    parts = code.split("-")
    assert len(parts) == 5 and all(p in panel.WORDS for p in parts[:4]) and parts[4].isdigit()


def test_passcode_is_stored_as_a_hash_only():
    key = panel.make_key("otter-maple-comet-sage-42")
    assert "otter" not in json.dumps(key)
    path = os.path.join(TMP, "key")
    panel.save_key(key, path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert panel.load_key(path) == key


def _doorman(clock=None, alarms=None):
    key = panel.make_key("Otter Maple")
    return panel.Doorman(key, clock=clock or Clock(), alarm=(alarms.append if alarms is not None else None))


def test_right_passcode_gives_a_cookie_that_works():
    d = _doorman()
    ok, cookie = d.login("100.1.1.1", "  otter   maple ")      # case and spaces don't matter
    assert ok and d.welcome(cookie)


def test_wrong_or_tampered_cookies_dont_work():
    d = _doorman()
    _, cookie = d.login("h", "otter maple")
    until, _, sig = cookie.partition(".")
    assert not d.welcome(f"{int(until) + 999}.{sig}")
    assert not d.welcome("garbage") and not d.welcome(None) and not d.welcome("")
    other = _doorman()                                      # a new passcode = a new secret
    assert not other.welcome(cookie)


def test_cookie_expires():
    clock = Clock()
    d = _doorman(clock)
    _, cookie = d.login("h", "otter maple")
    clock.t += 31 * 86400
    assert not d.welcome(cookie)


def test_five_wrong_guesses_lock_that_computer_and_tell_her():
    clock, alarms = Clock(), []
    d = _doorman(clock, alarms)
    for _ in range(5):
        assert not d.login("192.168.1.66", "nope")[0]
    assert d.locked("192.168.1.66") > 0 and len(alarms) == 1
    assert not d.login("192.168.1.66", "otter maple")[0]      # even the right one, for now
    assert d.login("192.168.1.20", "otter maple")[0]          # other computers are fine
    clock.t += 601
    assert d.login("192.168.1.66", "otter maple")[0]


def test_many_wrong_guesses_from_everywhere_lock_everyone():
    d = _doorman()
    for i in range(10):
        d.login(f"10.0.0.{i}", "nope")
    assert not d.login("10.0.0.200", "otter maple")[0]


def test_no_passcode_set_yet():
    d = panel.Doorman(None)
    ok, why = d.login("h", "anything")
    assert not ok and "new-passcode" in why and not d.welcome("1.2")


# ----- the buttons -----
def _press(body):
    sent = {"voice": [], "face": [], "run": []}

    def voice(kind, text=""):
        sent["voice"].append((kind, text))
        return True

    class R:
        returncode, stderr = 0, ""

    def run(cmd, **kw):
        sent["run"].append(cmd)
        return R()

    ok, msg = panel.do(body, voice=voice, face=sent["face"].append, run=run)
    return ok, msg, sent


def test_questions_go_to_her_voice():
    ok, _, sent = _press({"action": "hush", "text": "  what's   the weather? "})
    assert ok and sent["voice"] == [("hush", "what's the weather?")]
    assert not _press({"action": "ask", "text": "   "})[0]


def test_face_buttons_are_a_fixed_list():
    ok, _, sent = _press({"action": "face", "what": "doodle:rain"})
    assert ok and sent["face"] == ["doodle:rain"]
    ok, _, sent = _press({"action": "face", "what": "state:love"})
    assert not ok and sent["face"] == []


def test_note_and_brightness():
    _, _, sent = _press({"action": "note", "text": "Back at 6, feed Tiny!"})
    assert sent["face"] == ["notice:Back at 6, feed Tiny!"]
    _, _, sent = _press({"action": "light", "level": 7})
    assert sent["face"] == ["light:1.00"]
    _, _, sent = _press({"action": "light", "level": "auto"})
    assert sent["face"] == ["light:auto"]
    assert not _press({"action": "light", "level": "bright"})[0]


def test_only_voice_and_face_can_be_restarted():
    ok, _, sent = _press({"action": "restart", "service": "voice"})
    assert ok and sent["run"] == [["sudo", "-n", "/usr/bin/systemctl", "restart", "chatty-voice"]]
    ok, _, sent = _press({"action": "restart", "service": "ssh; reboot"})
    assert not ok and sent["run"] == []


def test_unknown_button():
    assert not _press({"action": "water the plants"})[0]


# ----- the link to the voice node -----
def _link(mode="full"):
    clock = Clock()
    p = panel_link.Panel(path=os.path.join(TMP, "v.json"), clock=clock, log_mode=lambda: mode)
    return p, clock


def test_requests_need_the_token():
    p, _ = _link()
    assert p.take(panel_link.build(p.token, "ask", "what time is it"))
    assert not p.take(panel_link.build("0" * 32, "ask", "shut down"))
    assert not p.take(f"panel:{p.token}:format:disk")
    assert not p.take("wake")
    assert p.next("sleep") == ("ask", "what time is it") and p.next("sleep") is None


def test_while_waiting_for_a_yes_only_yes_no_go_through():
    p, _ = _link()
    p.take(panel_link.build(p.token, "ask", "weather"))
    p.take(panel_link.build(p.token, "yes"))
    assert p.next("confirm") == ("yes", "")
    assert p.next("confirm") is None
    assert p.next("sleep") == ("ask", "weather")


def test_a_late_yes_is_dropped():
    p, _ = _link()
    p.take(panel_link.build(p.token, "yes"))
    assert p.next("sleep") is None and p.waiting == []


def test_old_requests_are_dropped():
    p, clock = _link()
    p.take(panel_link.build(p.token, "say", "hello"))
    clock.t += 61
    assert p.next("sleep") is None


def test_quiet_turn_and_lines():
    p, _ = _link()
    with p.turn(quiet=True):
        assert p.hush
        p.heard("what time is it")
        p.said("It's 4:05 AM.")
    assert not p.hush and p.last_quiet
    assert [x["who"] for x in p.lines] == ["you", "chatty"] and all(x["panel"] for x in p.lines)


def test_private_log_mode_only_shows_panel_lines():
    p, _ = _link("private")
    p.heard("something said out loud in the kitchen")
    with p.turn():
        p.heard("weather")
        p.said("Sunny.")
    assert [x["text"] for x in p.lines] == ["weather", "Sunny."]


def test_status_file_is_owner_only_and_the_token_stays_on_the_pi():
    p, _ = _link()
    p.said("hello")
    assert p.write("sleep", {"nodes": []})
    assert stat.S_IMODE(os.stat(p.path).st_mode) == 0o600
    assert json.load(open(p.path))["token"] == p.token
    assert not p.write("sleep")                   # not again so soon
    s = panel.status(panel.Cache(), voice_file=p.path, now=T + 1)
    assert "token" not in s["voice"] and s["voice_ok"] and s["mode"] == "sleep"
    assert s["voice"]["lines"][0]["text"] == "hello"


def test_stale_status_means_her_voice_is_down():
    p, _ = _link()
    p.write("sleep", force=True)
    s = panel.status(panel.Cache(), voice_file=p.path, now=T + 120)
    assert not s["voice_ok"] and "isn't answering" in s["mode_text"]


# ----- the web server itself -----
def _server():
    panel.Handler.doorman = panel.Doorman(panel.make_key("otter maple"))
    panel.Handler.cache = panel.Cache()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _req(httpd, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", panel.HEADER: "1"} if body is not None else {}
    h.update(headers or {})
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    out = r.status, dict(r.getheaders()), r.read()
    c.close()
    return out


def test_web_login_and_buttons():
    httpd = _server()
    try:
        code, hdrs, page = _req(httpd, "GET", "/")
        assert code == 200 and b"Chatty" in page and "frame-ancestors 'none'" in hdrs["Content-Security-Policy"]
        assert _req(httpd, "GET", "/api/status")[0] == 401
        assert _req(httpd, "POST", "/api/do", {"action": "wake"})[0] == 401
        code, hdrs, _ = _req(httpd, "POST", "/api/login", {"passcode": "otter maple"})
        assert code == 200
        cookie = hdrs["Set-Cookie"].split(";")[0]
        assert "HttpOnly" in hdrs["Set-Cookie"] and "SameSite=Strict" in hdrs["Set-Cookie"]
        code, _, body = _req(httpd, "GET", "/api/status", headers={"Cookie": cookie})
        assert code == 200 and json.loads(body)["ok"]
        # a button without the panel's header (like a form on someone else's page) is refused
        c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        c.request("POST", "/api/do", body="action=rest",
                  headers={"Cookie": cookie, "Content-Type": "application/x-www-form-urlencoded"})
        assert c.getresponse().status == 400
        c.close()
        code, _, body = _req(httpd, "POST", "/api/do", {"action": "face", "what": "calm"},
                             headers={"Cookie": cookie})
        assert code == 200 and json.loads(body)["ok"]
        assert _req(httpd, "GET", "/../../etc/passwd", headers={"Cookie": cookie})[0] == 404
    finally:
        httpd.shutdown()


# ----- the face and the screen -----
def test_face_calm_and_panel_info():
    from face_model import FaceModel
    face = FaceModel(800, 480, rng=random.Random(1))
    face.add_notice("User pi logged on, from Tailscale", now=T)
    import doodles
    face.doodle = doodles.Doodle(face.rng, T, "spiro")
    assert face.activity().startswith("doodle")
    face.calm(T + 1)
    assert face.activity() == "" and face.notices          # notices stay until cleared
    info = face.panel_info()
    assert info["notices"] == ["User pi logged on, from Tailscale"] and info["state"] == "idle"


def test_brightness_hold():
    import backlight
    d = backlight.Dimmer(is_night=lambda n: False)
    d.hold(0.5, T)
    assert d.target("idle", T, T + 10) == 0.5
    assert d.target("speaking", T, T + 10) == 0.5
    assert d.target("idle", T, T + 3 * 3600) == backlight.IDLE_LEVEL or not backlight.ENABLED
    d.hold(0.1, T)
    d.hold(None, T)
    assert d.target("idle", T, T + 10) == 1.0 or not backlight.ENABLED


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)


def test_typed_math_keeps_its_signs():
    import ast
    import re
    src = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")
    tree = ast.parse(open(src).read())
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "typed_math"]
    ns = {"re": re}
    exec(compile(ast.Module(body=fn, type_ignores=[]), src, "exec"), ns)
    tm = ns["typed_math"]
    assert tm("What is the sum of 1+1?") == "What is the sum of 1 plus 1?"
    assert tm("10 - 3") == "10 minus 3"
    assert tm("6*7") == "6 times 7"
    assert tm("8/2") == "8 divided by 2"
    assert tm("set a timer for 10 minutes") == "set a timer for 10 minutes"
    assert tm("rain-node") == "rain-node"

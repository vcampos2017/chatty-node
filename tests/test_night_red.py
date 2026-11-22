import os
import random
import sys
import time

os.environ.pop("CHATTY_NIGHT_RED", None)
os.environ.pop("CHATTY_NIGHT_RED_BRIGHT", None)
os.environ.pop("CHATTY_NIGHT_RED_COLOR", None)
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_GAMES"] = "0"
os.environ["CHATTY_DOODLES"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import night_red  # noqa: E402
import panel  # noqa: E402
from face_model import FaceModel  # noqa: E402

T = 1_000_000.0
SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def test_red_at_night_and_after_the_wind_down():
    day = night_red.NightRed(is_night=lambda now: False)
    assert not day.on(T)
    assert day.on(T, bed_until=T + 3600)            # bedtime came before 10 PM
    assert not day.on(T + 3601, bed_until=T + 3600)
    assert night_red.NightRed(is_night=lambda now: True).on(T)


def test_red_alert_always_wins():
    for mode in ("1", "always"):
        n = night_red.NightRed(is_night=lambda now: True, mode=mode)
        n.set("on", T)
        assert n.on(T) and not n.on(T, red_alert=True)


def test_asked_for_on_off_and_auto():
    n = night_red.NightRed(is_night=lambda now: True)
    n.set("off", T)
    assert not n.on(T + 60)                        # off for tonight
    assert n.manual and n.manual[1] > T            # until the morning
    assert n.on(n.manual[1] + 1)                   # the next night it's back
    n.set("on", T)
    assert n.on(T)
    n.set("auto", T)
    assert n.manual is None
    day = night_red.NightRed(is_night=lambda now: False)
    day.set("on", T)
    assert day.on(T + 60)                          # asked for in the daytime: on until morning
    assert not night_red.NightRed(is_night=lambda now: True, mode="0").on(T)


def test_brightness_is_gentle_unless_the_panel_picked_one():
    assert night_red.NightRed.cap(1.0, held=False) == night_red.BRIGHT
    assert night_red.NightRed.cap(0.06, held=False) == 0.06
    assert night_red.NightRed.cap(0.9, held=True) == 0.9


def test_colors_become_one_red():
    assert night_red.redden_rgb(255, 255, 255) == (255, 0, 0)
    assert night_red.redden_rgb(0, 0, 0) == (0, 0, 0)
    blue = night_red.redden_rgb(70, 130, 255)
    assert blue[0] > 150 and blue[1:] == (0, 0)    # her blue parts don't vanish
    assert night_red.redden_rgb(200, 200, 200, color=(255, 40, 0))[1] > 0


def test_voice_requests():
    want = {"turn on the red light": "on", "night vision": "on", "night vision on": "on",
            "submarine mode": "on", "dark sky mode": "on", "go red": "on",
            "turn on the night light": "on",
            "turn off the red light": "off", "red light off": "off", "show me your true colors": "off",
            "red light automatic": "auto", "set the red light to auto": "auto",
            "why is your screen red": "why", "what is night vision": "why"}
    for text, kind in want.items():
        assert night_red.request(text) == kind, text
    for text in ("red alert", "is there a red alert", "test the red alert", "turn on the light",
                 "is it night", "what is night mode", "what color is a red light", ""):
        assert night_red.request(text) is None, text
    for kind in ("on", "off", "auto", "why"):
        assert night_red.reply(kind)


def test_voice_node_and_face_know_it():
    voice = open(os.path.join(SRC, "chatty_voice_node.py")).read()
    assert "night_red.request(prompt)" in voice and "face.night_red(glow)" in voice
    face = open(os.path.join(SRC, "chatty_face.py")).read()
    assert 'key == "nightred"' in face and "redden_surface(screen)" in face
    # Red Alert's full brightness comes after the gentle red cap
    assert face.index("red.cap(") < face.index("target = backlight.FULL          # Red Alert")


def test_panel_buttons_and_info():
    for what in ("nightred:on", "nightred:off", "nightred:auto"):
        sent = []
        ok, _ = panel.do({"action": "face", "what": what}, face=sent.append)
        assert ok and sent == [what]
    f = FaceModel(800, 480, rng=random.Random(1))
    assert f.panel_info()["night_red"] is False


def test_pygame_fallback_without_numpy():
    calls = []

    class Surf:
        def blit(self, other, at):
            calls.append("blit")

        def fill(self, color, special_flags=0):
            calls.append(("fill", color))

    import types
    fake = types.SimpleNamespace(BLEND_RGB_MULT=1, transform=types.SimpleNamespace(grayscale=lambda s: s))
    sys.modules["pygame"] = fake
    try:
        night_red._redden_pygame(Surf(), (255, 0, 0))
        night_red.redden_surface(object())       # never raises
    finally:
        del sys.modules["pygame"]
    assert calls == ["blit", ("fill", (255, 0, 0))]


def test_numpy_matches_the_pixel_rule():
    try:
        import numpy as np
    except ImportError:
        return                                    # the Pi has numpy; this is just a check
    rng = random.Random(4)
    pix = [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(500)]
    pix += [(255, 255, 255), (0, 0, 0), (0, 0, 255)]
    arr = np.array(pix, dtype=np.uint8).reshape(1, -1, 3)
    night_red.red_array(arr, (255, 0, 0))
    for (r, g, b), got in zip(pix, arr[0]):
        want = night_red.redden_rgb(r, g, b)
        assert abs(int(got[0]) - want[0]) <= 2 and got[1] == 0 and got[2] == 0


def test_next_morning_is_after_now():
    now = time.time()
    n = night_red.NightRed(is_night=lambda t: True)
    n.set("off", now)
    assert now < n.manual[1] <= now + 24 * 3600


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

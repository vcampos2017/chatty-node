import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import backlight  # noqa: E402

T = 1_000_000.0


def test_full_while_talking_soft_when_idle_in_the_day():
    d = backlight.Dimmer(is_night=lambda now: False)
    assert d.target("speaking", T - 9999, T) == 1.0
    assert d.target("idle", T - 60, T) == 1.0
    assert d.target("idle", T - 400, T) == backlight.IDLE_LEVEL
    assert d.target("sleepy", T - 4000, T) == backlight.IDLE_LEVEL


def test_dark_at_night_and_when_resting():
    night = backlight.Dimmer(is_night=lambda now: True)
    assert night.target("idle", T - 10, T) == 1.0          # just talked: still lit
    assert night.target("idle", T - 60, T) == backlight.NIGHT_LEVEL
    assert night.target("listening", T - 600, T) == 1.0    # "Hey Chatty" lights it up
    day = backlight.Dimmer(is_night=lambda now: False)
    assert day.target("resting", T - 60, T) == backlight.NIGHT_LEVEL


def test_a_poke_lights_it_for_a_while():
    d = backlight.Dimmer(is_night=lambda now: True)
    d.poke(T)
    assert d.target("idle", T - 999, T + 5) == 1.0
    assert d.target("idle", T - 999, T + 60) == backlight.NIGHT_LEVEL


def _fake_sysfs(tmp, max_b=255, now=255):
    path = os.path.join(tmp, "10-0045")
    os.makedirs(path)
    open(os.path.join(path, "max_brightness"), "w").write(f"{max_b}\n")
    open(os.path.join(path, "brightness"), "w").write(f"{now}\n")
    return path


def _read(path):
    return int(open(os.path.join(path, "brightness")).read())


def test_fades_instead_of_jumping():
    with tempfile.TemporaryDirectory() as tmp:
        path = _fake_sysfs(tmp)
        b = backlight.Backlight(path)
        assert b.ok and b.level == 1.0
        b.step(0.35, 0.25)
        assert 0.7 < b.level < 0.8 and 180 < _read(path) < 200
        for _ in range(10):
            b.step(0.35, 0.25)
        assert _read(path) == round(0.35 * 255) and not b.busy(0.35)


def test_never_writes_zero_unless_asked_and_small_panels_work():
    with tempfile.TemporaryDirectory() as tmp:
        path = _fake_sysfs(tmp, max_b=31, now=31)
        b = backlight.Backlight(path)
        for _ in range(20):
            b.step(0.01, 0.25)
        assert _read(path) == 1
        for _ in range(20):
            b.step(0.0, 0.25)
        assert _read(path) == 0


def test_no_permission_turns_it_off_quietly():
    with tempfile.TemporaryDirectory() as tmp:
        path = _fake_sysfs(tmp)
        os.chmod(os.path.join(path, "brightness"), 0o444)
        b = backlight.Backlight(path)
        if os.geteuid() != 0:          # root can write anyway
            b.step(0.3, 0.5)
            assert not b.ok
        b2 = backlight.Backlight(os.path.join(tmp, "missing"))
        assert not b2.ok
        b2.step(0.3, 0.5)              # no crash


def test_off_switch():
    old = backlight.ENABLED
    backlight.ENABLED = False
    try:
        assert backlight.Dimmer(is_night=lambda n: True).target("idle", 0, T) == 1.0
    finally:
        backlight.ENABLED = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

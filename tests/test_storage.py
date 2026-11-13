"""Safe JSON saves (src/storage.py)."""
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import storage  # noqa: E402


def test_round_trip_and_owner_only():
    path = os.path.join(tempfile.mkdtemp(), "new", "folder", "x.json")
    storage.save_json(path, {"a": [1, 2]})
    assert storage.load_json(path) == {"a": [1, 2]}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert os.listdir(os.path.dirname(path)) == ["x.json"]      # no temp file left


def test_missing_or_broken_file_gives_the_default():
    folder = tempfile.mkdtemp()
    assert storage.load_json(os.path.join(folder, "nope.json"), []) == []
    bad = os.path.join(folder, "bad.json")
    with open(bad, "w") as f:
        f.write("{half a fi")
    assert storage.load_json(bad, {}) == {}


def test_a_failed_save_keeps_the_old_file():
    path = os.path.join(tempfile.mkdtemp(), "x.json")
    storage.save_json(path, {"old": True})
    try:
        storage.save_json(path, {"bad": object()})              # not JSON
        raise AssertionError("expected an error")
    except TypeError:
        pass
    assert storage.load_json(path) == {"old": True}
    assert os.listdir(os.path.dirname(path)) == ["x.json"]


def test_modules_use_it():
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    for name in ("alerts", "bedtime", "chess_mail", "chess_match", "memory", "morning_weather",
                 "rain_hold", "rain_watch", "timers", "trickster", "voices"):
        text = open(os.path.join(src, name + ".py")).read()
        assert "storage.save_json(" in text, name
        assert ".write_text(json.dumps" not in text, name


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

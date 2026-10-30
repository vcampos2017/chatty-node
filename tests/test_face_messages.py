import os
import random
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_GAMES"] = "0"
os.environ.pop("CHATTY_NOTICE_HOURS", None)
os.environ.pop("CHATTY_CAPTION_SECONDS", None)
import face_model  # noqa: E402
from face_model import FaceModel  # noqa: E402

T = 1_000_000.0


def _face():
    face = FaceModel(800, 480, rng=random.Random(1))
    face.last_activity = T
    return face


def test_notices_expire_after_max_age():
    face = _face()
    face.add_notice("User pi logged on, from Tailscale", now=T)
    face.update(0.1, T + 11 * 3600)
    assert len(face.notices) == 1
    face.update(0.1, T + 12 * 3600 + 1)
    assert face.notices == []


def test_only_old_notices_expire():
    face = _face()
    face.add_notice("old one", now=T)
    face.add_notice("new one", now=T + 6 * 3600)
    face.update(0.1, T + 13 * 3600)
    assert [text for _, text in face.notices] == ["new one"]


def test_repeated_notice_replaces_older_copy():
    face = _face()
    face.add_notice("Possible suspicious activity", now=T)
    face.add_notice("SSH session ended", now=T + 10)
    face.add_notice("Possible suspicious activity", now=T + 20)
    assert face.notices == [(T + 10, "SSH session ended"), (T + 20, "Possible suspicious activity")]


def test_tap_still_dismisses_notices():
    face = _face()
    face.add_notice("hello", now=T)
    assert face.handle_tap((10, 10), now=T + 1)
    assert face.notices == []


def test_caption_clears_itself_when_left_behind():
    face = _face()
    face.set_caption("what time is it", now=T)
    face.update(0.1, T + 60)
    assert face.caption == "what time is it"
    face.update(0.1, T + 121)
    assert face.caption == ""


def test_newer_caption_restarts_the_clock():
    face = _face()
    face.set_caption("what time", now=T)
    face.set_caption("what time is it", now=T + 100)
    face.update(0.1, T + 150)
    assert face.caption == "what time is it"


def test_zero_turns_notice_expiry_off():
    old = face_model.NOTICE_MAX_AGE
    face_model.NOTICE_MAX_AGE = 0
    try:
        face = _face()
        face.add_notice("keep me", now=T)
        face.update(0.1, T + 30 * 24 * 3600)
        assert len(face.notices) == 1
    finally:
        face_model.NOTICE_MAX_AGE = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            fn()
            print("ok", name)

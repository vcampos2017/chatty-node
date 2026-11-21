"""The IFTTT phone buzz (src/phone.py)."""
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import phone  # noqa: E402

sent = []


class _Ok:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, timeout=None):
    sent.append(req)
    if "bad" in os.environ.get("IFTTT_KEY", ""):
        raise phone.urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO())
    return _Ok()


phone.urllib.request.urlopen = _fake_urlopen
import urllib.error  # noqa: E402,F401  (so phone.urllib.error exists)


def test_no_key_no_buzz():
    os.environ.pop("IFTTT_KEY", None)
    sent.clear()
    assert phone.send("hi") is False and sent == []


def test_sends_value1_to_the_event():
    os.environ["IFTTT_KEY"] = "k123"
    sent.clear()
    assert phone.send("Soil is dry", event="rain_detected")
    assert sent[0].full_url.endswith("/trigger/rain_detected/with/key/k123")
    assert json.loads(sent[0].data) == {"value1": "Soil is dry"}
    phone.send("x")
    assert "/trigger/chatty_alert/" in sent[1].full_url


def test_failure_never_raises_or_prints_the_key(capsys=None):
    os.environ["IFTTT_KEY"] = "bad-key-secret"
    out = io.StringIO()
    real, sys.stdout = sys.stdout, out
    try:
        assert phone.send("x") is False
    finally:
        sys.stdout = real
    assert "401" in out.getvalue() and "secret" not in out.getvalue()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

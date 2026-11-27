import os
import stat
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import whisper_stt  # noqa: E402

RATE = 16000


def _speech(seconds_quiet=1.0, seconds_loud=1.0):
    quiet = np.zeros(int(RATE * seconds_quiet), dtype=np.int16)
    t = np.arange(int(RATE * seconds_loud)) / RATE
    loud = (8000 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)
    return np.concatenate([quiet, loud, quiet]).tobytes()


def test_trim_keeps_speech_and_a_little_padding():
    clip = whisper_stt.trim_silence(_speech(), RATE)
    secs = len(clip) / 2 / RATE
    assert 1.0 <= secs <= 1.0 + 2 * whisper_stt.PAD + 0.1


def test_trim_of_silence_is_empty():
    assert whisper_stt.trim_silence(bytes(RATE * 2), RATE) == b""


def test_clean_drops_annotations():
    assert whisper_stt.clean(" [BLANK_AUDIO]\n What's the weather? (music)\n") == "What's the weather?"


def test_hallucination_guard():
    assert not whisper_stt.plausible("Thank you.", "what time is it in tokyo")
    assert whisper_stt.plausible("Thank you.", "thank you")
    assert whisper_stt.plausible("What time is it in Tokyo?", "what time is it to key oh")
    assert not whisper_stt.plausible(" ".join(["word"] * 40), "hi there")


def test_audio_ctx_scales_with_clip():
    assert whisper_stt.audio_ctx(2) == 256
    assert whisper_stt.audio_ctx(10) == 564
    assert whisper_stt.audio_ctx(60) == 1500


def _fake_whisper(tmp_path, script_body):
    exe = tmp_path / "whisper-cli"
    exe.write_text("#!/bin/sh\n" + script_body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    model = tmp_path / "ggml-base.en.bin"
    model.write_bytes(b"x")
    return str(exe), str(model)


def test_transcribe_uses_whisper_and_deletes_clip(tmp_path, monkeypatch):
    seen = tmp_path / "args.txt"
    exe, model = _fake_whisper(tmp_path, f'echo "$@" > {seen}\n'
                                         'for a in "$@"; do case "$a" in *.wav) cp "$a" '
                                         f'{tmp_path}/copy.wav;; esac; done\n'
                                         'echo " Is the greenhouse thirsty?"\n')
    monkeypatch.setattr(whisper_stt, "BIN", exe)
    monkeypatch.setattr(whisper_stt, "MODEL", model)
    monkeypatch.setattr(whisper_stt, "ENABLED", True)
    text, _ = whisper_stt.transcribe(_speech(), RATE, "is the green house thirsty")
    assert text == "Is the greenhouse thirsty?"
    args = seen.read_text()
    assert "-l en" in args and "-nt" in args and "-ac 256" in args
    wav_path = [a for a in args.split() if a.endswith(".wav")][0]
    assert not os.path.exists(wav_path)          # the clip never lingers
    with wave.open(str(tmp_path / "copy.wav")) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1


def test_transcribe_falls_back_when_whisper_fails(tmp_path, monkeypatch):
    exe, model = _fake_whisper(tmp_path, "exit 3\n")
    monkeypatch.setattr(whisper_stt, "BIN", exe)
    monkeypatch.setattr(whisper_stt, "MODEL", model)
    monkeypatch.setattr(whisper_stt, "ENABLED", True)
    assert whisper_stt.transcribe(_speech(), RATE, "hello")[0] is None


def test_transcribe_falls_back_when_too_slow(tmp_path, monkeypatch):
    exe, model = _fake_whisper(tmp_path, "sleep 5\n")
    monkeypatch.setattr(whisper_stt, "BIN", exe)
    monkeypatch.setattr(whisper_stt, "MODEL", model)
    monkeypatch.setattr(whisper_stt, "ENABLED", True)
    monkeypatch.setattr(whisper_stt, "TIMEOUT", 0.5)
    assert whisper_stt.transcribe(_speech(), RATE, "hello")[0] is None


def test_not_installed_means_vosk(monkeypatch):
    monkeypatch.setattr(whisper_stt, "BIN", "/nope/whisper-cli")
    assert not whisper_stt.available()
    assert whisper_stt.transcribe(_speech(), RATE, "hello") == (None, 0.0)
    assert "not installed" in whisper_stt.status()


# ---- hearing Vincent better (2026-11-27): vocabulary, soundalikes, borrowed ears ----

import json as _json  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402

import words  # noqa: E402


def test_prompt_knows_her_skill_words():
    for w in ("square root", "percent", "Morse code", "Mandelbrot", "greenhouse", "Tiny"):
        assert w.lower() in whisper_stt.DEFAULT_PROMPT.lower()
    assert len(whisper_stt.DEFAULT_PROMPT.split()) < 45     # short: read on every question


def test_square_ring_is_a_square_root():
    fix = words.fix_heard
    assert fix("whats the square ring") == "whats the square root"
    assert fix("whats the square ring of 81") == "whats the square root of 81"
    assert fix("what is the square route of eighty one") == "what is the square root of eighty one"
    assert fix("square rude 49") == "square root 49"
    # nothing else is touched
    assert fix("put the ring in the square box") == "put the ring in the square box"
    assert fix("is the square room big") == "is the square room big"
    assert fix("whats the weather") == "whats the weather"
    assert fix("") == ""


def test_voice_node_fixes_what_she_heard():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")).read()
    i = src.index("def sharpen(")
    body = src[i:src.index("\nclass RedCutIn", i)]
    assert body.count("fix_heard(") == 3          # Vosk-only, Whisper unsure, and Whisper's words


def test_borrowed_ears_only_at_home():
    ok = whisper_stt.home_only
    assert ok("http://my-dell:8178") and ok("http://dell.local:8178")
    assert ok("http://dell.tail1234.ts.net:8178")
    assert ok("http://100.101.102.103:8178") and ok("http://192.168.1.20:8178")
    assert ok("http://10.0.0.5:8178") and ok("http://127.0.0.1:8178")
    assert not ok("http://8.8.8.8:8178")
    assert not ok("https://whisper.example.com")
    assert not ok("ftp://my-dell")
    assert not ok("")


def test_level_db():
    assert whisper_stt.level_db(_speech()) > -13         # 8000 of 32768 is about -12 dB
    assert whisper_stt.level_db(bytes(200)) < -80


class _FakeServer:
    """A stand-in for whisper.cpp's whisper-server on the Dell."""

    def __init__(self, text="What's the square root of 81?", status=200):
        seen = self.seen = {}

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                seen["path"] = self.path
                seen["body"] = self.rfile.read(n)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(_json.dumps({"text": text}).encode())

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_borrowed_ears_answer_first(monkeypatch):
    srv = _FakeServer()
    try:
        monkeypatch.setattr(whisper_stt, "ENABLED", True)
        monkeypatch.setattr(whisper_stt, "BIN", "/nope/whisper-cli")   # not even on the Pi
        monkeypatch.setattr(whisper_stt, "REMOTE_URL", srv.url)
        monkeypatch.setattr(whisper_stt, "_remote_down_until", 0.0)
        assert whisper_stt.available()
        text, _ = whisper_stt.transcribe(_speech(), RATE, "whats the square ring")
        assert text == "What's the square root of 81?"
        assert srv.seen["path"] == "/inference"
        body = srv.seen["body"]
        assert b'name="file"' in body and b"RIFF" in body and b"square root" in body
        assert "borrowed ears first" in whisper_stt.status()
    finally:
        srv.close()


def test_borrowed_ears_down_means_the_pi(tmp_path, monkeypatch):
    exe, model = _fake_whisper(tmp_path, 'echo " Is it raining?"\n')
    monkeypatch.setattr(whisper_stt, "BIN", exe)
    monkeypatch.setattr(whisper_stt, "MODEL", model)
    monkeypatch.setattr(whisper_stt, "ENABLED", True)
    monkeypatch.setattr(whisper_stt, "REMOTE_URL", "http://127.0.0.1:9")   # nobody home
    monkeypatch.setattr(whisper_stt, "REMOTE_TIMEOUT", 1.0)
    monkeypatch.setattr(whisper_stt, "_remote_down_until", 0.0)
    text, _ = whisper_stt.transcribe(_speech(), RATE, "is it raining")
    assert text == "Is it raining?"
    assert whisper_stt._remote_down_until > 0          # resting: not asked again for a while
    srv = _FakeServer(text="never asked")
    try:
        monkeypatch.setattr(whisper_stt, "REMOTE_URL", srv.url)
        assert whisper_stt.transcribe(_speech(), RATE, "is it raining")[0] == "Is it raining?"
        assert "path" not in srv.seen
    finally:
        srv.close()


def test_public_address_is_never_used(monkeypatch):
    monkeypatch.setattr(whisper_stt, "ENABLED", True)
    monkeypatch.setattr(whisper_stt, "BIN", "/nope/whisper-cli")
    monkeypatch.setattr(whisper_stt, "REMOTE_URL", "https://whisper.example.com")
    assert not whisper_stt.available()
    assert "ignored" in whisper_stt.status()
    assert whisper_stt.ask_remote(_speech(), RATE) is None



if __name__ == "__main__":
    # No pytest on the Pi or in the cloud workspace: tiny stand-ins for its helpers.
    import inspect
    import pathlib
    import tempfile

    class _Patch:
        def __init__(self):
            self.undo = []

        def setattr(self, obj, name, value):
            self.undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, value)

        def restore(self):
            for obj, name, value in reversed(self.undo):
                setattr(obj, name, value)

    for name, fn in list(globals().items()):
        if not name.startswith("test_"):
            continue
        patch = _Patch()
        with tempfile.TemporaryDirectory() as d:
            kwargs = {"tmp_path": pathlib.Path(d), "monkeypatch": patch}
            try:
                fn(**{k: kwargs[k] for k in inspect.signature(fn).parameters})
            finally:
                patch.restore()
        print("ok", name)

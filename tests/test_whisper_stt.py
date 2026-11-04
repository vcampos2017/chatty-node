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

#!/usr/bin/env python3
"""Hearing test: say one sentence and see how each of Chatty's ears hears it.

Run on the Pi, from the repo folder. The voice service holds the mic, so stop it
first and start it again after:
    sudo systemctl stop chatty-voice
    python3 scripts/hearing_test.py
    sudo systemctl start chatty-voice

It records SECONDS (default 5) from the mic into RAM (/dev/shm), then shows:
  - how loud you were (peak level; about -30 dB or lower = the mic hears you faintly)
  - whisper.cpp on the Pi with her usual settings, then with beam 5 (a little more
    careful), then with any other model in ~/whisper.cpp/models (small.en, tiny.en...)
  - the borrowed ears (CHATTY_WHISPER_URL), when set
with the seconds each one took. The clip is deleted at the end; nothing is saved.

Options: python3 scripts/hearing_test.py [seconds] [--wav some.wav]
"""
import glob
import os
import subprocess
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import urllib.parse  # noqa: E402

import settings  # noqa: E402

settings.load()   # /etc/chatty/secrets.env, read before whisper_stt reads its settings
import whisper_stt  # noqa: E402

RATE = 16000
DEVICE = os.getenv("CHATTY_CAPTURE_DEVICE", "plughw:CARD=PowerConf,DEV=0")


def record(seconds: float) -> bytes:
    print(f"Recording {seconds:.0f} seconds: speak now (for example 'what is the square root of 81')")
    r = subprocess.run(["arecord", "-D", DEVICE, "-f", "S16_LE", "-c", "1", "-r", str(RATE),
                        "-t", "raw", "-d", str(int(seconds))], capture_output=True)
    if r.returncode != 0:
        print("Couldn't record:", r.stderr.decode(errors="replace").strip()[-200:])
        print("(Is chatty-voice still running? sudo systemctl stop chatty-voice)")
        sys.exit(1)
    return r.stdout


def run_local(clip: bytes, model: str, beam: int):
    path = f"/dev/shm/chatty_hearing_{os.getpid()}.wav"
    with open(path, "wb") as f:
        f.write(whisper_stt.wav_bytes(clip, RATE))
    old = whisper_stt.MODEL, whisper_stt.BEAM
    whisper_stt.MODEL, whisper_stt.BEAM = model, beam
    try:
        started = time.time()
        r = subprocess.run(whisper_stt.command(path, len(clip) / 2 / RATE),
                           capture_output=True, text=True, timeout=120)
        return whisper_stt.clean(r.stdout), time.time() - started
    finally:
        whisper_stt.MODEL, whisper_stt.BEAM = old
        os.remove(path)


def main():
    args = sys.argv[1:]
    if "--wav" in args:
        with wave.open(args[args.index("--wav") + 1], "rb") as w:
            if w.getframerate() != RATE or w.getnchannels() != 1:
                sys.exit("The wav must be 16 kHz mono.")
            clip = w.readframes(w.getnframes())
    else:
        secs = float(args[0]) if args and args[0].replace(".", "").isdigit() else 5.0
        clip = record(secs)
    clip = whisper_stt.trim_silence(clip, RATE)
    if not clip:
        sys.exit("I only heard silence. Is the mic muted, or too far away?")
    level = whisper_stt.level_db(clip)
    note = ("good" if -20 <= level <= -1 else "faint: move closer or raise the mic level"
            if level < -20 else "very loud: it may be clipping")
    print(f"\nYour voice: peak {level:.0f} dB ({note}), {len(clip) / 2 / RATE:.1f} s of speech\n")

    if whisper_stt.local_on():
        models = [whisper_stt.MODEL] + sorted(
            m for m in glob.glob(os.path.join(os.path.dirname(whisper_stt.MODEL), "ggml-*.bin"))
            if m != whisper_stt.MODEL and "for-tests" not in m)
        tries = [(whisper_stt.MODEL, whisper_stt.BEAM, "her usual")]
        if whisper_stt.BEAM < 5:
            tries.append((whisper_stt.MODEL, 5, "beam 5"))
        tries += [(m, whisper_stt.BEAM, "") for m in models[1:]]
        for model, beam, label in tries:
            text, took = run_local(clip, model, beam)
            name = os.path.basename(model).replace("ggml-", "").replace(".bin", "")
            print(f"  Pi, {name}, beam {beam}{' (' + label + ')' if label else ''}: "
                  f"{took:4.1f} s  {text!r}")
    else:
        print("  (whisper.cpp isn't installed on the Pi)")

    if whisper_stt.remote_on():
        whisper_stt._remote_down_until = 0.0
        started = time.time()
        text = whisper_stt.ask_remote(clip, RATE)
        host = urllib.parse.urlparse(whisper_stt.REMOTE_URL).hostname
        print(f"  Borrowed ears ({host}): {time.time() - started:4.1f} s  "
              f"{whisper_stt.clean(text) if text is not None else 'no answer'!r}")
    elif whisper_stt.REMOTE_URL:
        print("  (CHATTY_WHISPER_URL isn't a home or Tailscale address, so it's not used)")
    print("\nDone. The clip is gone. Start her again: sudo systemctl start chatty-voice")


if __name__ == "__main__":
    main()

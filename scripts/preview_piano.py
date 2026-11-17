"""
Preview Chatty playing the piano as PNGs (Pillow, no pygame): the keyboard on her face
with keys lit, notes floating up, and her eyes following the melody. Also writes the
song as a .wav so you can hear the piano sound on any computer.
Usage: python3 scripts/preview_piano.py [output_dir] [song id] [seconds into the song ...]
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("CHATTY_NIGHT_MODE", "0")    # full colors, whatever time it is
import piano  # noqa: E402
from face_model import FaceModel  # noqa: E402
from preview_face import PILCanvas  # noqa: E402

W, H = 800, 480
T = 1_000_000.0


def frame(key, seconds):
    face = FaceModel(W, H, rng=random.Random(3))
    face.set_rec("off")
    face.next_blink = 1e12
    face.set_state("piano", now=T)
    face.set_piano(f"{T}:{key}", now=T)
    at = T + seconds
    steps = max(1, int(seconds * 30))
    for i in range(steps + 1):
        face.update(1 / 30, T + i * seconds / steps)
    c = PILCanvas(W, H)
    face.draw(c, at)
    return c.image()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "piano_preview"
    key = sys.argv[2] if len(sys.argv) > 2 else "ode-to-joy"
    song = piano.load(key)
    if not song:
        sys.exit(f"No song called {key!r}. Try: python3 src/piano.py --list")
    times = [float(x) for x in sys.argv[3:]] or [song.seconds * 0.3, song.seconds * 0.62]
    os.makedirs(out, exist_ok=True)
    for i, sec in enumerate(times, 1):
        path = os.path.join(out, f"piano-{key}-{i}.png")
        frame(key, sec).save(path)
        print("wrote", path)
    print("wrote", piano.write_wav(song, os.path.join(out, f"{key}.wav")))

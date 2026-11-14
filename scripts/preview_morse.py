"""
Preview Chatty sending Morse code as PNGs (Pillow, no pygame): the telegraph tape,
the lamp, and her eyes flashing with a beep.
Usage: python3 scripts/preview_morse.py [output_dir] [text]
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("CHATTY_NIGHT_MODE", "0")    # full colors, whatever time it is
import morse  # noqa: E402
from face_model import FaceModel  # noqa: E402
from preview_face import PILCanvas  # noqa: E402

W, H = 800, 480
T = 1_000_000.0


def frame(code, dits, caption="say hello in morse"):
    """The face `dits` dits into sending `code`."""
    unit = morse.unit_seconds()
    face = FaceModel(W, H, rng=random.Random(3))
    face.set_rec("off")
    face.next_blink = 1e12
    face.set_caption(caption, now=T)
    face.set_state("morse", now=T)
    face.set_morse(f"{T}:{unit}:{code}", now=T)
    at = T + dits * unit
    steps = max(1, int((at - T) * 30))
    for i in range(steps + 1):
        face.update(1 / 30, T + i * (at - T) / steps)
    c = PILCanvas(W, H)
    face.draw(c, at)
    return c.image()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "morse_preview"
    text = " ".join(sys.argv[2:]) or "hello"
    os.makedirs(out, exist_ok=True)
    code = morse.encode(text)
    beeps = [(a, b) for on, n, _ in morse.elements(code)
             for a, b in [(0, 0)] if on]                     # just to count
    total = sum(n for _, n, _ in morse.elements(code))
    for name, dits in (("start", 0.5), ("middle", total * 0.55), ("end", total + 1)):
        # land in the middle of a beep for the "middle" frame, so the flash shows
        if name == "middle":
            t = 0
            for on, n, _ in morse.elements(code):
                if on and t >= dits:
                    dits = t + n / 2
                    break
                t += n
        path = os.path.join(out, f"morse-{name}.png")
        frame(code, dits, caption=f"say {text} in morse").save(path)
        print("wrote", path)

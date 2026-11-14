"""
International Morse code: Chatty reads it and speaks it, all on the Pi (no cloud).

Speaking ("Hey Chatty, say hello in Morse"): she plays it as soft beeps through her
speaker while a little telegraph tape on her face lights up with each dit and dah,
and her eyes flash along. Short ones she also says out loud ("dit dit dit, dah dah dah...").

Reading:
  * spoken dots and dashes: "Hey Chatty, what does dot dot dot, next, dash dash dash,
    next, dot dot dot mean?" (say "next" or "space" between letters, "new word" between
    words; "dit" and "dah" work too)
  * typed on the remote panel or sent through the message door: "... --- ..." or
    "morse: .... ..", one space between letters, " / " between words
  * real beeps on her microphone: "Hey Chatty, listen for Morse" (a phone app, a
    practice key, a buzzer). She finds the strongest steady tone, measures the beeps
    and gaps, works out the speed herself, and tells you what it says.

The code table is the ITU one (letters, digits and common punctuation). Timing is the
standard one: a dah is 3 dits, 1 dit between parts of a letter, 3 between letters,
7 between words. Speed in words per minute (PARIS): one dit = 1.2 / WPM seconds.

Face message: `morse:<start>:<dit seconds>:<code>` (the face works out the timing itself).

Settings (/etc/chatty/secrets.env):
  CHATTY_MORSE=0             turn it all off
  CHATTY_MORSE_WPM=13        how fast she sends (13 is easy to follow; 20 for old hands)
  CHATTY_MORSE_TONE=650      beep pitch in Hz
  CHATTY_MORSE_VOLUME=0.3    beep loudness, 0..1
  CHATTY_MORSE_MAX_CHARS=40  longer messages are cut to the first words that fit
  CHATTY_MORSE_LISTEN=30     longest she listens for beeps, in seconds

Test without the Pi: python3 src/morse.py "hello world"   (prints the code and timing)
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import wave
from typing import List, Optional, Tuple

ENABLED = os.getenv("CHATTY_MORSE", "1") != "0"
WPM = max(5.0, min(40.0, float(os.getenv("CHATTY_MORSE_WPM", "13"))))
TONE = float(os.getenv("CHATTY_MORSE_TONE", "650"))
VOLUME = max(0.0, min(1.0, float(os.getenv("CHATTY_MORSE_VOLUME", "0.3"))))
MAX_CHARS = int(os.getenv("CHATTY_MORSE_MAX_CHARS", "40"))
LISTEN_SECONDS = float(os.getenv("CHATTY_MORSE_LISTEN", "30"))
DEVICE = os.getenv("CHATTY_ALSA_OUT", "plughw:CARD=PowerConf,DEV=0")
RATE = 22050

# ----------------------------
# the code (ITU-R M.1677)
# ----------------------------

CODE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--",
    "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...", ":": "---...",
    ";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", '"': ".-..-.",
    "@": ".--.-.",
}
LETTERS = {v: k for k, v in CODE.items()}
SOS = "...---..."      # sent as one run, no gaps between the letters

# ----------------------------
# text <-> code
# ----------------------------

_DOTS = ".·•∙⋅"
_DASHES = "-−–—_"


def clean_code(code: str) -> str:
    """Tidy typed Morse: any dot or dash look-alike, '|' or ' / ' between words,
    one space between letters."""
    code = code or ""
    for ch in _DOTS:
        code = code.replace(ch, ".")
    for ch in _DASHES:
        code = code.replace(ch, "-")
    code = re.sub(r"[|\\]", "/", code)
    code = re.sub(r"[^.\-/ ]", " ", code)
    code = re.sub(r"\s*/+\s*", " / ", code)
    code = re.sub(r"(?<=[.\-]) {3,}(?=[.\-])", " / ", code)    # a long gap = a new word
    code = re.sub(r" +", " ", code).strip(" /")
    return code


def encode(text: str) -> str:
    """'Hi there' -> '.... .. / - .... . .-. .' (characters she can't send are left out)."""
    words = []
    for word in (text or "").upper().split():
        letters = [CODE[ch] for ch in word if ch in CODE]
        if letters:
            words.append(" ".join(letters))
    return " / ".join(words)


def decode_detail(code: str) -> Tuple[str, int]:
    """('HI THERE', number of letters she couldn't read). Unreadable ones show as '?'."""
    code = clean_code(code)
    if code.replace(" ", "") == SOS:
        return "SOS", 0
    words, unknown = [], 0
    for word in code.split(" / "):
        out = ""
        for letter in word.split():
            ch = LETTERS.get(letter)
            if ch is None:
                ch = "SOS" if letter == SOS else "?"
                unknown += ch == "?"
            out += ch
        if out:
            words.append(out)
    return " ".join(words), unknown


def decode(code: str) -> str:
    return decode_detail(code)[0]


def spoken(code: str) -> str:
    """How she says it: 'dit dit dit, dah dah dah, dit dit dit'."""
    words = []
    for word in clean_code(code).split(" / "):
        words.append(", ".join(" ".join("dit" if s == "." else "dah" for s in letter)
                               for letter in word.split()))
    return ". ".join(w for w in words if w)


def to_words(code: str) -> str:
    """Typed code as words her ears understand: '.- -...' -> 'dot dash next dash dot dot dot'."""
    out = []
    for i, word in enumerate(clean_code(code).split(" / ")):
        if i:
            out.append("new word")
        for j, letter in enumerate(word.split()):
            if j:
                out.append("next")
            out.append(" ".join("dot" if s == "." else "dash" for s in letter))
    return " ".join(out)


def fit(text: str) -> Tuple[str, bool]:
    """Cut a long message to the first words that fit in MAX_CHARS. (text, was it cut)"""
    words, out = (text or "").split(), []
    for w in words:
        if len(" ".join(out + [w])) > MAX_CHARS:
            break
        out.append(w)
    if not out and words:
        out = [words[0][:MAX_CHARS]]
    return " ".join(out), len(out) < len(words) or (bool(words) and len(words[0]) > MAX_CHARS)


# ----------------------------
# finding Morse in what she hears or reads
# ----------------------------

DIT_WORDS = {"dot", "dots", "dit", "dits", "di", "did", "ditt", "dut"}
DAH_WORDS = {"dash", "dashes", "dah", "dahs", "da", "daa", "dar"}
LETTER_GAP = {"space", "next", "stop", "break", "pause", "then", "letter", "and", "comma"}
WORD_GAP = {"slash", "word", "words"}


def spoken_code(prompt: str) -> Optional[str]:
    """Spoken dots and dashes -> code. 'dot dot dot next dash dash dash' -> '... ---'.
    None when there are no dot/dash words. Words in between that aren't dots, dashes
    or a gap word count as a gap between letters."""
    words = (prompt or "").split()
    marks = [i for i, w in enumerate(words) if w in DIT_WORDS or w in DAH_WORDS]
    if not marks:
        return None
    # "di di dit" style words are too common to count on their own; need a real one
    if not any(words[i] in ("dot", "dash", "dit", "dah", "dots", "dashes", "dits", "dahs") for i in marks):
        return None
    out, letter = [], ""
    for w in words[marks[0]:marks[-1] + 1]:
        if w in DIT_WORDS or w in DAH_WORDS:
            letter += "." if w in DIT_WORDS else "-"
            continue
        if letter:
            out.append(letter)
            letter = ""
        if w in WORD_GAP and out and out[-1] != "/":
            out.append("/")
    if letter:
        out.append(letter)
    return clean_code(" ".join(out))


_TYPED = re.compile(r"[.\-·•−–—_/|][.\-·•−–—_/| ]*[.\-·•−–—_]")


def find_code(text: str) -> Optional[str]:
    """Typed Morse in a message ('... --- ...', 'morse: .... ..'), or None. Without the
    word 'morse' the message has to be mostly code, so an ellipsis isn't mistaken for S."""
    text = text or ""
    runs = [m.group(0) for m in _TYPED.finditer(text)]
    if not runs:
        return None
    best = clean_code(max(runs, key=lambda r: len(r.replace(" ", ""))))
    marks = best.replace(" ", "").replace("/", "")
    if len(marks) < 2:
        return None
    said_morse = re.search(r"\bmorse\b", text, re.I) is not None
    rest = _TYPED.sub(" ", text)
    rest = re.sub(r"(?i)\b(morse|code|what|does|do|this|that|it|mean|means|say|says|"
                  r"read|translate|decode|please|chatty|hey|hi|is|in|the)\b", " ", rest)
    mostly_code = len(re.sub(r"[\s?!:,]", "", rest)) <= 2
    if said_morse or mostly_code or ("." in marks and "-" in marks and len(marks) >= 4 and
                                     len(best.split()) >= 2):
        return best
    return None


_SEND = [
    re.compile(r"^(?:can you |could you |would you |will you |please )?(?:say|spell|tap|send|beep|play|"
               r"flash|signal|write|show me|key|blink)(?: out| me)? (?P<what>.+?) in morse(?: code)?(?: please)?$"),
    re.compile(r"\bhow (?:do|would|can|should) (?:you|i|we|one) (?:say|spell|write|send|tap|sign|do) "
               r"(?P<what>.+?) in morse(?: code)?$"),
    re.compile(r"\bwhat(?:s| is| does) (?P<what>.+?) (?:look like |sound like )?in morse(?: code)?$"),
    re.compile(r"\bmorse(?: code)? for (?P<what>.+?)(?: please)?$"),
    re.compile(r"^(?:send|beep|tap|signal|play) (?:an? |the )?(?P<what>sos)\b"),
]
_LISTEN = re.compile(r"\b(listen|listening|decode|translate|read|hear|catch)\b.*\b(morse|beeps?|dits)\b|"
                     r"\bmorse\b.*\b(listen|listening|decode|translate|hear)\b")
_ABOUT = re.compile(r"\b(what is|whats|who (invented|made|came up with)|history of|tell me about|"
                    r"explain|how does)\b.*\bmorse\b|^(can|do|could|will) you (read|speak|know|understand|"
                    r"do|use|talk|send) (in )?morse\b|^morse( code)?$")
_TEACH = re.compile(r"\b(teach me|learn|lesson|practice|practise|show me a letter)\b.*\bmorse\b|"
                    r"\bmorse\b.*\b(lesson|practice)\b")


def _what(s: str) -> str:
    s = re.sub(r"^(the (word|words|letter|letters|number|name|phrase) |the |a |an |word |letter )", "", s.strip())
    return s.strip()


def asked(prompt: str) -> Optional[Tuple[str, str]]:
    """What a (normalized) question wants, or None if it isn't about Morse:
    ('send', text) beep it, ('read', code) read spoken/typed dots and dashes,
    ('listen', '') decode beeps on the mic, ('teach', '') a letter to learn,
    ('about', '') what Morse code is / what she can do with it."""
    if not ENABLED or not prompt:
        return None
    p = prompt.strip()
    code = spoken_code(p)
    if code and (re.search(r"\b(morse|mean|means|say|says|spell|spells|read|decode|translate)\b", p)
                 or len(code.replace(" ", "")) >= len(p.split()) * 0.6):
        return "read", code
    if "morse" not in p and "sos" not in p:
        return None
    for rx in _SEND:
        m = rx.search(p)
        if m:
            what = _what(m.group("what"))
            if what and what not in ("it", "that", "this", "something", "code"):
                return "send", what
    if _TEACH.search(p):
        return "teach", ""
    if _LISTEN.search(p) and not re.match(r"^(can|do|could) you (read|understand)\b", p):
        return "listen", ""
    if _ABOUT.search(p):
        return "about", ""
    if re.search(r"\b(say|tap|send|beep|play) (something|anything|it) in morse\b", p):
        return "send", "hi"
    return None


# ----------------------------
# answers in words (panel, message door, and what she says around the beeps)
# ----------------------------

ABOUT = ("Morse code spells letters with short and long beeps: dits and dahs. Samuel Morse and "
         "Alfred Vail made the first version for the telegraph in the late 1830s, and the "
         "international version I use grew out of Friedrich Gerke's changes in 1848. "
         "Ask me to say something in Morse, read me dots and dashes, or say: listen for Morse.")

TEACH = [   # (letter, a little hook to remember it by; all original)
    ("E", "the shortest one there is: a single dit. E is the most common letter, so it got the quickest sound."),
    ("T", "one long dah. The opposite of E."),
    ("A", "dit dah. A starts small, then stretches."),
    ("N", "dah dit, A backwards."),
    ("S", "three quick dits, like rain tapping."),
    ("O", "three long dahs. Round and steady, like the letter."),
    ("K", "dah dit dah. Radio operators send it to say: go ahead, your turn."),
    ("R", "dit dah dit, like a little rocking chair."),
    ("M", "two dahs, a long hum: mmm."),
    ("I", "two dits, like a blink of two eyes."),
    ("C", "dah dit dah dit, a happy little gallop. Chat-ty, chat-ty!"),
    ("V", "dit dit dit dah. Famous from the start of a certain symphony."),
]


def text_answer(text: str) -> Optional[str]:
    """A written reply for typed Morse (message door), or None."""
    if not ENABLED:
        return None
    code = find_code(text)
    if code:
        plain, unknown = decode_detail(code)
        if not plain.strip("? "):
            return "That looks like Morse, but I couldn't make out any letters. One space between letters, and a / between words, please."
        reply = f'That Morse says: "{plain}".'
        if unknown:
            reply += f" ({unknown} letter{'s' if unknown > 1 else ''} I couldn't read are marked ?.)"
        if plain == "SOS":
            reply += " If you really need help, call 911. If you're just practicing: nicely sent!"
        else:
            reply += " Back at you: " + encode("hi") + " (HI)"
        return reply
    a = asked(re.sub(r"[^a-z0-9\s]", "", text.lower()).strip())
    if not a:
        return None
    kind, value = a
    if kind == "send":
        what, cut = fit(value)
        code = encode(what)
        if not code:
            return "I couldn't find any letters or numbers in that to send."
        return (f'"{what}" in Morse code: {code}' + (" (that's the start; it was long)" if cut else ""))
    if kind == "read":
        return text_answer(value)
    if kind == "teach":
        letter, hook = TEACH[sum(map(ord, text)) % len(TEACH)]
        return f"The letter {letter} is {CODE[letter]}: {hook}"
    if kind == "listen":
        return "I can only listen for beeps in the room. Through letters, just type the dots and dashes."
    return ABOUT


def read_reply(code: str) -> str:
    """What she says after reading Morse (spoken or heard)."""
    plain, unknown = decode_detail(code)
    letters = plain.replace(" ", "").replace("?", "")
    if not letters:
        if code and " " not in code.strip() and len(code.strip()) > 6:
            return ("Those all ran together, so I couldn't tell where one letter ends. "
                    "Say next between letters, like: dot dash, next, dash dot dot dot.")
        return "I couldn't make out any letters in that. Want to try again, a little slower?"
    out = f"That says: {plain.lower()}."
    if letters == "SOS":
        out = "That's S O S, the distress call! If anyone really needs help, call 911."
    elif len(letters) <= 4 and letters.isalpha() and " " not in plain:
        out = f"That spells {', '.join(letters)}."
    if unknown:
        out += f" There {'was' if unknown == 1 else 'were'} {unknown} I couldn't read."
    return out


# ----------------------------
# timing and sound
# ----------------------------

def unit_seconds(wpm: float = None) -> float:
    return 1.2 / (wpm or WPM)


def elements(code: str) -> List[Tuple[bool, int, int]]:
    """The code as (tone on?, length in dits, which letter) steps, gaps included.
    Letter index counts letters across the whole message (word gaps don't count)."""
    out, letter_no = [], -1
    for wi, word in enumerate(clean_code(code).split(" / ")):
        if wi and out:
            out.append((False, 7, letter_no))
        for li, letter in enumerate(word.split()):
            letter_no += 1
            if li:
                out.append((False, 3, letter_no))
            for si, s in enumerate(letter):
                if si:
                    out.append((False, 1, letter_no))
                out.append((True, 1 if s == "." else 3, letter_no))
    return out


def duration(code: str, wpm: float = None) -> float:
    return sum(n for _, n, _ in elements(code)) * unit_seconds(wpm)


def samples(code: str, wpm: float = None, freq: float = None, rate: int = RATE, volume: float = None):
    """The beeps as a float numpy array (-1..1), soft 5 ms edges so they don't click."""
    import numpy as np
    unit = unit_seconds(wpm)
    freq = freq or TONE
    vol = VOLUME if volume is None else volume
    parts = [np.zeros(int(rate * 0.05))]
    for on, n, _ in elements(code):
        length = int(round(rate * unit * n))
        if not on:
            parts.append(np.zeros(length))
            continue
        t = np.arange(length) / rate
        edge = np.minimum(1.0, np.minimum(t, (length - 1) / rate - t) / 0.005)
        parts.append(np.sin(2 * np.pi * freq * t) * np.clip(edge, 0, 1))
    parts.append(np.zeros(int(rate * 0.1)))
    return np.concatenate(parts) * vol


def write_wav(code: str, path: str, wpm: float = None, freq: float = None) -> str:
    import numpy as np
    audio = samples(code, wpm, freq)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())
    return path


def play(code: str, wpm: float = None) -> bool:
    """Play the beeps (blocks until done). True if it played."""
    folder = "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()
    path = os.path.join(folder, f"chatty_morse_{os.getpid()}.wav")
    try:
        write_wav(code, path, wpm)
        subprocess.run(["aplay", "-q", "-D", DEVICE, path], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=duration(code, wpm) + 5)
        return True
    except Exception as e:
        print(f"(morse beeps failed: {e!r})", flush=True)
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def face_message(code: str, start: float, wpm: float = None) -> str:
    return f"morse:{start:.2f}:{unit_seconds(wpm):.4f}:{clean_code(code)}"


# ----------------------------
# hearing beeps
# ----------------------------

FRAME = 320          # 20 ms at 16 kHz
HOP_SECONDS = 0.005  # envelope step
LOW_HZ, HIGH_HZ = 300.0, 2000.0
MIN_SNR = 6.0        # the tone has to stand this far above the room noise
END_QUIET = 2.5      # this long without a beep (after some) = they're done
GIVE_UP = 12.0       # no beeps at all by now = nobody's sending


def _runs(on) -> List[Tuple[bool, int]]:
    runs = []
    for v in on:
        v = bool(v)
        if runs and runs[-1][0] == v:
            runs[-1][1] += 1
        else:
            runs.append([v, 1])
    return [(v, n) for v, n in runs]


def _two_groups(values):
    """Split durations into short and long (1-D k-means). Returns (short mean, long mean)."""
    lo, hi = min(values), max(values)
    for _ in range(20):
        mid = (lo + hi) / 2
        a = [v for v in values if v <= mid] or [lo]
        b = [v for v in values if v > mid] or [hi]
        lo, hi = sum(a) / len(a), sum(b) / len(b)
    return lo, hi


def decode_audio(pcm, rate: int = 16000) -> Optional[dict]:
    """Beeps -> {'code', 'text', 'wpm', 'tone', 'quiet_after', 'tones'}, or None when no
    steady tone stands out. pcm: 16-bit mono bytes or a float numpy array."""
    import numpy as np
    if isinstance(pcm, (bytes, bytearray, memoryview)):
        x = np.frombuffer(bytes(pcm), dtype=np.int16).astype(np.float64) / 32768.0
    else:
        x = np.asarray(pcm, dtype=np.float64)
    frame = max(64, int(FRAME * rate / 16000))
    hop = max(1, int(rate * HOP_SECONDS))
    if len(x) < frame * 4:
        return None
    n = 1 + (len(x) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(frame), axis=1))
    freqs = np.fft.rfftfreq(frame, 1.0 / rate)
    band = (freqs >= LOW_HZ) & (freqs <= HIGH_HZ)
    if not band.any():
        return None
    loud = np.percentile(spec[:, band], 95, axis=0)       # the bin that is loud most often
    peak = int(np.flatnonzero(band)[int(np.argmax(loud))])
    lo, hi = max(0, peak - 1), min(spec.shape[1], peak + 2)
    env = spec[:, lo:hi].sum(axis=1)
    total = spec[:, band].sum(axis=1) + 1e-12
    purity = env / total                                   # a steady beep is one narrow peak
    env = np.convolve(env, np.ones(3) / 3, mode="same")
    floor, top = np.percentile(env, 20), np.percentile(env, 99)
    if top < max(floor, 1e-4) * MIN_SNR:
        return None
    high = floor + 0.5 * (top - floor)
    low = floor + 0.3 * (top - floor)
    on, state = np.zeros(n, dtype=bool), False
    for i in range(n):
        if state:
            state = env[i] > low
        else:
            state = env[i] > high and purity[i] > 0.2
        on[i] = state
    runs = _runs(on)
    # glitches under 15 ms join their neighbors
    min_len = max(1, int(0.015 / HOP_SECONDS))
    merged: List[List] = []
    for v, k in runs:
        if merged and (k < min_len or merged[-1][0] == v):
            merged[-1][1] += k
        else:
            merged.append([v, k])
    runs = [(v, k * HOP_SECONDS) for v, k in merged]
    tones = [d for v, d in runs if v]
    if not tones:
        return None
    first = next(i for i, (v, _) in enumerate(runs) if v)
    last = max(i for i, (v, _) in enumerate(runs) if v)
    quiet_after = sum(d for _, d in runs[last + 1:])
    body = runs[first:last + 1]
    gaps = [d for v, d in body if not v]

    short, long_ = _two_groups(tones)
    if long_ > 2.0 * short:
        unit = (short + long_ / 3) / 2
    elif gaps and min(gaps) > 0:
        g = _two_groups(gaps)[0]          # the gaps inside letters are one dit long
        unit = short if short < 2 * g else short / 3
        if short > 0.26:                  # a dit that long would be under 5 WPM: they're dahs
            unit = short / 3
    else:
        unit = short if short < 0.2 else short / 3
    unit = max(unit, 0.02)

    # gaps between letters vs. between words: practice apps often stretch both
    # (Farnsworth timing), so look at how the long gaps group, not just at the dit length
    long_gaps = [d for d in gaps if d >= 2 * unit]
    word_gap = 5 * unit
    if len(long_gaps) >= 2:
        a, b = _two_groups(long_gaps)
        if b > 1.8 * a:
            word_gap = (a * b) ** 0.5
        else:
            word_gap = max(word_gap, 1.6 * b)
    code = ""
    for v, d in body:
        if v:
            code += "." if d < 2 * unit else "-"
        elif d >= word_gap:
            code += " / "
        elif d >= 2 * unit:
            code += " "
    code = clean_code(code)
    plain, unknown = decode_detail(code)
    return {"code": code, "text": plain, "unknown": unknown, "wpm": round(1.2 / unit, 1),
            "tone": round(float(freqs[peak])), "quiet_after": quiet_after, "tones": len(tones)}


if __name__ == "__main__":
    import sys
    message = " ".join(sys.argv[1:]) or "hello world"
    c = find_code(message)
    if c:
        print(f"{c!r} reads as {decode(c)!r}")
    else:
        c = encode(message)
        print(f"{message!r} -> {c}")
        print(f"spoken: {spoken(c)}")
        print(f"{duration(c):.1f} s at {WPM:g} WPM, {TONE:g} Hz")
        try:
            got = decode_audio(samples(c, rate=16000), 16000)
            print(f"heard back from a clean recording: {got['text']!r} at {got['wpm']} WPM")
        except ImportError:
            pass

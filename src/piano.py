"""
Chatty plays the piano: songs from little text files, a piano sound made right here
on the Pi (numpy, no samples, no cloud), and a keyboard on her face whose keys light up
as she plays, with her eyes following the melody.

Ask her:
  "Hey Chatty, play the piano" / "play me a song"      a song she picks
  "play Ode to Joy" / "play Twinkle Twinkle on the piano"
  "what songs can you play?"                            the list
  "play it again"                                       (within 5 minutes)
  "how do I teach you a song?"                          where song files go
A tap on her screen stops the song. A tornado warning stops it too (Red Alert first).

Songs: the built-in ones are in src/songs/ (public domain, plus one original). Your own go
in CHATTY_SONGS_DIR (default ~/.local/share/chatty/songs/), one .txt file each. That folder
is outside the repo, so songs you own sheet music for stay on your Pi. A file there with
the same name as a built-in one replaces it.

Song file format (one song per file; '#' starts a comment; '|' bar lines are optional
but let it check your counting):
    title: Ode to Joy
    by: Ludwig van Beethoven, 1824 (public domain)
    names: ode to joy, beethoven        what you might call it out loud
    tempo: 108                          quarter notes a minute
    style: classical                    optional; classical pieces get her powdered wig
    about: It's pure joy in four bars.  optional; why she likes it (said when she picks it)
    time: 4/4                           optional; with it, every bar is checked
    right: E4 E4 F4 G4 | G4 F4 E4 D4 | C4 C4 D4 E4 | E4:1.5 D4:0.5 D4:2
    left:  C3:2 E3:2 | G2:2 B2:2 | ...
The end of a line is also the end of a bar. A note is a letter, an optional # or b, and an octave (middle C is C4). After a colon
comes its length in quarter-note beats (1 quarter, 0.5 eighth, 0.75 dotted eighth,
1/3 a triplet eighth, 2 half, 4 whole); without one it's as long as the note before.
C4+E4+G4 is a chord, r is a rest, x is a finger snap. Several right:/left: lines are
joined in order. Check a file with:  python3 src/piano.py --check my-song.txt

Face message: `piano:<start>:<song id>` (the face reads the same song file) / `piano:off`.

Settings (/etc/chatty/secrets.env):
  CHATTY_PIANO=0              off
  CHATTY_PIANO_VOLUME=0.35    loudness, 0..1
  CHATTY_PIANO_MAX_SECONDS=150  longer songs are cut there
  CHATTY_SONGS_DIR            where your own songs live

Try it without the Pi: python3 src/piano.py --list | --check FILE | --wav ID out.wav
"""
from __future__ import annotations

import difflib
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from fractions import Fraction
from typing import Callable, Dict, List, Optional, Tuple

ENABLED = os.getenv("CHATTY_PIANO", "1") != "0"
VOLUME = max(0.0, min(1.0, float(os.getenv("CHATTY_PIANO_VOLUME", "0.35"))))
MAX_SECONDS = float(os.getenv("CHATTY_PIANO_MAX_SECONDS", "150"))
SONGS_DIR = os.path.expanduser(os.getenv("CHATTY_SONGS_DIR", "~/.local/share/chatty/songs"))
BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "songs")
DEVICE = os.getenv("CHATTY_ALSA_OUT", "plughw:CARD=PowerConf,DEV=0")
RATE = 22050
FOLLOW_UP = 300.0          # "play it again" counts this long after a song

_NOTE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d)$")
_STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


# ----------------------------
# song files
# ----------------------------

class Song:
    """A parsed song. notes: (start s, length s, midi or None for a snap, hand) by start."""

    def __init__(self, key: str, title: str, by: str, tempo: float, names: List[str],
                 notes: List[Tuple[float, float, Optional[int], str]], bars: List[str], local: bool):
        self.key, self.title, self.by, self.tempo = key, title, by, tempo
        self.names, self.notes, self.bars, self.local = names, notes, bars, local
        self.style = ""          # "classical" puts a powdered wig on her face while she plays
        self.about = ""          # why she likes it, in her words (said when she picks it herself)

    @property
    def seconds(self) -> float:
        return max((t + d for t, d, _, _ in self.notes), default=0.0)

    def keys_range(self) -> Tuple[int, int]:
        pitches = [m for _, _, m, _ in self.notes if m is not None]
        return (min(pitches), max(pitches)) if pitches else (60, 72)


def midi(name: str) -> int:
    """'C4' -> 60, 'F#3' -> 54, 'Bb2' -> 46."""
    m = _NOTE.match(name.strip())
    if not m:
        raise ValueError(f"not a note: {name!r}")
    letter, acc, octave = m.group(1).upper(), m.group(2), int(m.group(3))
    n = 12 * (octave + 1) + _STEPS[letter] + (1 if acc == "#" else -1 if acc == "b" else 0)
    if not 21 <= n <= 108:
        raise ValueError(f"{name!r} is off the piano")
    return n


def note_name(n: int) -> str:
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"


def _beats(text: str) -> Fraction:
    try:
        v = Fraction(text) if "/" in text else Fraction(text).limit_denominator(48)
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"not a length: {text!r}")
    if v <= 0 or v > 32:
        raise ValueError(f"not a length: {text!r}")
    return v


def _track(tokens: List[str]) -> Tuple[List[Tuple[Fraction, Fraction, List[Optional[int]]]], List[Fraction]]:
    """Tokens of one hand -> [(start beat, beats, pitches)] and the bar lengths."""
    events, t, last, bars, bar_start = [], Fraction(0), Fraction(1), [], Fraction(0)
    for tok in tokens:
        if tok == "|":
            if t > bar_start:
                bars.append(t - bar_start)
            bar_start = t
            continue
        what, _, length = tok.partition(":")
        if length:
            last = _beats(length)
        if what.lower() == "r":
            pitches = []
        elif what.lower() == "x":
            pitches = [None]
        else:
            pitches = [midi(p) for p in what.split("+") if p]
            if not pitches:
                raise ValueError(f"not a note: {tok!r}")
        if pitches:
            events.append((t, last, pitches))
        t += last
    if t > bar_start:
        bars.append(t - bar_start)
    return events, bars + [t]          # the last entry is the hand's whole length


def parse(text: str, key: str = "song", local: bool = False) -> Song:
    """A song file's text -> Song. Raises ValueError with the line number on a mistake."""
    head: Dict[str, str] = {}
    hands: Dict[str, List[str]] = {"right": [], "left": []}
    for no, raw in enumerate((text or "").splitlines(), 1):
        line = _strip_comment(raw)
        if not line:
            continue
        field, sep, value = line.partition(":")
        field = field.strip().lower()
        if not sep:
            raise ValueError(f"line {no}: expected 'name: value'")
        if field in ("right", "left", "rh", "lh", "melody", "bass"):
            hand = "right" if field in ("right", "rh", "melody") else "left"
            toks = value.replace("|", " | ").split()
            for tok in toks:          # check each note now, for a helpful line number
                if tok != "|":
                    try:
                        _track([tok])
                    except ValueError as e:
                        raise ValueError(f"line {no}: {e}")
            if toks and toks[-1] != "|":
                toks.append("|")      # the end of a line is the end of a bar
            hands[hand] += toks
        elif field in ("title", "by", "names", "tempo", "time", "style", "about"):
            head[field] = value.strip()
        else:
            raise ValueError(f"line {no}: unknown field {field!r}")
    try:
        tempo = float(head.get("tempo", "100"))
    except ValueError:
        raise ValueError("tempo should be a number (quarter notes a minute)")
    if not 20 <= tempo <= 320:
        raise ValueError("tempo should be between 20 and 320")
    beat = 60.0 / tempo
    notes, bars = [], []
    for hand, toks in hands.items():
        events, lengths = _track(toks)
        bars.append((hand, lengths))
        for start, beats, pitches in events:
            for p in pitches:
                notes.append((float(start) * beat, float(beats) * beat, p, hand))
    if not any(m is not None for _, _, m, _ in notes):
        raise ValueError("no notes (write them on a 'right:' line)")
    notes.sort(key=lambda n: (n[0], n[2] or 0))
    title = head.get("title") or key.replace("-", " ").replace("_", " ").title()
    names = [normalize(n) for n in head.get("names", "").split(",") if normalize(n)]
    for n in (normalize(title), normalize(key.replace("-", " ").replace("_", " "))):
        if n and n not in names:
            names.append(n)
    song = Song(key, title, head.get("by", ""), tempo, names, notes, [], local)
    song.bars = _bar_problems(bars, head.get("time", ""))
    song.style = head.get("style", "").strip().lower()
    song.about = head.get("about", "").strip()
    return song


def _strip_comment(raw: str) -> str:
    """'right: C4 D4  # comment' -> 'right: C4 D4' (a '#' right after a note letter is a sharp)."""
    return re.sub(r"(^|\s)#.*$", "", raw).strip()


def _bar_problems(bars, meter: str) -> List[str]:
    """Counting mistakes, in words: bars that don't add up to the time signature
    (the first and last bar may be short), and hands of different lengths."""
    out = []
    totals = {hand: lengths[-1] for hand, lengths in bars if lengths[-1] > 0}
    if len(set(totals.values())) > 1:
        out.append("the hands have different lengths: " +
                   ", ".join(f"{h} {float(t):g} beats" for h, t in totals.items()))
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", meter or "")
    if not m:
        return out
    want = Fraction(int(m.group(1)) * 4, int(m.group(2)))
    for hand, lengths in bars:
        inner = lengths[:-1]
        for i, length in enumerate(inner):
            short_end = i in (0, len(inner) - 1) and length < want
            if length != want and not short_end:
                out.append(f"{hand} hand, bar {i + 1}: {float(length):g} beats, not {float(want):g}")
    return out


def _load_file(path: str, local: bool) -> Optional[Song]:
    key = os.path.splitext(os.path.basename(path))[0].lower()
    if not re.match(r"^[a-z0-9_-]{1,40}$", key):
        print(f"(piano: skipped {os.path.basename(path)}: name it with letters, numbers, - or _)", flush=True)
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return parse(f.read(200_000), key, local)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        print(f"(piano: skipped {os.path.basename(path)}: {e})", flush=True)
        return None


def library() -> Dict[str, Song]:
    """Every song she knows by id: built-in ones, then your own (yours win on the same id)."""
    songs: Dict[str, Song] = {}
    for folder, local in ((BUILTIN_DIR, False), (SONGS_DIR, True)):
        try:
            files = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in files:
            if name.endswith(".txt"):
                song = _load_file(os.path.join(folder, name), local)
                if song:
                    songs[song.key] = song
    return songs


def load(key: str) -> Optional[Song]:
    return library().get((key or "").strip().lower())


# ----------------------------
# what was asked
# ----------------------------

def normalize(s: str) -> str:
    s = (s or "").lower().replace("ü", "u").replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


_FILLER = re.compile(r"\b(please|for me|for us|chatty|on the piano|on your piano|on piano|the song|"
                     r"song|tune|theme song|theme|again|now|real quick|a little|little bit of|some)\b")
_ANY = re.compile(r"\b(play|playing|plays)\b.*\b(piano|keyboard|keys)\b|\bpiano\b.*\bplay\b|"
                  r"\bplay (me |us )?(a |another |some |any )?(song|tune|music|melody)\b|"
                  r"\b(sing|play) (me |us )?something\b.*\b(piano|music)\b|^piano( time)?$|"
                  r"\b(serenade me|tickle the ivories|piano time)\b")
_LIST = re.compile(r"\b(what|which) (songs|tunes|music|pieces)\b.*\b(know|play|have|got)\b|"
                   r"\b(list|name) (your |the )?(songs|tunes)\b|\byour (songs|repertoire|playlist)\b|"
                   r"\bwhat can you play\b|\bwhat do you play\b")
_HOW = re.compile(r"\bhow\b.*\b(add|teach|give|put|write|make|load)\b.*\b(song|songs|tune|tunes)\b|"
                  r"\bhow (do|can) you play\b.*\bpiano\b|\bhow does your piano\b|"
                  r"\b(teach|learn) (you |a )?(a )?new (song|tune)\b")
_AGAIN = re.compile(r"^(?:(?:can you |could you |please )?(?:play|do) (?:it|that|that song|that one) "
                    r"(?:again|one more time|once more)|again|again please|one more time|encore|play it again)$")
_PLAY = re.compile(r"^(?:(?:can|could|would|will) you |please |do you know |go ahead and |let's hear )?"
                   r"(?:play|playing|plays|perform|do) (?:me |us )?(?P<what>.+)$")

_GENERIC = {"it", "that", "this", "something", "anything", "song", "tune", "music", "melody", "piano",
            "a song", "a tune", "some music", "something nice", "something else", "another one", "another"}

_CHOOSE = re.compile(
    r"\b(what|which)\b(?: \w+){0,3} (?:would|do|should|will|d) you (?:like|want|wanna|feel like|prefer|choose|pick|"
    r"love|enjoy)(?: to)? (?:play|playing|perform)\b|"
    r"\bwhat (?:do |would )?you feel like playing\b|"
    r"\b(?:your|ur) (?:favorite|favourite) (?:song|songs|piece|pieces|tune|composer|music|thing to play)\b|"
    r"\b(?:you|u) (?:pick|choose|decide)\b.*\b(?:song|piece|tune|play|music)\b|"
    r"\b(?:play|pick) (?:me )?(?:something|anything|a song|a piece|one) you (?:like|love|choose|pick|enjoy)\b|"
    r"\b(?:your|you) (?:choice|pick)\b.*\b(?:song|piece|tune|play|music|piano)\b")
_YOU_PICK = re.compile(r"^(?:you pick|you choose|your choice|you decide|surprise me|dealers choice|"
                       r"whatever you like|you pick one|pick one)$")

last = {"key": "", "at": 0.0, "listed": 0.0}
LISTED_FOLLOW_UP = 60.0     # right after "what songs can you play?", just a name will do


def remember(key: str, now: Optional[float] = None) -> None:
    last.update(key=key, at=time.time() if now is None else now)


def listed(now: Optional[float] = None) -> None:
    last["listed"] = time.time() if now is None else now


def recent(now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    return bool(last["key"]) and now - last["at"] < FOLLOW_UP


def match(what: str, songs: Optional[Dict[str, Song]] = None) -> Optional[str]:
    """The song id a spoken name points to ('ode to joy', 'the adams family theme'), or None."""
    songs = library() if songs is None else songs
    best, best_score = None, 0.0
    raw = re.sub(r"^(the|a|an) ", "", normalize(what)).strip()
    for words in {raw, re.sub(r"^(the|a|an) ", "", normalize(_FILLER.sub(" ", raw))).strip()}:
        if not words or words in _GENERIC:
            continue
        for key, song in songs.items():
            for name in song.names:
                bare = re.sub(r"^(the|a|an) ", "", name)
                if not bare:
                    continue
                if bare == words or re.search(rf"\b{re.escape(bare)}\b", words):
                    score = 1.0 + len(bare) / 100
                elif len(words.split()) >= 2 and re.search(rf"\b{re.escape(words)}\b", bare):
                    score = 0.95       # part of a long name: "twinkle twinkle"
                elif len(words) >= 6:          # a misheard name: "owed to joy"
                    score = difflib.SequenceMatcher(None, words, bare).ratio()
                else:
                    score = 0.0
                if score > best_score:
                    best, best_score = key, score
    return best if best_score >= 0.8 else None


def asked(prompt: str, now: Optional[float] = None) -> Optional[Tuple[str, str]]:
    """What a (normalized) request wants, or None if it isn't about the piano:
    ('play', id), ('any', ''), ('list', ''), ('how', ''), ('again', ''),
    ('unknown', name) for "play <a song she doesn't know> on the piano"."""
    if not ENABLED or not prompt:
        return None
    p = normalize(prompt)
    if recent(now) and _AGAIN.match(p):
        return "again", ""
    style = "classical" if re.search(r"\b(classical|composer|symphony|sonata|concerto)\b", p) else ""
    games = re.search(r"\b(game|games|chess|tic ?tac ?toe|trickster|mystery|catch|hide and seek)\b", p)
    if _CHOOSE.search(p) and not games:
        return "choose", style
    listed_now = (time.time() if now is None else now) - last["listed"] < LISTED_FOLLOW_UP
    if listed_now and _YOU_PICK.match(p):
        return "choose", ""
    if _HOW.search(p):
        return "how", ""
    if _LIST.search(p) and not re.search(r"\b(game|games|chess)\b", p):
        return "list", ""
    m = _PLAY.search(p)
    songs = library()
    now = time.time() if now is None else now
    if not m and now - last["listed"] < LISTED_FOLLOW_UP:
        key = match(p, songs)              # "Ode to Joy" right after she listed her songs
        if key:
            return "play", key
    if m:
        key = match(m.group("what"), songs)
        if key:
            return "play", key
    m2 = re.search(r"\b(?:play|playing) (?:me |us )?(?P<what>.+?) on (?:the |your )?piano\b", p)
    if m2:
        what = re.sub(r"^(the |a |some |something|anything|a song|a tune|music)\s*", "", m2.group("what")).strip()
        key = match(what, songs) if what else None
        if key:
            return "play", key
        if what and what not in _GENERIC:
            return "unknown", what
    if _ANY.search(p):
        return "any", ""
    return None


def song_list(songs: Optional[Dict[str, Song]] = None) -> str:
    songs = library() if songs is None else songs
    titles = [s.title for s in sorted(songs.values(), key=lambda s: (not s.local, s.title.lower()))]
    if not titles:
        return "I don't know any songs yet."
    if len(titles) == 1:
        return f"I can play {titles[0]}."
    return "I can play " + ", ".join(titles[:-1]) + ", and " + titles[-1] + "."


HOW = ("I play from little song files, and I make the piano sound myself, right here on the Pi. "
       "To teach me a song, put a text file of its notes in my songs folder, in "
       "dot local, share, chatty, songs. The notes look like E4, D4, C4. "
       "The instructions are at the top of piano dot py.")


def choose(style: str = "", avoid: str = "", rng=None, songs: Optional[Dict[str, Song]] = None) -> Optional[str]:
    """She picks a piece herself: one of the style asked for ('classical'), else any she
    has something to say about, never the one she just played if there's another."""
    import random as _random
    rng = rng or _random
    songs = library() if songs is None else songs
    pool = [k for k, s in songs.items() if not style or s.style == style] or list(songs)
    liked = [k for k in pool if songs[k].about] or pool
    fresh = [k for k in liked if k != avoid] or liked
    return rng.choice(sorted(fresh)) if fresh else None


def reason(song: Song, rng=None) -> str:
    """What she says when she picks a piece herself: her choice, and why."""
    import random as _random
    rng = rng or _random
    pick = rng.choice([f"Ooh, I choose {song.title}!", f"I'd love to play {song.title}.",
                       f"Let's do {song.title}.", f"My pick is {song.title}."])
    why = song.about or rng.choice(["It always makes my circuits smile.",
                                    "It's one of my favorites to play.",
                                    "My fingers have been itching to play it."])
    return f"{pick} {why} Here goes!"


def pick_any(rng=None, avoid: str = "") -> Optional[str]:
    import random as _random
    rng = rng or _random
    keys = sorted(library())
    choices = [k for k in keys if k != avoid] or keys
    return rng.choice(choices) if choices else None


def intro(song: Song, rng=None) -> str:
    import random as _random
    rng = rng or _random
    lines = [f"Here's {song.title}!", f"Okay! {song.title}. Here goes.",
             f"One {song.title}, coming right up!", f"Let me warm up my fingers. {song.title}!"]
    return rng.choice(lines)


BOWS = ["Thank you, thank you!", "Ta-da!", "And that's the song!", "I hope you liked it!"]
STOPPED = ["Okay, I'll stop there.", "Intermission!", "Okay, piano lid closed."]


# ----------------------------
# the piano sound
# ----------------------------

def freq(n: int) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def _note_samples(n: int, seconds: float, rate: int = RATE):
    """One piano note: a few slightly stretched overtones (real strings run a little sharp
    up high), two strings a hair apart for warmth, each overtone fading faster than the
    one below, a soft felt-hammer thump at the start, and the damper after the key is let go."""
    import numpy as np
    f0 = freq(n)
    ring = min(seconds, 4.0)
    total = int(rate * (ring + 0.25))
    t = np.arange(total) / rate
    out = np.zeros(total)
    inharm = 0.00012 * (1 + max(0, n - 60) / 12)
    low = max(0.0, (60 - n) / 24)                       # low notes: more overtones, slower fade
    for k in range(1, 9):
        fk = k * f0 * math.sqrt(1 + inharm * k * k)
        if fk > rate * 0.45:
            break
        amp = (1.0 / k ** (1.35 - 0.45 * low)) * (1.0 if k > 1 else 1.2)
        decay = (0.9 + 0.55 * k) * (0.6 + f0 / 520) * (1 - 0.35 * low)
        env = np.exp(-t * decay)
        out += amp * env * np.sin(2 * np.pi * fk * t)
        if k <= 3:
            out += 0.5 * amp * env * np.sin(2 * np.pi * fk * 1.0012 * t + 0.7 * k)
    attack = np.minimum(1.0, t / 0.004)
    out *= attack
    rng = np.random.default_rng(n)
    thump = rng.standard_normal(total) * np.exp(-t * 140) * 0.05
    out += np.convolve(thump, np.ones(6) / 6, mode="same")
    let_go = np.where(t > ring, np.exp(-(t - ring) * 22), 1.0)   # the damper
    return out * let_go / 2.4


def _snap_samples(rate: int = RATE):
    """A finger snap: a sharp, bright little burst of noise."""
    import numpy as np
    n = int(rate * 0.09)
    t = np.arange(n) / rate
    noise = np.random.default_rng(7).standard_normal(n)
    bright = np.diff(noise, prepend=0.0)                 # high-passed: crisp, not hissy
    return (bright * 0.5 * np.exp(-t * 55) + 0.4 * np.sin(2 * np.pi * 2200 * t) * np.exp(-t * 90)) * 0.9


def render(song: Song, rate: int = RATE, volume: Optional[float] = None, max_seconds: Optional[float] = None):
    """The whole song as a float numpy array (-volume..volume)."""
    import numpy as np
    vol = VOLUME if volume is None else volume
    limit = MAX_SECONDS if max_seconds is None else max_seconds
    length = min(song.seconds, limit)
    out = np.zeros(int(rate * (length + 1.5)) + 1)
    cache = {}
    lead = int(rate * 0.05)
    for start, dur, n, hand in song.notes:
        if start >= limit:
            break
        if n is None:
            key = "snap"
            if key not in cache:
                cache[key] = _snap_samples(rate)
            gain = 0.8
        else:
            key = (n, round(dur * 0.9, 2))
            if key not in cache:
                cache[key] = _note_samples(n, max(0.08, dur * 0.9), rate)
            gain = 0.8 if hand == "left" else 1.0       # the melody sings over the bass
        s = cache[key]
        i = lead + int(start * rate)
        j = min(len(out), i + len(s))
        out[i:j] += s[:j - i] * gain
    if limit < song.seconds:                             # cut short: a gentle fade
        cut = lead + int(limit * rate)
        fade = int(rate * 0.8)
        out[cut:] = 0
        out[max(0, cut - fade):cut] *= np.linspace(1, 0, min(fade, cut))
    peak = float(np.max(np.abs(out))) or 1.0
    return np.tanh(out / peak * 1.2) / math.tanh(1.2) * vol


def write_wav(song: Song, path: str, **kw) -> str:
    import numpy as np
    audio = render(song, **kw)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())
    return path


def render_file(song: Song) -> Optional[str]:
    """Render the song to a wav in RAM (/dev/shm). The path, or None if it failed."""
    folder = "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()
    path = os.path.join(folder, f"chatty_piano_{os.getpid()}.wav")
    try:
        return write_wav(song, path)
    except Exception as e:
        print(f"(piano: couldn't make the sound: {e!r})", flush=True)
        return None


def play_file(path: str, seconds: float, stop: Optional[Callable[[], bool]] = None,
              on_start: Optional[Callable[[float], None]] = None) -> str:
    """Play a rendered song (blocks). 'done', 'stopped' (stop() said so) or 'failed'.
    stop() is checked ten times a second. The wav is deleted afterwards."""
    proc = None
    try:
        proc = subprocess.Popen(["aplay", "-q", "-D", DEVICE, path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if on_start:
            on_start(time.time() + 0.15)                 # aplay takes a moment to get going
        give_up = time.time() + min(seconds, MAX_SECONDS) + 8
        while proc.poll() is None:
            if stop and stop():
                proc.terminate()
                return "stopped"
            if time.time() > give_up:
                proc.kill()
                return "failed"
            time.sleep(0.1)
        return "done" if proc.returncode == 0 else "failed"
    except Exception as e:
        print(f"(piano: couldn't play: {e!r})", flush=True)
        return "failed"
    finally:
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        try:
            os.remove(path)
        except OSError:
            pass


def discard(path: Optional[str]) -> None:
    """Delete a rendered song that won't be played after all."""
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def face_message(song: Song, start: float) -> str:
    return f"piano:{start:.2f}:{song.key}"


# ----------------------------
# try it
# ----------------------------

def _main(argv: List[str]) -> int:
    if not argv or argv[0] == "--list":
        for key, song in sorted(library().items()):
            where = "yours" if song.local else "built in"
            print(f"{key:24} {song.title} ({song.seconds:.0f} s, {where})")
        return 0
    if argv[0] == "--check" and len(argv) > 1:
        try:
            with open(argv[1], encoding="utf-8") as f:
                song = parse(f.read(), os.path.splitext(os.path.basename(argv[1]))[0])
        except (OSError, ValueError) as e:
            print("Problem:", e)
            return 1
        lo, hi = song.keys_range()
        print(f"{song.title}: {len(song.notes)} notes, {song.seconds:.1f} s, "
              f"{note_name(lo)} to {note_name(hi)}, names: {', '.join(song.names)}")
        for problem in song.bars:
            print("  counting:", problem)
        print("Looks good!" if not song.bars else "Have a look at those bars.")
        return 0 if not song.bars else 2
    if argv[0] == "--wav" and len(argv) > 2:
        song = load(argv[1])
        if not song:
            print("No song called", argv[1])
            return 1
        print("wrote", write_wav(song, argv[2]))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))

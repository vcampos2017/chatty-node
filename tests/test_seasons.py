"""Season days: the solstice and equinox dates, the Pi's own calendar, what you might ask,
once per season in the daytime, the summer party's steps and song, the sunglasses, the money
breeze and drifting petals/snow on her face, and the voice node's wiring."""
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

os.environ["TZ"] = "UTC"
time.tzset()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CHATTY_NIGHT_MODE", "0")
os.environ.pop("CHATTY_FORCE_SEASON", None)
os.environ.pop("CHATTY_FORCE_THANKSGIVING", None)
os.environ["CHATTY_SONGS_DIR"] = os.path.join(tempfile.mkdtemp(), "songs")
import piano  # noqa: E402
import seasons as se  # noqa: E402
from face_model import FaceModel  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")
FACE = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_face.py")


def _at(month, day, hour=12, minute=0, year=2026):
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


def _tz(name):
    os.environ["TZ"] = name
    time.tzset()


def test_the_sky_dates_to_a_couple_of_minutes():
    # published instants (UTC)
    known = [("spring", 2026, (3, 20, 14, 46)), ("summer", 2026, (6, 21, 8, 24)),
             ("autumn", 2026, (9, 23, 0, 5)), ("winter", 2026, (12, 21, 20, 50)),
             ("summer", 2027, (6, 21, 14, 11)), ("summer", 2028, (6, 20, 20, 2)),
             ("winter", 2027, (12, 22, 2, 42))]
    for season, year, (m, d, hh, mm) in known:
        want = time.mktime((year, m, d, hh, mm, 0, 0, 0, -1))
        got = se.instant(season, year)
        assert abs(got - want) < 180, (season, year, (got - want) / 60)


def test_first_day_follows_the_pis_own_clock():
    try:
        assert se.first_day("autumn", 2026) == (9, 23)       # UTC
        _tz("America/Los_Angeles")
        assert se.first_day("autumn", 2026) == (9, 22)       # the evening before, out west
        assert se.first_day("summer", 2026) == (6, 21)
        assert se.first_day("summer", 2028) == (6, 20)
    finally:
        _tz("UTC")


def test_season_today():
    assert se.season_today(_at(6, 21)) == "summer"
    assert se.season_today(_at(6, 22)) is None
    assert se.season_today(_at(12, 21)) == "winter"
    assert se.season_today(_at(3, 20)) == "spring"
    os.environ["CHATTY_FORCE_SEASON"] = "fall"
    try:
        assert se.season_today(_at(1, 5)) == "autumn"
    finally:
        os.environ.pop("CHATTY_FORCE_SEASON")


def test_when_text():
    said = se.when_text("summer", _at(11, 23))
    assert "June 21st, 2027" in said and "Monday" in said and "days away" in said
    assert "tomorrow" in se.when_text("summer", _at(6, 20))
    today = se.when_text("summer", _at(6, 21))
    assert "today" in today.lower() and "solstice" in today
    assert "December 21st" in se.when_text("winter", _at(11, 23)) and "2026" not in se.when_text("winter", _at(11, 23))
    assert se.next_season(_at(11, 23)) == "winter"


def test_what_you_might_ask():
    a = lambda p: se.asked(p, _at(11, 23))  # noqa: E731
    assert a("celebrate summer") == ("celebrate", "summer")
    assert a("lets celebrate the first day of summer") == ("celebrate", "summer")
    assert a("its the first day of summer") == ("celebrate", "summer")
    assert a("summer party") == ("celebrate", "summer")
    assert a("celebrate fall") == ("celebrate", "autumn")
    assert a("celebrate winter") == ("celebrate", "winter")
    assert a("when is the first day of summer") == ("when", "summer")
    assert a("when does winter start") == ("when", "winter")
    assert a("how many days until summer") == ("when", "summer")
    assert a("when is the summer solstice") == ("when", "summer")
    assert a("when is the longest day of the year") == ("when", "summer")
    assert a("when is the next solstice") == ("when", "winter")
    assert a("when is the equinox") == ("when", "spring")
    assert a("what is a solstice") == ("explain", "solstice")
    assert a("whats an equinox") == ("explain", "equinox")
    assert a("why are you wearing sunglasses") == ("shades", "")
    assert a("chatty bucks") == ("bills", "summer")
    assert a("blow the money away") == ("bills", "summer")
    assert a("order ice cream") == ("icecream", "order")
    assert a("lets get ice cream") == ("icecream", "order")
    assert a("whats your favorite ice cream flavor") == ("icecream", "favorite")
    assert a("do you like ice cream") == ("icecream", "order")
    assert a("happy first day of spring") == ("happy", "spring")
    assert a("happy summer") == ("happy", "summer")
    for no in ("why are you wearing a hat", "happy thanksgiving", "what time is it", "play the piano",
               "whats the weather", "will it rain this summer", "i love summer", "thank you"):
        assert a(no) is None, no


def test_replies():
    r = se.reply_for
    assert "cool" in r("shades", "", _at(6, 21))[0]
    assert "save them" in r("shades", "", _at(11, 23))[0]
    assert "equal night" in r("explain", "equinox")[0]
    assert "almost-summer" in r("happy", "summer", _at(11, 23))[0]
    assert r("happy", "summer", _at(6, 21))[0].startswith("Happy first day of summer")


def test_summer_party_steps():
    steps = se.celebration("summer", random.Random(1))
    assert [m for m, _, _ in steps][:3] == ["season:summer", "season:bills", "season:icecream"]
    assert steps[2][1] in se.ICE_CREAM and all("ice cream" in x.lower() or "scoop" in x for x in se.ICE_CREAM)
    said, mood = se.reply_for("icecream", "favorite", rng=random.Random(1))
    assert "favorite" in said.lower() and mood == "mischief_talk"
    assert se.reply_for("icecream", "order")[0] in se.ICE_CREAM
    assert "Chatty Bucks" in steps[1][1] and "summer" in steps[0][1].lower()
    one = se.celebration("winter", random.Random(1))
    assert len(one) == 1 and one[0][0] == "season:winter" and ("longest night" in one[0][1] or "shortest" in one[0][1])


def _day(home=lambda: None):
    notes, sent = [], []
    state = Path(tempfile.mkdtemp()) / "s.json"
    d = se.SeasonDay(home=home, notice=notes.append, start=lambda: 10 * 60, state_file=state, send=sent.append)
    return d, notes, sent, state


def test_once_per_season_in_the_daytime_while_free():
    d, notes, sent, state = _day()
    assert d.due("sleep", _at(6, 20, 12)) is None            # not the day
    assert d.due("sleep", _at(6, 21, 9)) is None             # too early
    assert d.due("active", _at(6, 21, 12)) is None           # busy
    words, mood = d.due("sleep", _at(6, 21, 12))
    assert "summer" in words.lower() and sent == ["season:summer"] and notes
    assert [m for m, _, _ in d.steps][0] == "season:bills" and d.season == "summer"
    assert d.due("sleep", _at(6, 21, 13)) is None            # once
    assert json.loads(state.read_text()) == {"done": ["2026-summer"]}
    again = se.SeasonDay(notice=notes.append, start=lambda: 10 * 60, state_file=state)
    assert again.due("sleep", _at(6, 21, 14)) is None        # remembered across restarts
    assert d.due("sleep", _at(12, 21, 12))                   # winter is its own day
    d2, _, _, _ = _day()
    assert d2.due("sleep", _at(6, 21, 18, 30)) is None       # window over


def test_nobody_home_only_a_notice():
    d, notes, sent, _ = _day(home=lambda: False)
    assert d.due("sleep", _at(3, 20, 12)) is None
    assert notes == ["Happy first day of spring!"]


def test_small_days_can_be_turned_off():
    se.SMALL = False
    try:
        assert se.season_today(_at(12, 21)) is None and se.season_today(_at(6, 21)) == "summer"
    finally:
        se.SMALL = True


def test_celebrate_any_day():
    d, _, _, state = _day()
    steps = d.now_steps("summer", _at(11, 23))
    assert len(steps) == 4 and d.season == "summer" and d.steps == []
    assert not state.exists()                                # not the day: nothing used up


def test_shuffle_is_a_good_song_file():
    song = piano.load(se.SONG)
    assert song and song.title == "Sunny Day Shuffle" and song.about
    assert 20 < song.seconds < piano.MAX_SECONDS
    assert any(m is None for _, _, m, _ in song.notes)       # the snaps


def test_face_shades_sun_and_bills():
    face = FaceModel(800, 480, rng=random.Random(1))
    day, other = _at(6, 21), _at(11, 23)
    assert face.shades_on(day) and not face.shades_on(other)
    face.set_state("love", now=day)
    assert not face.shades_on(day)                           # happy ^ ^ eyes stay visible
    face.set_state("idle", now=other)
    face.set_season("bills", now=other)                      # any day: shades go on too
    assert face.breeze and face.shades_on(other + 1) and face.busy()
    face.update(0.1, other + se.BILLS_SECONDS + 5)
    assert face.breeze is None
    assert not face.shades_on(other + se.SHOW_SECONDS + 1)
    face.set_season("icecream", now=other)
    assert face.cone == other and face.shades_on(other + 1)
    calls = []

    class C:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append(name) or 10
    face.draw(C(), other + 5)
    assert face.cone and "text" in calls          # the "?" while she decides
    face.draw(C(), other + se.ICE_SECONDS + 1)
    assert face.cone is None
    face.set_season("winter", now=other)
    face.update(0.1, other + 1)
    assert face.season_drift.kind == "winter" and face.season_drift.items


def test_face_draws_everything():
    calls = []

    class C:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append(name) or 10

    for kind in ("bills", "icecream", "spring", "autumn", "winter"):
        face = FaceModel(800, 480, rng=random.Random(2))
        t = _at(11, 23)
        face.set_season(kind, now=t)
        for i in range(30):
            face.update(1 / 10, t + i / 10)
        face.draw(C(), t + 3)
    assert "polygon" in calls and "ellipse" in calls and "rrect" in calls


def test_wiring():
    src = open(SRC).read()
    assert 'Announcer("season", "Season", season_day.due, after="season")' in src
    assert src.index("season_ask = seasons.asked(prompt)") < src.index("thanks_ask = thanksgiving.asked(prompt)")
    assert 'news.after == "season"' in src
    assert 'key == "season"' in open(FACE).read()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)

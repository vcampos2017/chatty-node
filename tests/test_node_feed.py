"""node_feed.py: tides from NOAA and the time, posted on MQTT for the Matrix node."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import node_feed  # noqa: E402

NOW = 1_763_500_000      # 2025-11-18 21:06 UTC
NOAA = {"predictions": [{"t": "2025-11-19 03:30", "v": "1.905", "type": "H"},
                        {"t": "2025-11-18 20:48", "v": "0.402", "type": "L"},
                        {"t": "garbage", "v": "x", "type": "H"},
                        {"t": "2025-11-19 10:12", "v": "-0.150", "type": "L"}]}


def test_parse_sorts_and_skips_bad_rows():
    rows = node_feed.parse(NOAA)
    assert [r[2] for r in rows] == ["L", "H", "L"]
    assert rows[0][1] == 0.4 and rows[2][1] == -0.15
    assert node_feed.parse({"error": {"message": "No data"}}) == [] and node_feed.parse(None) == []


def test_url_starts_yesterday_and_names_only_the_station():
    u = node_feed.url("1234567", NOW)
    assert u.startswith("https://api.tidesandcurrents.noaa.gov/")
    assert "begin_date=20251117" in u and "station=1234567" in u and "interval=hilo" in u
    assert "lat" not in u and "lon" not in u


def test_feed_posts_tides_and_clock_and_retries():
    posts, asked = [], []

    def publish(topic, body, retain=True):
        posts.append((topic, body, retain))
        return True

    answer = [None]
    feed = node_feed.Feed(publish=publish, station="1234567",
                          fetch=lambda u: asked.append(u) or answer[0], clock=lambda: NOW)
    feed.step(NOW)                                   # NOAA said nothing useful
    assert ("chatty/clock", {"ts": NOW}, False) in posts
    assert not [p for p in posts if p[0] == "chatty/tides"] and feed.next_tides == NOW + node_feed.RETRY
    feed.step(NOW + 60)
    assert len(asked) == 1                           # waits 15 minutes before asking again
    answer[0] = NOAA
    feed.step(NOW + node_feed.RETRY)
    tides = [p for p in posts if p[0] == "chatty/tides"][-1]
    assert tides[2] is True and tides[1]["station"] == "1234567" and len(tides[1]["events"]) == 3
    assert feed.next_tides == NOW + node_feed.RETRY + node_feed.EVERY


def test_no_station_no_tides():
    posts = []
    feed = node_feed.Feed(publish=lambda t, b, retain=True: posts.append(t) or True, station="",
                          fetch=lambda u: 1 / 0)
    feed.step(NOW)
    assert posts == ["chatty/clock"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  ", name)

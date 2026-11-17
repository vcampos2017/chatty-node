"""Tests for the Matrix node (matrix_node/CIRCUITPY): clock, moon, news cards, finding
Chatty, and the whole app running on stand-ins for CircuitPython."""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "matrix_node", "CIRCUITPY"))
sys.path.insert(0, os.path.join(ROOT, "matrix_node", "sim"))

import chatty_clock as clock  # noqa: E402
import chatty_hub as hub  # noqa: E402
import chatty_moon as moon  # noqa: E402
import chatty_news as news  # noqa: E402
import chatty_art as art  # noqa: E402
import fake_circuitpython as fake  # noqa: E402


# ------------------------------------------------------------------ clock

def test_days_round_trip():
    for y, m, d in ((1970, 1, 1), (2000, 2, 29), (2026, 11, 17), (2099, 12, 31)):
        assert clock.civil_from_days(clock.days_from_civil(y, m, d)) == (y, m, d)
    assert clock.epoch(2000, 1, 1, 12) == moon.J2000


def test_weekday_and_sundays():
    assert clock.weekday(2026, 11, 17) == 1          # a Tuesday
    assert clock.nth_sunday(2026, 3, 2) == 8
    assert clock.nth_sunday(2026, 11, 1) == 1
    assert clock.nth_sunday(2026, 3, -1) == 29
    assert clock.nth_sunday(2026, 10, -1) == 25


def test_us_daylight_saving():
    zone = "America/New_York"
    before = clock.epoch(2026, 3, 8, 6, 59)          # 1:59 EST
    after = clock.epoch(2026, 3, 8, 7, 0)            # 3:00 EDT
    assert clock.offset(zone, before) == -5 * 3600
    assert clock.offset(zone, after) == -4 * 3600
    assert clock.offset(zone, clock.epoch(2026, 11, 1, 5, 59)) == -4 * 3600
    assert clock.offset(zone, clock.epoch(2026, 11, 1, 6, 0)) == -5 * 3600
    assert clock.offset("America/Phoenix", after) == -7 * 3600


def test_eu_daylight_saving_and_fixed():
    assert clock.offset("Europe/Berlin", clock.epoch(2026, 7, 1)) == 2 * 3600
    assert clock.offset("Europe/Berlin", clock.epoch(2026, 12, 1)) == 3600
    assert clock.offset("-07:00", 0) == -7 * 3600
    assert clock.offset("+05:30", 0) == 5 * 3600 + 1800
    assert clock.offset("Mars/Olympus", 0) == 0
    assert not clock.known("Mars/Olympus") and clock.known("UTC") and clock.known("-3")


def test_local_midnight_and_text():
    zone = "America/New_York"
    utc = clock.epoch(2026, 11, 17, 21, 30)          # 4:30 PM EST
    mid = clock.local_midnight(zone, utc)
    assert mid == clock.epoch(2026, 11, 17, 5)
    assert clock.hh_mm(15, 5) == "3:05" and clock.hh_mm(0, 0) == "12:00"
    assert clock.hh_mm(15, 5, twelve=False) == "15:05"
    assert clock.short_hour(15) == "3P" and clock.short_hour(0) == "12A"


def test_parse_iso():
    assert clock.parse_iso_utc("2026-02-17T05:12:34Z") == clock.epoch(2026, 2, 17, 5, 12, 34)
    assert clock.parse_iso_utc("2026-02-17T05:12:34+00:00") == clock.epoch(2026, 2, 17, 5, 12, 34)
    assert clock.parse_iso_utc("2026-02-17T00:12:34-05:00") == clock.epoch(2026, 2, 17, 5, 12, 34)
    assert clock.parse_iso_utc("garbage") is None


# ------------------------------------------------------------------ moon

def test_phase_at_known_new_and_full_moons():
    # full moon 2024-01-25 17:54 UTC, new moon 2024-01-11 11:57 UTC, full 2025-10-07 03:47
    p, lit = moon.illumination(clock.epoch(2024, 1, 25, 17, 54))
    assert abs(p - 0.5) < 0.03 and lit > 0.99
    p, lit = moon.illumination(clock.epoch(2024, 1, 11, 11, 57))
    assert min(p, 1 - p) < 0.03 and lit < 0.01
    p, lit = moon.illumination(clock.epoch(2025, 10, 7, 3, 47))
    assert abs(p - 0.5) < 0.03 and lit > 0.99
    assert moon.name(0.0) == "New moon" and moon.name(0.5) == "Full moon"
    assert moon.name(0.26) == "First quarter" and moon.name(0.99) == "New moon"


def test_moonrise_follows_the_phase():
    """Full moon rises around sunset, new moon around sunrise, about 50 min later a day."""
    lat, lon = 40.0, -100.0                          # a made-up spot
    def local_hours(day, when):
        start = clock.epoch(2024, 1, day) - int(lon / 15 * 3600)   # local mean midnight
        rise, sets = moon.rise_set(start, lat, lon)
        return (rise - start) / 3600 if rise else None, (sets - start) / 3600 if sets else None
    rise_full, _ = local_hours(25, None)
    assert 15.5 < rise_full < 19.5
    rise_new, _ = local_hours(11, None)
    assert 5.5 < rise_new < 9.5
    gaps = []
    for day in range(20, 24):
        a, _ = local_hours(day, None)
        b, _ = local_hours(day + 1, None)
        if a and b:
            gaps.append((b - a) * 60)
    assert gaps and all(20 < g < 90 for g in gaps)


def test_rise_and_set_alternate_and_next_event():
    lat, lon = 40.0, -100.0
    start = clock.epoch(2026, 11, 17, 7)
    today = moon.rise_set(start, lat, lon)
    tomorrow = moon.rise_set(start + 86400, lat, lon)
    for when in today + tomorrow:
        if when is not None:
            assert start <= when <= start + 2 * 86400
            assert abs(moon.altitude(when, lat, lon) - moon.RISE_ALT) < 0.01
    when, kind = moon.next_event(start, [today, tomorrow])
    assert kind in ("rise", "set") and when >= start
    assert moon.next_event(start, [(None, None)]) == (None, None)


def test_precision_trick_matches_plain_math():
    # the split angle must equal the plain formula (computers have big floats)
    di, df = moon._days(clock.epoch(2026, 11, 17, 21, 0))
    plain = (218.316 + 13.176396 * (di + df)) % 360
    assert abs(moon._angle(218.316, 13.176396, di, df) / moon.RAD - plain) < 1e-6


# ------------------------------------------------------------------ finding Chatty

def test_hosts_order_and_tailscale_skipped():
    note = hub.note_from(json.dumps({"lan": ["192.168.1.120"], "tailscale": "100.64.0.10",
                                     "known": {"HomeWiFi": "192.168.1.110",
                                               "ExtenderWiFi": "192.168.1.120"}}))
    hosts = hub.to_try("192.168.1.110", note, "192.168.1.50, 100.64.0.10")
    assert hosts == ["192.168.1.110", "192.168.1.120", "192.168.1.50", "chatty-node"]
    assert hub.note_from("not json") is None and hub.note_from("[1]") is None


def test_pack_unpack():
    note = {"lan": ["192.168.1.120"], "known": ["192.168.1.110"]}
    data = hub.pack("192.168.1.120", note)
    assert len(data) <= hub.MAX_SAVE
    assert hub.unpack(data + bytes(20)) == ("192.168.1.120", note)
    assert hub.unpack(bytes(64)) == (None, None)
    big = {"lan": ["1" * 40] * 3, "known": ["2" * 40] * 4}
    assert len(hub.pack("x", big)) <= hub.MAX_SAVE


# ------------------------------------------------------------------ news

NOW = clock.epoch(2026, 11, 17, 21, 0)


def hm(utc):
    p = clock.parts(utc - 5 * 3600)
    return p[3], p[4]


def test_tornado_warning_and_old_news():
    n = news.News()
    body = {"alerts": [{"event": "Tornado Warning", "kind": "urgent", "expires_ts": NOW + 1800},
                       {"event": "Flood Watch", "kind": "info", "expires_ts": None}], "ts": NOW - 60}
    n.message("chatty/alerts/active", json.dumps(body), NOW, 1000)
    assert n.tornado(NOW, 1000)["event"] == "Tornado Warning"
    cards = n.cards(NOW, 1000, hm)
    assert [c["scroll"] for c in cards if c["scroll"]] == ["FLOOD WATCH"]
    assert n.tornado(NOW + 1801, 1000) is None                  # expired
    assert n.tornado(NOW, 1000 + news.ALERTS_STALE + 1) is None  # no word from Chatty
    old = dict(body, ts=NOW - 3 * 3600)                          # an old retained list
    n.message("chatty/alerts/active", json.dumps(old), NOW, 2000)
    assert n.tornado(NOW, 2000) is None
    n.message("chatty/alerts/active", json.dumps({"alerts": [], "ts": NOW}), NOW, 2000)
    assert n.tornado(NOW, 2000) is None and n.cards(NOW, 2000, hm) == []


def test_alert_card_with_end_time():
    n = news.News()
    body = {"alerts": [{"event": "Severe Thunderstorm Warning", "kind": "urgent",
                        "expires_ts": clock.epoch(2026, 11, 18, 3, 45)}], "ts": NOW}
    n.message("chatty/alerts/active", json.dumps(body), NOW, 10)
    card = n.cards(NOW, 10, hm)[0]
    assert card["scroll"] == "SEVERE THUNDERSTORM WARNING TIL 10:45PM"
    assert card["color"] == news.ORANGE


def test_rain_now_and_rain_coming():
    n = news.News()
    n.message("chatty/forecast/rain", json.dumps({"rain_expected": True, "starts_ts": NOW + 3600,
                                                  "chance": 70, "kind": "rain", "ts": NOW}), NOW, 10)
    card = n.cards(NOW, 10, hm)[0]
    assert card["icon"] == "cloud" and card["lines"] == ["RAIN", "70%", "5P"]
    n.message("chatty/nodes/rain/data", json.dumps({"rate_mm_hr": 0, "tip_count": 5}), NOW, 20)
    assert not n.raining(20)
    n.message("chatty/nodes/rain/data", json.dumps({"rate_mm_hr": 0, "tip_count": 6,
                                                    "rain_in": 0.124}), NOW, 30)
    assert n.raining(30) and not n.raining(30 + news.RAIN_QUIET + 1)
    card = n.cards(NOW, 31, hm)[0]
    assert card["icon"] == "drop" and card["lines"] == ["RAIN", "NOW", '0.12"']


def test_lightning_flash_only_for_new_strikes():
    n = news.News()
    old = {"last_strike": {"ts": NOW - 7200, "distance_mi": 9}}
    assert n.message("chatty/nodes/lightning/data", json.dumps(old), NOW, 10) == []
    fresh = {"last_strike": {"ts": NOW - 20, "distance_km": 9.7}}
    events = n.message("chatty/nodes/lightning/data", json.dumps(fresh), NOW, 11)
    assert events and events[0][0] == "strike" and round(events[0][1]) == 6
    assert n.message("chatty/nodes/lightning/data", json.dumps(fresh), NOW, 12) == []
    card = [c for c in n.cards(NOW, 12, hm) if c["icon"] == "bolt"][0]
    assert card["lines"][0] == "6mi"
    # no clock yet: the first strike seen can't be told apart from an old one
    m = news.News()
    assert m.message("chatty/nodes/lightning/data", json.dumps(fresh), None, 5) == []


def test_greenhouse_and_nodes():
    n = news.News("matrix")
    n.message("chatty/nodes/greenhouse/data",
              json.dumps({"metrics": {"air_temperature_f": 71.6, "soil_moisture_band": "Dry"}}),
              NOW, 10)
    for name, state in (("rain", "online"), ("greenhouse", "online"), ("lightning", "offline"),
                        ("matrix", "online")):
        n.message("chatty/nodes/%s/status" % name, json.dumps({"state": state, "every": 60}),
                  NOW, 10)
    cards = n.cards(NOW, 10, hm)
    plant = [c for c in cards if c["icon"] == "leaf"][0]
    assert plant["lines"] == ["PLANT", "72F", "DRY"] and plant["color"] == news.ORANGE
    nodes = [c for c in cards if c["icon"] == "nodes"][0]
    assert nodes["lines"] == ["NODES", "2/3", "ZAP?"]
    assert n.online(10 + 400) == (0, 3)                           # everyone went silent


def test_soil_band():
    assert news.soil_band({"soil_moisture_band": "okay"}) == "ok"
    assert news.soil_band({"soil_moisture_percent": 20, "soil_voltage": 1.2}) == "dry"
    assert news.soil_band({"soil_moisture_percent": 100, "soil_voltage": 0.0}) is None
    assert news.soil_band({}) is None


def test_cards_fit_the_panel():
    n = news.News()
    n.message("chatty/forecast/rain", json.dumps({"rain_expected": True, "starts_ts": NOW + 9000,
                                                  "chance": 100, "kind": "storms", "ts": NOW}),
              NOW, 1)
    for c in n.cards(NOW, 1, hm):
        assert all(len(x) <= 5 for x in c["lines"])
        assert c["icon"] in art.ICONS


def test_icons_are_square():
    for name, rows in art.ICONS.items():
        assert len(rows) == art.SIZE and all(len(r) == art.SIZE for r in rows), name
        assert set("".join(rows)) <= set(".#+"), name


# ------------------------------------------------------------------ the whole app

class Clock:
    def __init__(self):
        self.ns = 10 ** 12

    def __call__(self):
        return self.ns

    def advance(self, seconds):
        self.ns += int(seconds * 1e9)


def make_app(clk, secrets=None):
    fake.BROKER.__init__()
    fake.install(secrets or {"ssid": "HomeWiFi", "password": "x", "timezone": "America/Denver",
                             "latitude": 40.0, "longitude": -100.0,
                             "mqtt_hosts": "10.0.0.9, 192.168.1.50"})
    time.monotonic_ns = clk
    import chatty_matrix
    import chatty_net
    net = chatty_net.Net("HomeWiFi", "x")
    start = NOW
    net.esp = fake.FakeESP(lambda: start + (clk.ns - 10 ** 12) // 10 ** 9)
    app = chatty_matrix.App(display=fake.FakeDisplay(), net=net)
    return app


def run(app, clk, seconds, fps=25):
    for _ in range(int(seconds * fps)):
        app.step()
        clk.advance(1 / fps)


def test_app_joins_the_network_and_shows_the_moon():
    real = time.monotonic_ns
    clk = Clock()
    try:
        app = make_app(clk)
        fake.BROKER.post("chatty/nodes/rain/status", {"state": "online", "every": 60})
        run(app, clk, 2)
        assert app.utc() is not None and app.link.host == "192.168.1.50"
        status = fake.BROKER.last("chatty/nodes/matrix/status")
        assert status["state"] == "online" and status["title"] == "Matrix clock"
        assert app.link.client.will[0] == "chatty/nodes/matrix/status"
        data = fake.BROKER.last("chatty/nodes/matrix/data")
        assert data["moon"]["name"] and 0 <= data["moon"]["lit"] <= 100
        assert app.mode == "clock" and app.screen.time.text != "--:--"
        assert app.screen.moon_tile[0].bitmap.path.startswith("moon/moon")
        # the address that worked is remembered for next time
        import microcontroller
        assert hub.unpack(microcontroller.nvm)[0] == "192.168.1.50"
    finally:
        time.monotonic_ns = real


def test_app_tornado_takes_over_and_lets_go():
    real = time.monotonic_ns
    clk = Clock()
    try:
        app = make_app(clk)
        run(app, clk, 2)
        utc = app.utc()
        fake.BROKER.post("chatty/alerts/active", {"alerts": [{"event": "Tornado Warning",
                                                              "kind": "urgent",
                                                              "expires_ts": utc + 900}],
                                                  "ts": utc})
        run(app, clk, 2)
        assert app.mode == "tornado" and not app.screen.frame.hidden
        assert "TORNADO WARNING UNTIL" in app.screen.scroll.text
        assert app.screen.moon.hidden
        run(app, clk, 30)                       # buttons-free, cards don't push it away
        assert app.mode == "tornado"
        fake.BROKER.post("chatty/alerts/active", {"alerts": [], "ts": app.utc()})
        run(app, clk, 2)
        assert app.mode == "clock" and app.screen.frame.hidden and not app.screen.moon.hidden
    finally:
        time.monotonic_ns = real


def test_app_news_round_rain_and_strike():
    real = time.monotonic_ns
    clk = Clock()
    try:
        app = make_app(clk)
        run(app, clk, 2)
        fake.BROKER.post("chatty/nodes/rain/data", {"rate_mm_hr": 1.2, "rain_in": 0.3,
                                                    "tip_count": 3})
        run(app, clk, 2)
        assert not app.screen.rain_grid.hidden and any(app.screen.rain_bmp.px)
        run(app, clk, 20)
        assert app.mode == "card" and app.card["icon"] == "drop"
        run(app, clk, 6)
        assert app.mode == "clock"
        fake.BROKER.post("chatty/nodes/lightning/data",
                         {"last_strike": {"ts": app.utc() - 5, "distance_mi": 3}})
        app.network(app.next_loop)              # read it now
        app.step()
        assert app.card["icon"] == "bolt" and not app.screen.flash.hidden
        run(app, clk, 1)
        assert app.screen.flash.hidden
    finally:
        time.monotonic_ns = real


def test_app_without_chatty_still_keeps_time():
    real = time.monotonic_ns
    clk = Clock()
    try:
        app = make_app(clk)
        fake.BROKER.reachable = set()
        run(app, clk, 3)
        assert app.link.client is None and app.utc() is not None
        assert app.screen.time.text != "--:--"
        fake.BROKER.reachable = {"192.168.1.50"}
        run(app, clk, 30)
        assert app.link.client is not None
    finally:
        time.monotonic_ns = real


def test_app_follows_chattys_note():
    real = time.monotonic_ns
    clk = Clock()
    try:
        app = make_app(clk)
        fake.BROKER.post("chatty/hub", {"lan": ["192.168.1.120"], "tailscale": "100.64.0.10",
                                        "known": {"HomeWiFi": "192.168.1.50"}})
        run(app, clk, 2)
        assert app.link.note["lan"] == ["192.168.1.120"]
        # she moved: the old address is gone, the note's new one answers
        fake.BROKER.reachable = {"192.168.1.120"}
        app.link.drop()
        run(app, clk, 10)
        assert app.link.host == "192.168.1.120"
    finally:
        time.monotonic_ns = real


def test_no_location_means_no_rise_times_but_a_moon():
    real = time.monotonic_ns
    clk = Clock()
    try:
        app = make_app(clk, {"ssid": "HomeWiFi", "password": "x", "mqtt_hosts": "192.168.1.50"})
        run(app, clk, 2)
        assert app.zone == "UTC" and "next" not in app.moon
        assert app.screen.event.y == -99 and app.screen.pct.text.endswith("%")
    finally:
        time.monotonic_ns = real


def test_portrait_cards_stay_on_the_panel():
    real = time.monotonic_ns
    clk = Clock()
    try:
        app = make_app(clk)
        from chatty_screen import Screen
        import chatty_screen
        fonts = chatty_screen.load_fonts()
        for rotation in (0, 90):
            screen = Screen(fake.FakeDisplay(), rotation, fonts)
            n = news.News()
            n.message("chatty/forecast/rain", json.dumps({"rain_expected": True, "chance": 70,
                                                          "starts_ts": NOW + 3600, "ts": NOW}),
                      NOW, 1)
            n.message("chatty/nodes/greenhouse/data",
                      json.dumps({"air_temperature_f": 70, "soil_moisture_band": "wet"}), NOW, 1)
            for card in n.cards(NOW, 1, hm):
                screen.show_card(card)
                assert 0 <= screen.icon.x and screen.icon.x + art.SIZE <= screen.w
                assert 0 <= screen.icon.y and screen.icon.y + art.SIZE <= screen.h
                for item in screen.lines:
                    if item.y != -99:
                        box = item.bounding_box
                        assert item.x >= 0 and item.x + box[2] <= screen.w, (rotation, item.text)
                        assert item.y - 5 >= 0 and item.y + 5 <= screen.h, (rotation, item.text)
            for risen in (True, False):
                info = {"phase": 0.3, "lit": 0.6, "next": "set" if risen else "rise",
                        "next_local": (21, 5)}
                screen.show_clock(clock.parts(NOW), info, True)
                for item in (screen.time, screen.date, screen.event):
                    assert item.x >= 0 and item.x + item.bounding_box[2] <= screen.w
    finally:
        time.monotonic_ns = real


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as ex:  # noqa: BLE001
                failed += 1
                import traceback
                traceback.print_exc()
                print("FAIL", name, repr(ex))
    sys.exit(1 if failed else 0)

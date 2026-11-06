import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_NIGHT_MODE"] = "0"
import self_care  # noqa: E402

T = 1_000_000.0
GOOD = {"temp": 55.0, "throttled": 0, "disk": (90e9, 117e9), "mem_mb": 1500.0,
        "ollama": True, "mic_age": 0.2}


class Pi:
    """Fake readings and a fake clock."""
    def __init__(self, night=False):
        self.r = dict(GOOD)
        self.now = T
        self.notes, self.phone = [], []
        self.w = self_care.Watcher(read=lambda: dict(self.r), clock=lambda: self.now,
                                   notice=self.notes.append, send=self.phone.append,
                                   is_night=lambda now: night)

    def tick(self, minutes=1, **change):
        self.r.update(change)
        self.now += minutes * 60
        self.w.check_once()


def test_all_good_is_quiet():
    pi = Pi()
    for _ in range(5):
        pi.tick()
    assert pi.notes == [] and pi.phone == [] and pi.w.due("sleep") is None
    assert pi.w.report(GOOD).startswith("I'm feeling great")


def test_warm_needs_two_checks_and_no_phone():
    pi = Pi()
    pi.tick(temp=77.0)
    assert pi.notes == []
    pi.tick()
    assert pi.notes == ["I'm running warm (77°C)"]
    assert "warm" in pi.w.due("sleep") and pi.phone == []
    # 72 is still within 5 degrees of the limit: not better yet
    pi.tick(temp=72.0); pi.tick(); pi.tick()
    assert len(pi.notes) == 1
    pi.tick(temp=60.0); pi.tick()
    assert len(pi.notes) == 1
    pi.tick()
    assert pi.notes[-1].startswith("Feeling better") and pi.phone == []


def test_too_hot_asks_for_help_and_phones_once():
    pi = Pi()
    pi.tick(temp=82.0); pi.tick()
    assert pi.notes[-1].startswith(self_care.ASK)
    assert len(pi.phone) == 1 and "too hot" in pi.phone[0]
    pi.tick(); pi.tick()
    assert len(pi.phone) == 1
    for _ in range(3):
        pi.tick(temp=60.0)
    assert pi.phone[-1] == "Chatty: Feeling better: I've cooled down to 60°C."


def test_warm_then_too_hot_tells_again():
    pi = Pi()
    pi.tick(temp=77.0); pi.tick()
    pi.tick(temp=81.0)
    assert len(pi.notes) == 2 and pi.notes[-1].startswith(self_care.ASK)
    assert len(pi.phone) == 1


def test_power_dip_since_boot():
    pi = Pi()
    pi.tick(throttled=0x50000)
    assert "power" in pi.notes[0].lower() and len(pi.phone) == 1
    assert "dipped" in pi.w.due("sleep")


def test_ollama_down_phones_after_ten_minutes():
    pi = Pi()
    pi.tick(ollama=False); pi.tick(); pi.tick()
    assert pi.notes and "Ollama" in pi.notes[0] and pi.phone == []
    for _ in range(10):
        pi.tick()
    assert len(pi.phone) == 1
    pi.tick(ollama=True)
    assert pi.notes[-1] == "Feeling better: my thinking model is back"
    assert len(pi.phone) == 2


def test_deaf_mic():
    pi = Pi()
    pi.tick(mic_age=45.0)
    assert "microphone" in pi.notes[0] and pi.phone == []
    for _ in range(5):
        pi.tick()
    assert len(pi.phone) == 1
    pi.tick(mic_age=0.1)
    assert pi.notes[-1] == "Feeling better: I can hear again"


def test_disk_and_memory():
    pi = Pi()
    pi.tick(disk=(8e9, 117e9))
    assert "getting full" in pi.notes[0] and pi.phone == []
    pi.tick(disk=(0.5e9, 117e9))
    assert "almost full" in pi.notes[-1] and len(pi.phone) == 1
    pi.tick(mem_mb=100.0); pi.tick(); pi.tick()
    assert "working memory" in pi.notes[-1] and len(pi.phone) == 1


def test_unreadable_parts_are_left_alone():
    pi = Pi()
    pi.tick(temp=None, throttled=None, disk=None, mem_mb=None, ollama=None, mic_age=None)
    assert pi.notes == []
    assert pi.w.report().startswith("I'm feeling great")


def test_night_shows_but_never_speaks():
    pi = Pi(night=True)
    pi.tick(temp=82.0); pi.tick()
    assert pi.notes and len(pi.phone) == 1
    assert pi.w.due("sleep") is None


def test_speech_waits_until_she_is_free_and_goes_stale():
    pi = Pi()
    pi.tick(temp=77.0); pi.tick()
    assert pi.w.due("active") is None
    pi.now += 2 * 3600
    assert pi.w.due("sleep") is None


def test_report_mentions_trouble():
    pi = Pi()
    r = dict(GOOD, ollama=False)
    text = pi.w.report(r)
    assert text.startswith("Mostly okay") and "Ollama" in text
    assert self_care.ASK not in text
    good = pi.w.report(GOOD)
    assert "55 degrees" in good and "90 gigabytes" in good and "ears are working" in good


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

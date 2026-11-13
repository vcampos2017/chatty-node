"""
The things Chatty says on her own, in one line-up: the morning briefing, the
bedtime wind-down, rain on the way, rain or lightning starting, her own health,
and "Welcome home". Each one keeps its own rules (time of day, once a day, only
while she's free...) in its own module; this file only asks them in order and
hands back the first one that has something to say.

Moved out of chatty_voice_node.py's main loop (2026-11-13) with no change in
behavior: same order, same "first one wins this round", the rest wait for the
next round. Weather alerts, Red Alert, timers, door letters and the face's
notices stay in the voice node (they each do more than "say it, then sleep").

    lineup = Lineup([
        Announcer("morning_briefing", "Morning briefing", morning.due),
        Announcer("bedtime", "Bedtime", winddown.due, after="tuck_in"),
    ])
    news = lineup.next_due(free_mode)
    if news:
        say(*news.say_args)
"""
from dataclasses import dataclass
from typing import Callable, Optional, Sequence


@dataclass
class Announcer:
    kind: str                  # the conversation log's name for it ("rain_ahead")
    label: str                 # the console line's name for it ("Rain watch")
    due: Callable              # due(mode) -> text, (text, mood, ...) or nothing
    after: str = "sleep"       # what she does afterwards: "sleep" or "tuck_in" (bedtime)


@dataclass
class News:
    announcer: Announcer
    say_args: tuple            # what to pass to say(): (text,) or (text, mood)

    @property
    def kind(self) -> str:
        return self.announcer.kind

    @property
    def label(self) -> str:
        return self.announcer.label

    @property
    def text(self) -> str:
        return self.say_args[0]

    @property
    def after(self) -> str:
        return self.announcer.after


class Lineup:
    def __init__(self, announcers: Sequence[Announcer]):
        self.announcers = list(announcers)

    def next_due(self, mode: str) -> Optional[News]:
        """Ask each in order; the first with something to say wins. The ones after
        it aren't asked this round (just like the old chain of `continue`s)."""
        for a in self.announcers:
            got = a.due(mode)
            if got:
                return News(a, tuple(got) if isinstance(got, (tuple, list)) else (got,))
        return None

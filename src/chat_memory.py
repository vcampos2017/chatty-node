"""
A short memory of the conversation, so Chatty can follow along.

She keeps the last few exchanges (what you said, what she answered) from every tier:
built-in answers like the greenhouse reading, things you asked her to remember, the
small Pi model and the relay. The small Pi model sees them with each new question, so
"please" or "what about the air?" make sense after what came before.

It is one conversation, whether you talk out loud or type on the remote panel, and it
lasts until nobody has said anything for CHATTY_CONTEXT_MINUTES. Then she forgets it.

Privacy: it lives only in RAM on the Pi (never written to disk), "change the subject"
or putting her to bed wipes it, and none of it goes to the cloud except one earlier
exchange for a very short follow-up, which the privacy checker sees first.

Settings:
  CHATTY_CONTEXT          1 = on (default), 0 = every question stands alone again
  CHATTY_CONTEXT_TURNS    exchanges kept (default 3; each costs the Pi a little time)
  CHATTY_CONTEXT_MINUTES  forget after this long without a word (default 5)
"""
from __future__ import annotations

import os
import re
import time
import uuid
from collections import deque
from typing import Callable, Deque, List, Optional, Tuple

ENABLED = os.getenv("CHATTY_CONTEXT", "1") != "0"
TURNS = max(1, int(os.getenv("CHATTY_CONTEXT_TURNS", "3")))
IDLE_SECONDS = float(os.getenv("CHATTY_CONTEXT_MINUTES", "5")) * 60
MAX_CHARS = 160           # per line: a Pi 4 reads prompts slowly, keep them short
FOLLOWUP_WORDS = 6        # "yes please", "what about tomorrow?": short enough to need context

# "another one", "please go on", "tell me more": asking for the same thing again
MORE = re.compile(
    r"^(please |ok(ay)? |chatty )*(tell me |give me |do |say )?(another( one)?|one more( time)?|more|"
    r"go on|keep going|again|the next one|next)( one)?( please| chatty)*$")

CHANGE_SUBJECT = re.compile(
    r"^(let'?s |can we )?(change the subject|new topic|start over|forget (what i (just )?said|that|our conversation))$")


def _trim(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS].rsplit(" ", 1)[0] + "..."


class ChatMemory:
    def __init__(self, turns: int = TURNS, idle_seconds: float = IDLE_SECONDS,
                 enabled: bool = ENABLED, clock: Callable[[], float] = time.time):
        self.enabled = enabled
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.turns: Deque[Tuple[str, str]] = deque(maxlen=turns)
        self.last = 0.0
        self.conversation_id = uuid.uuid4().hex

    def _expire(self) -> None:
        if self.turns and self.clock() - self.last > self.idle_seconds:
            self.forget()

    def fresh(self) -> bool:
        """True while a conversation is still going (something said lately)."""
        self._expire()
        return bool(self.turns)

    def session_id(self) -> str:
        """The same id while the conversation is fresh, a new one after it expires,
        so the relay's own history (by session) follows along too."""
        if not self.fresh():
            self.conversation_id = uuid.uuid4().hex
        return self.conversation_id

    def add(self, user: str, reply: str) -> None:
        if not self.enabled or not (user or "").strip() or not (reply or "").strip():
            return
        self._expire()
        self.turns.append((_trim(user), _trim(reply)))
        self.last = self.clock()

    def messages(self) -> List[dict]:
        """The recent exchanges as chat messages for the Pi model (oldest first)."""
        self._expire()
        out: List[dict] = []
        for user, reply in self.turns:
            out.append({"role": "user", "content": user})
            out.append({"role": "assistant", "content": reply})
        return out

    def for_relay(self, prompt: str) -> str:
        """A very short follow-up ("please", "yes", "what about tomorrow") gets the one
        exchange before it, so the relay knows what it answers. Longer questions go as
        they are."""
        self._expire()
        if not self.turns or len((prompt or "").split()) > FOLLOWUP_WORDS:
            return prompt
        user, reply = self.turns[-1]
        return (f"(Earlier I was asked: \"{user}\" and I answered: \"{reply}\")\n"
                f"Now they say: {prompt}")

    def expand(self, prompt: str) -> str:
        """'Another one' after 'tell me a fun fact about cats' becomes 'tell me a fun fact
        about cats, a different one than before'. The tiny Pi model loses the thread on a
        bare 'another one' (it drifted off to music and hobbies); a whole question keeps it
        on topic. Kept as the expanded question, so 'another one' again still works."""
        self._expire()
        if not self.turns or not MORE.match((prompt or "").strip().lower()):
            return prompt
        last = self.turns[-1][0]
        if "eliza" in last.lower():
            return "tell me more about eliza"   # a new fact each time, not the same blurb
        last = re.sub(r", a different one than before$", "", last)
        return f"{last}, a different one than before"

    def forget(self) -> None:
        self.turns.clear()
        self.last = 0.0

    @staticmethod
    def wants_new_subject(prompt: str) -> bool:
        return bool(CHANGE_SUBJECT.match((prompt or "").strip().lower()))


if __name__ == "__main__":
    m = ChatMemory()
    m.add("chatty im not at home right now", "Thanks for letting me know! How can I help while you're away?")
    m.add("what is the temperature in the greenhouse", "It's 65 degrees in there. The plants are thirsty!")
    for msg in m.messages():
        print(f"{msg['role']:>9}: {msg['content']}")
    print(m.for_relay("please"))

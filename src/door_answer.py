"""
How Chatty works out her answer to a letter through the message door (door.py).

Answer-only, never a command, never from her memories. In order:
  1. the door's own answers (door.own_answer: hello, who are you...)
  2. her local skills (time, weather, greenhouse...)
  3. the small Pi model, unless the question is a fact the Pi shouldn't guess
     (fact_check.skip_local) and the cloud is allowed for letters
  4. the paid relay, only with CHATTY_DOOR_CLOUD=1 and nothing private in it,
     fact-checked; if the relay fails, the Pi's own guess, hedged
A private-looking letter never leaves the Pi (nobody is there to ask).

Moved out of chatty_voice_node.py unchanged (split step 5, 2026-11-14). The voice
node passes in the slow calls (wrapped so a Red Alert can cut in: its RedCutIn is
a BaseException, so it passes straight through here) and does the speaking.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, Optional

import door as door_mod
import fact_check
import privacy
from words import normalize

FALLBACK = "That's a bigger question than I can answer on my own right now."
NOT_OVER_THE_NETWORK = "I'd rather not send that over the network. Ask me in person, okay?"


@dataclass
class Answer:
    reply: str              # what goes back through the door
    tier: str               # door / skill / local_llm / relay
    private: bool           # the letter looked private (so it isn't read out loud)
    failed: bool = False    # something went wrong; reply is the fallback line


def work_out(m: dict, skills: Callable[[str], Optional[str]],
             ask_local: Callable[..., Optional[str]], ask_relay: Callable[..., str],
             cloud: Optional[bool] = None) -> Answer:
    """skills(prompt); ask_local(prompt, session_id); ask_relay(text, session_id, timeout=...)."""
    cloud = door_mod.CLOUD if cloud is None else cloud
    text = m["text"]
    prompt = normalize(text)
    private = bool(privacy.find(text))
    tier, reply = "door", door_mod.own_answer(text)
    local_guess = None
    failed = False
    try:
        if reply is None:
            tier = "skill"
            reply = skills(prompt)
        if reply is None:
            tier = "local_llm"
            if not (cloud and not private and fact_check.skip_local(prompt)):
                reply = ask_local(prompt, f"door-{m['from']}")
            if reply is not None and cloud and not private \
                    and not fact_check.keep_local(prompt, reply):
                local_guess, reply = reply, None
        if reply is None and cloud and not private:
            tier = "relay"
            try:
                reply = ask_relay(text, f"door-{m['from']}")
                reply, _ = fact_check.review(
                    text, reply,
                    lambda t: ask_relay(t, f"check-{uuid.uuid4().hex[:8]}",
                                        timeout=fact_check.SECONDS))
            except Exception:
                if not local_guess:
                    raise
                tier, reply = "local_llm", fact_check.hedge(local_guess)
    except Exception as e:
        print("Message door: answer failed:", repr(e), flush=True)
        reply, failed = None, True
    if not reply:
        reply = FALLBACK
    return Answer(reply, tier, private, failed)


def safe_to_send(reply: str) -> str:
    """Her reply goes over MQTT (not encrypted): nothing private-looking in it."""
    return NOT_OVER_THE_NETWORK if privacy.find(reply) else reply

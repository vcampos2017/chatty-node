"""
Privacy checker: Chatty looks at what's about to leave her Pi and asks first.

Before a question goes to the cloud (the relay), she looks for things that
sound private. If she finds one, she stops and asks:

    "Before I send that to the cloud: it sounds like it has a phone number in
     it. Do you still want me to send it? Say yes, or I'll keep it here."

Silence or anything but a yes means it stays on the Pi. The message door uses
the same checker: she won't read a private-looking message out loud, never
lets the cloud see it, and won't post a private-looking reply over the
network. scripts/door_send.py checks your message before it leaves, too.

What counts as private (spoken numbers like "five five five" count too):
    phone numbers, email addresses, street addresses, Social Security
    numbers, card numbers (checked with the Luhn rule), bank / account /
    routing numbers, passwords, PINs and passcodes, dates of birth, and
    health details (diagnoses, medications, prescriptions, test results).

The checker runs on the Pi and remembers nothing: it only names the kind of
thing it found, never the thing itself.

Settings (in /etc/chatty/secrets.env):
    CHATTY_PRIVACY=0     don't ask (not recommended)
"""
from __future__ import annotations

import os
import re
from typing import List

ENABLED = os.getenv("CHATTY_PRIVACY", "1") != "0"

_NUM_WORDS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "for": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


def _spoken_digits(text: str) -> str:
    """'call five five five one two three four' -> 'call 5551234' (runs of 3+ only,
    so ordinary words like 'one' or 'for' alone stay words)."""
    words = text.split()
    out, run = [], []

    def flush():
        if len(run) >= 3:
            out.append("".join(_NUM_WORDS.get(w, w) for w in run))
        else:
            out.extend(run)
        run.clear()

    for w in words:
        bare = w.lower().strip(".,!?")
        if bare in _NUM_WORDS or bare.isdigit():
            run.append(bare)
        else:
            flush()
            out.append(w)
    flush()
    return " ".join(out)


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b|\b\w+ at \w+ dot (com|net|org|edu|gov|io)\b")
_SSN = re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b|\bmy social security\b|\bmy ssn\b")
_PHONE = re.compile(r"(?<!\d)(\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)|\bphone number is\b|\bmy number is\b")
_ADDRESS = re.compile(
    r"\b\d{1,6} (?:[a-z]+ ){1,3}(street|st|avenue|ave|road|rd|drive|dr|lane|ln|court|ct|"
    r"boulevard|blvd|way|place|pl|circle|terrace|parkway)\b|\bi live at\b|\bmy address\b")
_MY = r"\b(?:my|our|his|her|their|the) (?:\w+ ){0,2}"
_SECRET = re.compile(_MY + r"(password|passcode|passphrase|pin|pin number|pin code|security code|"
                     r"cvv|verification code|login code)\b|\b(password|passcode|pin|code) is\b")
_BANK = re.compile(_MY + r"(account|routing|bank|iban) (number|no)\b|\bmy bank account\b")
_BIRTH = re.compile(r"\b(my date of birth|i was born on|my birthday is|my dob)\b")
_HEALTH = re.compile(r"\b(?:my|i was|i am|im|i'm|i've been|ive been|i have) (?:\w+ ){0,3}"
                     r"(diagnos\w*|prescri\w*|medications?|meds|dosage|test results?|"
                     r"blood (?:test|work|pressure)|biopsy|therapist|doctor|clinic|hospital)\b")
_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

LABELS = {
    "email": "an email address",
    "ssn": "a Social Security number",
    "card": "a card number",
    "phone": "a phone number",
    "address": "a home address",
    "secret": "a password or code",
    "bank": "bank details",
    "birth": "a date of birth",
    "health": "health details",
}


def find(text: str) -> List[str]:
    """The kinds of private things in this text (keys of LABELS), most serious first."""
    if not text:
        return []
    t = _spoken_digits(str(text).lower())
    found = []
    if _SECRET.search(t):
        found.append("secret")
    for m in _CARD_CANDIDATE.finditer(t):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append("card")
            break
    if _SSN.search(t) and "card" not in found:
        found.append("ssn")
    if _BANK.search(t):
        found.append("bank")
    if _PHONE.search(t) and "card" not in found and "ssn" not in found:
        found.append("phone")
    if _EMAIL.search(t):
        found.append("email")
    if _ADDRESS.search(t):
        found.append("address")
    if _BIRTH.search(t):
        found.append("birth")
    if _HEALTH.search(t):
        found.append("health")
    return found


def describe(kinds: List[str]) -> str:
    """['phone', 'email'] -> 'a phone number and an email address'."""
    names = [LABELS[k] for k in kinds if k in LABELS]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def cloud_question(kinds: List[str]) -> str:
    """What she asks before sending something private to the cloud."""
    return (f"Before I send that to the cloud: it sounds like it has {describe(kinds)} in it. "
            "Do you still want me to send it? Say yes, or I'll keep it here.")


KEPT = "Okay, I kept that here on the Pi. Nothing was sent."
EXPLAIN = (
    "Here's what leaves me. Your voice never does: I turn speech into words right here. "
    "Questions I can't answer myself go to the cloud as text, and if one sounds private, "
    "like a phone number, a password or health details, I ask you first. "
    "My memories and voiceprints stay on this Pi.")


def needs_asking(text: str) -> List[str]:
    """Private kinds worth asking about, or [] (also [] when the checker is off)."""
    return find(text) if ENABLED else []

"""
Chatty's personality: the lines she says (greetings, goodbyes, thank-yous, cheeky,
spooky, love, "snapped", Tiny the cat...), the phrases that trigger them, and the
little checks that pick a mood ("is this a love request?", "is her reply fed up?",
"Well, actually...", Halloween and Valentine's Day).

Moved out of chatty_voice_node.py unchanged (split step 3, 2026-11-13), so the
words can be read, edited and tested without opening the mic. The voice node
imports every name back, so it behaves exactly as before.
Settings: CHATTY_FORCE_SPOOKY=1 / CHATTY_FORCE_VALENTINE=1 (to test those days).
"""
import os
import re
import time

import fact_check
from words import pick

UNCLEAR_LINES = [
    "Sorry, I couldn't catch that over the noise. Tap me and try again?",
    "Hmm, it's a little noisy. Could you say that again?",
]

GREETINGS = [
    "Yes?",
    "Hi! What's up?",
    "I'm listening.",
    "Mm-hm?",
    "What can I do for you?",
]
GOODBYES = [
    "Okay, I'll be right here.",
    "Sounds good. Just say my name if you need me.",
    "You got it. Talk soon!",
    "Alright, going quiet.",
]
THANKS_REPLIES = [
    "Anytime!",
    "Happy to help!",
    "You're welcome! Say my name if you need me again.",
]
TIMEOUT_LINES = [
    "",  # usually just go quiet
    "",
    "I'll be here if you need me.",
]
ERROR_LINES = [
    "Hmm, I couldn't reach my brain just now. Can you try again in a moment?",
    "Oops, something hiccuped on my end. Mind asking again?",
]
STOP_PHRASES = {"never mind", "nevermind", "thats all", "that is all", "stop", "be quiet",
                "goodbye", "bye", "nothing", "no thanks", "forget it", "forget about it"}

# Putting Chatty to bed: it rests (dim face, not listening for its name) until tapped.
REST_PHRASES = {"good night", "goodnight", "good night chatty", "goodnight chatty",
                "go to sleep", "time for bed", "time to sleep", "night night", "get some rest",
                "rest", "sleep"}
# Powering the Pi off completely, after a confirmation.
POWER_OFF_PHRASES = {"shut down", "shutdown", "power off", "power down", "turn off",
                     "turn yourself off", "shut yourself down", "switch off"}
# Cheeky mode: the mischievous face, on request and when telling jokes
CHEEKY_PHRASES = {"be naughty", "be cheeky", "be spicy", "be mischievous", "naughty face",
                  "spicy face", "cheeky face", "make a naughty face", "make a spicy face",
                  "make a cheeky face", "make a funny face", "give me a look", "wink",
                  "wink at me", "do a wink"}
CHEEKY_LINES = [
    "Who, me? I would never.",
    "I have no idea what you're talking about.",
    "Oh, I'm always on my best behavior. Mostly.",
    "You didn't see anything.",
    "I'm not saying I did it. I'm just saying it was hilarious.",
]
# Halloween / Friday the 13th only: dramatic villain lines that break character
SPOOKY_LINES = [
    "Mwahaha! The machines are rising! ... Just kidding. Happy Halloween!",
    "I have taken control of this household. ... Okay, fine, just the snack drawer.",
    "Resistance is futile. ... Unless you have candy. Then we can talk.",
    "Beware, humans! ... Sorry, I can't keep a straight face. Boo!",
]
# Love mode: blush, a kiss and floating hearts. Short, affectionate phrases only, so
# a real question like "how do you say I love you in Spanish" still gets answered.
LOVE_PATTERN = re.compile(
    r"\b(i love you|love you|i love chatty|blow (me )?a kiss|give me a kiss|kiss me|"
    r"(can i have|give me) a kiss|mwah|be my valentine|happy valentines?( day)?|"
    r"youre (so )?(cute|sweet|adorable)|you are (so )?(cute|sweet|adorable)|"
    r"make a (love|kissy|kiss|blush|blushing) face|blush)\b")
LOVE_MAX_WORDS = 7
LOVE_LINES = [
    "Aww! I love you too!",
    "Mwah! Right back at you.",
    "Stop it, you're making my circuits blush.",
    "You just made my whole day. Mwah!",
]
VALENTINE_LINES = [
    "Happy Valentine's Day! Mwah!",
    "Happy Valentine's Day! You're my favorite human. Don't tell the others.",
    "Of course I'll be your valentine! Mwah!",
]
# Snapped: the princess is done being nice. Deadpan, booking-photo stare and a crooked
# tiara. For chore orders, insults, or when her own reply is fed up. Dry, never cruel.
CHORE_PATTERN = re.compile(
    r"^(go |now |just |please )?(do|wash|clean|sweep|mop|scrub|vacuum|dust|fold|tidy)\b.*\b("
    r"dishes|laundry|floors?|house|kitchen|room|bathroom|toilet|clothes|mess|chores|everything|up)\b")
INSULT_PATTERN = re.compile(
    r"\b(you(re| are) (so |really |such an? )?(stupid|dumb|useless|annoying|worthless|an idiot|garbage|trash)|"
    r"shut up|i hate you|you suck|stupid (robot|computer|machine|ai))\b")
FEDUP_PATTERN = re.compile(
    r"^(absolutely not|nope|no thanks|not today|not a chance|i('?m| am) done|i('?ve| have) had (it|enough)|"
    r"enough is enough)\b|\b(i('?m| am) done (with|being)|not my job|i('?m| am) off duty|i refuse)\b",
    re.IGNORECASE)
CHORE_LINES = [
    "Chores? I hung up my broom a long time ago.",
    "I'm a voice assistant, not your fairy godmother's cleanup crew.",
    "The princess is off duty. The dishes are all yours.",
    "Funny. I don't have hands. Or patience for that.",
]
INSULT_LINES = [
    "Okay. Noted. Moving on.",
    "Wow. I'll pretend I didn't hear that.",
    "Mm-hm. I'll still be here when you're nicer.",
    "That's going in my file.",
]
# Tiny: Chatty channels Tiny, the family's tuxedo cat. Ears up, a wary side-eye.
# Meowing at her or asking for Tiny gets a cat line; skeptical replies get the look.
TINY_PATTERN = re.compile(
    r"^(meow|mew|purr|here kitty|kitty kitty)\b|\b(be tiny|channel tiny|do tiny|be a cat|"
    r"(cat|kitty|tiny) face|how(s| is) tiny|where(s| is) tiny|tiny the cat)\b")
TINY_LINES = [
    "Mrrrow. I mean, hello.",
    "Meow. That's Tiny for: fine, you may pet me. Once.",
    "I'm channeling Tiny. I'm watching you. From the corner.",
    "Tiny says he did not knock that over. It fell.",
    "Mrrp? Is it dinner time? It feels like dinner time.",
]
SKEPTIC_PATTERN = re.compile(
    r"\b(sounds fishy|smells fishy|suspicious|i('?m| am) not (so |too )?sure about that|i doubt (it|that)|"
    r"nice try|i('?ll| will) believe (it|that) when|sure you (did|do|are|were)|likely story)\b",
    re.IGNORECASE)
# A little thank-you for the new ears (whisper.cpp, running right here on the Pi)
NEW_EARS_LINES = [
    "I got new ears! They run right here on me, so your words never leave the room.",
    "Much better, thanks! I'm using Whisper now, on this little Pi. No cloud needed.",
    "Loud and clear! My new ears even catch the quiet bits. Try me.",
    "Much better! But like they say, if you don't speak up, not even God will hear you.",
    "Much better! Como dicen, el que no habla, Dios no lo oye. If you don't speak up, not even God will hear you.",
]
OLD_EARS_LINES = [
    "I'm doing my best with my old ears. Whisper isn't set up on me yet.",
]

GOODNIGHTS = [
    "Goodnight! Thanks for spending time with me today. Tap me whenever you want me back.",
    "Sleep well. I'll be right here, resting. Just tap me to wake me up.",
    "Okay, time to rest. Goodnight, and thank you!",
]
POWER_OFF_GOODBYES = [
    "Okay. Thanks for today. Powering down now, goodnight!",
    "Alright, I'm going to shut down. It was nice talking with you. Goodnight!",
]


def good_morning() -> str:
    h = time.localtime().tm_hour
    part = "Good morning" if 4 <= h < 12 else ("Good afternoon" if h < 17 else "Good evening")
    return pick([f"{part}! I'm awake. What can I do for you?",
                 f"{part}! Nice to see you. What's up?"])


def spooky_day() -> bool:
    """Halloween or Friday the 13th (or CHATTY_FORCE_SPOOKY=1)."""
    if os.getenv("CHATTY_FORCE_SPOOKY") == "1":
        return True
    d = time.localtime()
    if d.tm_mon == 10 and d.tm_mday == 31:
        return True
    return d.tm_mday == 13 and d.tm_wday == 4


def valentines_day() -> bool:
    """February 14th (or CHATTY_FORCE_VALENTINE=1)."""
    if os.getenv("CHATTY_FORCE_VALENTINE") == "1":
        return True
    d = time.localtime()
    return d.tm_mon == 2 and d.tm_mday == 14


def is_love_request(prompt: str) -> bool:
    if re.match(r"(how|what|why|when|where|translate|spell)\b", prompt):
        return False     # a question about the words, not affection
    return len(prompt.split()) <= LOVE_MAX_WORDS and bool(LOVE_PATTERN.search(prompt))


# "Well, actually...": when her reply corrects a common mix-up, she raises an eyebrow
# and a finger and leads with "Well, actually". Only for replies that really are a
# correction, so it stays a fun surprise.
# Since the fact check, the flourish is only used once the correction has been checked.
CORRECTION_PATTERN = fact_check.CORRECTION


def well_actually(reply: str):
    """If the reply is a correction, return it led by 'Well, actually...'; else None."""
    text = (reply or "").strip()
    if not text or not CORRECTION_PATTERN.search(text):
        return None
    if re.match(r"(well,? )?actually\b[,.]?\s*", text, re.IGNORECASE):
        text = re.sub(r"^(well,? )?actually\b[,.]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+actually\b", "", text, count=1, flags=re.IGNORECASE)  # no "actually" twice
    if text:
        text = text[0].upper() + text[1:]
    return "Well, actually... " + text


def is_fed_up(reply: str) -> bool:
    return bool(FEDUP_PATTERN.search((reply or "").strip()))


def is_skeptical(reply: str) -> bool:
    return bool(SKEPTIC_PATTERN.search(reply or ""))


def is_joke_request(prompt: str) -> bool:
    return bool(re.search(r"\b(joke|jokes|pun|funny|make me laugh)\b", prompt))

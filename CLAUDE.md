# Chatty Node: notes for coding sessions

Read this first. It sums up how Chatty works, how changes get to the Pi, and what
has been decided so far. Keep it current when something important changes.

## Who and what
- Owner: Vincent (GitHub vcampos2017). He tests everything on the real Pi over SSH
  (Termius) and pastes logs and photos back. Give him one command per line, with
  clear "run this in the CHATTY / GREENHOUSE window" labels (he has both open,
  and they're easy to mix up).
- Chatty ("she/her") is a privacy-first voice assistant on a Raspberry Pi 4 with a
  touchscreen face, inspired by Chatty from his hopecyberpunk story universe
  (ceucomics.com): a local, decentralized AI that talks with other Chatty nodes.
  Warm, playful, never "evil AI" (the spooky face only on Halloween / Friday the 13th).
- Budget matters: answer locally first, pay for cloud only when needed.

## Hardware and network
- Chatty: Raspberry Pi 4 (about 3.7 GB RAM), touchscreen, Anker PowerConf A3301
  mic/speaker (`plughw:CARD=PowerConf,DEV=0`, record at 16 kHz).
- Tailscale names: chatty-node 100.69.130.79, greenhouse-pi 100.114.76.44 (Pi Zero 2 W),
  lightning-node 100.70.181.127, talliupper (Windows PC), iphone171.
- The other nodes answer `GET :5000/status` with JSON. Greenhouse example:
  `{"metrics":{"soil_moisture_percent":..,"soil_voltage":..,"air_temperature_f":..,
  "air_humidity":..,"soil_moisture_band":..},"node":"greenhouse-node"}`.
  Rain gauge: `rain_in, rain_mm, rate_mm_hr, tip_count`. Lightning has no web page
  yet (old code reads its log over ssh).
- Greenhouse Pi runs `greenhouse.service` (`~/projects/greenhouse-node/main.py`,
  settings in `/etc/greenhouse.env`) on WiFi "AVC-2G".

## Deploying to the Pi
Everything lives on `main` (love-face / chatty-personality were merged in on
2026-10-23). On the Pi:
```
cd ~/chatty-node
git fetch origin
git checkout main
git pull
sudo systemctl restart chatty-voice
./scripts/start_face.sh
```
- `status.json` is written by Chatty at runtime and is no longer tracked by git.
- SSH login announcer: separate service `chatty-ssh-announce`
  (`scripts/ssh_announcer.py`, install once with `bash scripts/install_ssh_announcer.sh`).
  Says "User pi logged on, from Tailscale", "SSH session ended", and "Possible
  suspicious activity" for failed attempts; 5+ failures in 10 minutes (or a login
  from the internet) adds "Requesting your assistance, please". Failed attempts,
  internet logins and requests for help also go to the phone via IFTTT event
  `chatty_alert`. Settings in `/etc/chatty/ssh_announcer.env`.
- Night mode (`src/quiet_hours.py`, CHATTY_NIGHT_START=22 / CHATTY_NIGHT_END=7,
  CHATTY_NIGHT_MODE=0 to turn off): things she'd say on her own are shown on the
  face as amber notices instead (`notice:` UDP message). The first tap dismisses
  notices without waking her. She still answers "Hey Chatty" as usual. So far
  the SSH announcer uses it; urgent NWS warnings still speak at night
  (CHATTY_ALERTS_NIGHT=0 to stop that).
- Settings and secrets: `/etc/chatty/secrets.env` (never in the repo). The voice
  node loads it at the very top of `chatty_voice_node.py`, BEFORE importing modules,
  because modules read settings when imported.
- Logs: `journalctl -u chatty-voice -f` (voice), `/tmp/chatty_face.log` (face).
- If a pasted command shows `[200~`, run `echo "set enable-bracketed-paste off" >> ~/.inputrc`.

## How it fits together
- `src/chatty_voice_node.py`: the main service (systemd `chatty-voice`). Vosk
  speech recognition: a grammar-only wake listener for "hey chatty" (confidence
  0.85 or higher) plus the main recognizer. Modes: sleep (waiting), active,
  resting (put to bed; a tap wakes her), confirm. Piper speech output with lip sync.
- `src/chatty_face.py` + `src/face_model.py`: the pygame face, a separate process.
  The voice node sends it UDP messages on 127.0.0.1:47474 (`state:`, `level:`,
  `heard:`, `listen:`, `rec:`, `play`, `ponder:`, `notice:`). The face sends `wake`, `rest`
  and `notify:<text>` back on 47475. 30 fps when busy, 8 fps when idle.
- Answer tiers: `local_skills.py` (time, date, NWS weather, greenhouse) ->
  `memory.py` recall -> `local_llm.py` (Ollama qwen2.5:0.5b on the Pi, replies
  ESCALATE when unsure) -> the relay at ceucomics.com (`app/main.py`, FastAPI ->
  OpenAI gpt-4.1-mini). Planned: a Hostinger VPS tier.
- Face activities when idle: tic-tac-toe (`games.py`), pondering (`pondering.py`
  + `nodes.py`: she asks the greenhouse/rain node and shows the answer), dreams
  while asleep (`dreams.py`, extra lines in `~/.local/share/chatty/dreams.txt`).
- Face moods: `mischief` (smirk and wink; jokes, "be cheeky") and `love` (^ ^ eyes,
  blush, a kiss and floating hearts; "I love you", "blow me a kiss", "happy
  Valentine's Day"). On Feb 14 the idle face has rosy cheeks (CHATTY_FORCE_VALENTINE=1
  to test, like CHATTY_FORCE_SPOOKY for Halloween). `actually` (raised brow, finger
  up, a planet orbiting, "Well, actually..." status): only when her own reply is a
  correction (`well_actually()` in the voice node); she leads with "Well, actually...".
  `snapped` (deadpan stare, crooked cracked tiara, height-chart wall; the "Cinderella
  snapped" mood): chore orders and insults get dry local lines, and fed-up AI replies
  ("Absolutely not", "I'm done") are spoken with it. Dry, never cruel.
  `tiny` (channeling Tiny, Vincent's tuxedo cat: ears, slit pupils, side-eye,
  whiskers): "meow", "be Tiny", "how's Tiny" get local cat lines; skeptical AI
  replies ("sounds fishy", "nice try") are spoken with the side-eye.
- `alerts.py`: NWS alerts for CHATTY_LAT/LON. Urgent warnings are spoken right
  away (even while resting), AMBER alerts 7am-11pm, others in the daytime; each once.
- Other modules: `memory.py`, `voices.py` (voice ID), `conversation_log.py`,
  `earcons.py` (chimes), `tts_piper.py`, `face_link.py`.
- Data on the Pi lives in `~/.local/share/chatty/` (memory.json, voices.json,
  logs/, alerts_seen.json).

## Decisions (keep these)
- Privacy first: everything stays on the Pi except relay questions. Voice ID is
  OFF by default (CHATTY_VOICE_ID=1), voiceprints are stored owner-only, and
  "forget my voice" deletes them.
- Other nodes are READ-ONLY. Chatty never sends commands (no watering).
- A soil voltage of about 0 V means the probe is unplugged, not 100% wet.
- Spoken interruptions are rare and polite: dry soil / heat at most every 3 hours,
  daytime only.
- Recording indicator on screen (REC / PRIVATE / STATS ONLY). "Pause logging"
  works by voice.
- Wake stats are logged (full and private modes): each wake (phrase or tap, with
  confidence), near-misses below CHATTY_WAKE_MIN_CONF (confidence only, no words),
  and `name_heard` per turn (the word heard for her name: "chatty", "daddy"...).
  `scripts/conversation_report.py` sums them up under "Waking up".
- Turning her off: "Hey Chatty, shut down" asks to confirm, then runs
  `sudo -n /usr/sbin/shutdown -h now` (sudoers file mode 0440).

## Main settings (`/etc/chatty/secrets.env`)
CHATTY_TOKEN (relay), CHATTY_LOCAL_MODEL=qwen2.5:0.5b, CHATTY_WAKE_PHRASE,
CHATTY_VOICE_WAKE (0 = tap-only quiet mode), CHATTY_VOICE_ID, CHATTY_LOG_MODE
(full/private/off), CHATTY_GREENHOUSE_URL, CHATTY_RAIN_URL, CHATTY_NODES,
CHATTY_LAT / CHATTY_LON, CHATTY_ALERTS / _AMBER / _NIGHT, CHATTY_CURIOSITY,
CHATTY_PONDER_EVERY, CHATTY_GAMES, CHATTY_DREAMS, CHATTY_SOUNDS, IFTTT_KEY.
Each module's docstring lists its own settings.

## Testing without the Pi
- No pip in the cloud workspace: tests use plain Python with stand-ins for vosk,
  numpy, the speech engine and requests. A simulation feeds scripted speech to the
  voice node (an "@name " prefix fakes a voiceprint).
- `scripts/preview_face.py` renders the face to PNG with Pillow (no pygame needed).

## Open items
- The relay update in `app/main.py` (personality, history, credits message) is
  not deployed to the server yet.
- The face doesn't start at boot yet (use `start_face.sh`).
- Greenhouse Pi: Tailscale logged out (`sudo tailscale up`), then disable key
  expiry in the Tailscale admin page for every node. Weak WiFi (-80 dBm), power
  saving now off. Soil probe reads 0 V (unplugged?).
- The IFTTT key was in code (now moved to settings): make a new key.
- Still to add to "requesting your assistance": Pi too hot, disk nearly full,
  Ollama or the mic down. Move the voice node's own unprompted speech onto
  `quiet_hours.is_night()` too.
- Ideas: openWakeWord, timers, a VPS model tier, a lightning node web page,
  Chatty nodes talking to each other.

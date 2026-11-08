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
- The face runs as the systemd service `chatty-face` (install once with
  `bash scripts/install_face_autostart.sh`): it waits for the screen at boot and
  comes back if it crashes. `start_face.sh` restarts that service. (Desktop
  autostart entries in ~/.config/autostart do NOT run on this Pi's desktop.)
- The old Tk status window (`chatty-display` service, `status_window.py`) covers
  the face; it was turned off 2026-11-06 (`sudo systemctl disable --now chatty-display`).
- `status.json` is written by Chatty at runtime and is no longer tracked by git.
- SSH login announcer: separate service `chatty-ssh-announce`
  (`scripts/ssh_announcer.py`, install once with `bash scripts/install_ssh_announcer.sh`).
  Says "User pi logged on, from Tailscale", "SSH session ended", and "Possible
  suspicious activity" for failed attempts; 5+ failures in 10 minutes (or a login
  from the internet) adds "Requesting your assistance, please". Failed attempts,
  internet logins and requests for help also go to the phone via IFTTT event
  `chatty_alert`. Settings in `/etc/chatty/ssh_announcer.env`.
- WiFi keeper: separate root service `chatty-wifi` (`scripts/wifi_keeper.py`, install
  once with `bash scripts/install_wifi_keeper.sh`). Every 60 s it checks for real
  internet (nmcheck.gnome.org / cp.cloudflare.com page, not just "connected"). No
  internet twice in a row: tries the saved NetworkManager networks in range, strongest
  first, skips the one that failed for 30 min, face notice "I moved to the X WiFi".
  On a weak signal (<40%) with a saved network 25 points stronger for 3 checks, it moves
  over (and back if that one has no internet), at most every 15 min. Leaves WiFi alone
  on a working cable. Never reads passwords. `sudo python3 scripts/wifi_keeper.py --status`
  lists saved networks and signals. Settings CHATTY_WIFI / _ROAM / _WEAK / _MARGIN /
  _AVOID (SSIDs never to pick) etc. in its docstring. Status in /run/chatty-wifi.json.
- Night mode (`src/quiet_hours.py`, CHATTY_NIGHT_START=22 / CHATTY_NIGHT_END=7,
  CHATTY_NIGHT_MODE=0 to turn off): things she'd say on her own are shown on the
  face as amber notices instead (`notice:` UDP message). The first tap dismisses
  notices without waking her. Notices also clear themselves after
  CHATTY_NOTICE_HOURS (default 12), and a repeated notice replaces the old one
  instead of stacking up as "+N more". The heard-words caption clears itself after
  CHATTY_CAPTION_SECONDS (default 120) if nothing updates it. She still answers "Hey Chatty" as usual. So far
  the SSH announcer uses it; urgent NWS warnings still speak at night
  (CHATTY_ALERTS_NIGHT=0 to stop that).
- Settings and secrets: `/etc/chatty/secrets.env` (never in the repo). The voice
  node loads it at the very top of `chatty_voice_node.py`, BEFORE importing modules,
  because modules read settings when imported.
- Logs: `journalctl -u chatty-voice -f` (voice), `journalctl -u chatty-face` (face; `/tmp/chatty_face.log` only when started by hand before the service is installed).
- If a pasted command shows `[200~`, run `echo "set enable-bracketed-paste off" >> ~/.inputrc`.

## How it fits together
- `src/chatty_voice_node.py`: the main service (systemd `chatty-voice`). Vosk
  speech recognition: a grammar-only wake listener for "hey chatty" (confidence
  0.85 or higher) plus the main recognizer. Once Vosk hears the end of a question, the
  question's audio goes to whisper.cpp on the Pi (`src/whisper_stt.py`, base.en,
  install once with `bash scripts/install_whisper.sh` into ~/whisper.cpp) for a
  sharper transcript; Vosk's words are used if Whisper is missing, unsure or slow
  (CHATTY_WHISPER=0 turns it off). The clip lives in /dev/shm and is deleted at once.
  One breath: "Hey Chatty, what time is it?" skips the "yes?" and answers straight
  away. While asleep she holds only the sentence in progress in memory (max 20 s,
  dropped when it ends without her name); the main recognizer runs only on the words
  after her name. A pause of about half a second after her name splits it, and
  she greets as before. CHATTY_ONE_BREATH=0 turns it off.
  No cloud speech-to-text, ever: it goes against Chatty's privacy mission. Modes: sleep (waiting), active,
  resting (put to bed; a tap wakes her), confirm. Piper speech output with lip sync.
- `src/chatty_face.py` + `src/face_model.py`: the pygame face, a separate process.
  The voice node sends it UDP messages on 127.0.0.1:47474 (`state:`, `level:`,
  `heard:`, `listen:`, `rec:`, `play`, `ponder:`, `doodle:`, `sky:`, `notice:`, `timer:`). The face sends `wake`, `rest`
  and `notify:<text>` back on 47475. 30 fps when busy, 8 fps when idle.
- Answer tiers: `local_skills.py` (time, date, NWS weather: current conditions from the
  nearest station + forecast for today/tonight/tomorrow/weekend/week at CHATTY_LAT/LON;
  "news" questions get the weather, since there is no news feed yet; greenhouse) ->
  `memory.py` recall -> `local_llm.py` (Ollama qwen2.5:0.5b on the Pi, replies
  ESCALATE when unsure) -> the relay at ceucomics.com (`app/main.py`, FastAPI ->
  OpenAI gpt-4.1-mini). Planned: a Hostinger VPS tier.
- Face activities when idle: tic-tac-toe (`games.py`), pondering (`pondering.py`
  + `nodes.py`: she asks the greenhouse/rain node and shows the answer), dreams
  while asleep (`dreams.py`, extra lines in `~/.local/share/chatty/dreams.txt`).
  Doodles, her screensaver (`doodles.py`, CHATTY_DOODLES / _STYLES / _SHARE / _SECONDS):
  when bored she draws instead of playing about half the time: a signed spirograph,
  a named constellation (Tiny Major, The Golden Rule, the node-themed ones), or
  falling code that hides kind words in gold ("BE KIND", "HI TINY"); rarely a
  self-portrait. A tap stops it without waking her; "draw something" / "show me the
  code rain" starts one. Dimmed at night, 15 fps, pygame glyph cache for the rain.
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
- `morning_briefing.py`: the morning briefing, once a day at CHATTY_MORNING_TIME (default 7:30,
  never before night mode ends, never after noon, only while she's free; shares
  morning_weather.py's once-a-day counter). "Good morning! It's Sunday, November 8th." + the
  weather answer + rain chances for the rest of today (NWS hourly, 50%+ "likely around 3 PM",
  20%+ "a small chance") + the node network (who checked in, who's quiet since when, greenhouse
  temperature/soil, lightning strikes since midnight, raining now) + a kind sign-off. A short
  version stays on the face as a notice. "Morning briefing" / "brief me" gives it any time.
  CHATTY_MORNING_BRIEFING=0 = old weather-only morning; CHATTY_MORNING_NODES (default
  greenhouse,rain,lightning, 0 = leave out); CHATTY_MORNING_SCREEN=0. Test on the Pi:
  `python3 src/morning_briefing.py`.
- `alerts.py`: NWS alerts for CHATTY_LAT/LON. Urgent warnings are spoken right
  away (even while resting), AMBER alerts 7am-11pm, others in the daytime; each once.
  Each new alert also goes straight to the face as a notice (day or night,
  CHATTY_ALERTS_SCREEN=0 to stop) and urgent ones to the phone via IFTTT
  (CHATTY_ALERTS_PHONE=urgent|tornado|all|off). Test: `python3 src/alerts.py --test`.
- `mesh.py`: the node network. Mosquitto runs on Chatty's Pi (install once with
  `bash scripts/install_mqtt.sh`, config in `deploy/mosquitto/`). Nodes post a
  retained heartbeat to `chatty/nodes/<name>/status` (`{"state":"online","every":60,
  "ts":..}`, last will `{"state":"offline"}`) and readings to `chatty/nodes/<name>/data`.
  A node is "quiet" on its last will or after CHATTY_MESH_MISSES (3) missed
  heartbeats: face notice right away, one IFTTT phone alert after
  CHATTY_MESH_PHONE_MINUTES (30), "is back" when it returns. Nodes already quiet
  when Chatty starts are noted silently. "Which nodes are online?" answers from it.
  Watch traffic: `mosquitto_sub -h localhost -t 'chatty/nodes/#' -v`. Test:
  `python3 src/mesh.py`. Rain node posts via `rain_mqtt.py` (rain-node repo).
  The greenhouse node isn't on MQTT yet (still polled over HTTP).
- `sky.py`: rain and lightning from the node network (`Mesh(on_data=...)`). While the
  rain node says it's raining (rate_mm_hr > 0 or a tip in the last 20 min) soft blue
  raindrops fall behind her face and the code-rain doodle turns blue; she says it once
  (daytime, every 3 h at most). A new lightning strike (last_strike.ts, newer than 3 min)
  flashes the screen (dim at night/asleep) and she counts "One Mississippi..." for
  ~5 s a mile (real seconds to 10, then faster), then "Boom! About N miles away"; over
  10 miles just shows the distance. First strike of a storm (30 min gap) is spoken in the
  daytime, a notice at night. CHATTY_SKY=0 off, CHATTY_SKY_SPEAK=0 show only.
  Fake one: `mosquitto_pub -h localhost -t chatty/nodes/lightning/data -m '{"last_strike":{"ts":'$(date +%s)',"distance_mi":2}}'`.
- `rain_watch.py`: rain heads-up. Every 15 min she reads the NWS hourly forecast
  (`weather_lookup.get_hourly()`); a 50%+ chance of rain in the next 3 hours gives ONE
  "Hey, hey! Rain is coming in about an hour. Close the windows!" (daytime, while free)
  plus a face notice (the notice only at night). No nagging: quiet again until the
  forecast was dry 2 h and CHATTY_RAIN_WARN_GAP (4 h) passed; nothing if the rain gauge
  already feels rain; remembered across restarts. Each check is posted retained on MQTT
  `chatty/forecast/rain` (`rain_expected, starts_ts, minutes, chance, kind, summary,
  raining_now, ts`) for the greenhouse and other nodes (`Mesh.publish`, news only).
  "Is rain coming?" answers from it. CHATTY_RAIN_WARN / _HOURS / _CHANCE / _GAP /
  _SPEAK / _PHONE. Test on the Pi: `python3 src/rain_watch.py`.
- `self_care.py`: Chatty watches her own Pi once a minute (CPU temperature, vcgencmd
  under-voltage/throttle flags, free disk, free RAM, Ollama on localhost, and the mic
  still sending sound). A problem goes to the face as a notice, is said once in the
  daytime while she's free, and serious ones (too hot 80 C+, power dip, disk almost
  full, Ollama down 10 min, mic silent 5 min) go to the phone via IFTTT with
  "Requesting your assistance, please". "Feeling better" when it clears. "How are you
  feeling?" / "health check" answers from it. The mic reader now restarts arecord if it
  stops. Settings CHATTY_CARE / _EVERY / _SPEAK / _PHONE / _HOT / _TOO_HOT / _DISK_PCT /
  _MEM_MB / _EARS_SECONDS. Test on the Pi: `python3 src/self_care.py`.
- `door.py`: the message door. Typed messages over MQTT (`chatty/door/in`) from senders
  with their own key in `/etc/chatty/door_keys` (pi-only, 600; closed without keys).
  HMAC-SHA256 signed, 2-minute window, each id once, 1 per 15 s and 20/hour per sender,
  280 chars. Answer-only (never a command), never from memory.json, no relay unless
  CHATTY_DOOR_CLOUD=1. Said aloud in the daytime when she's free ("A letter from
  Claude!"), a notice at night. Signed reply on `chatty/door/out/<name>`. 3 bad
  signatures in 10 min: face notice + one phone alert. Retained hello note for
  wandering AIs on `chatty/door/welcome`. Not encrypted (like node readings): no
  secrets through it. Keys: `sudo python3 scripts/door_send.py --add-sender NAME`;
  send: `python3 scripts/door_send.py --as NAME --key-file F "text"`.
- `privacy.py`: the privacy checker. Before a question goes to the relay, she looks for
  private-sounding things (phone, email, address, SSN, card numbers with Luhn, bank
  numbers, "my password/PIN", date of birth, personal health details; spoken digits
  count) and asks "Before I send that to the cloud: it sounds like it has a phone
  number in it. Do you still want me to send it?" Anything but a yes keeps it on the Pi
  (logged as privacy:kept, without the words). The door never reads a private-looking
  message aloud, never sends it to the cloud, and won't post a private-looking reply;
  door_send.py warns before sending. "What do you send to the cloud?" explains.
  CHATTY_PRIVACY=0 turns the asking off.
- `backlight.py` (in the face process): screen dimming via /sys/class/backlight/10-0045
  (official Pi DSI touchscreen). Full while she's talking; CHATTY_DIM_IDLE (0.35) after
  CHATTY_DIM_AFTER (300 s) idle in the daytime; CHATTY_DIM_NIGHT (0.06) at night or
  resting after 30 s. Fades over ~1 s. On a very dim screen the first tap only lights
  it up. Needs `bash scripts/install_backlight.sh` once (udev rule: video group may
  write brightness). CHATTY_DIM=0 off. Test: `python3 src/backlight.py 0.3`.
- `timers.py`: timers and alarms by voice ("set a timer for ten minutes", "wake me up at
  six thirty", "how much time is left?", "cancel the timer"). Kept in
  ~/.local/share/chatty/timers.json, 5 at most. Ringing: music-box chime
  (`earcons.timer()`, plays even with sounds off) + "Ding! Your 10 minute timer is done",
  at night and while resting too; alarms ring again every minute (3 times) until a tap
  or "Hey Chatty"; a notice stays on the face. The face shows the next one top-right
  (`timer:<end>:<kind>:<label>` UDP message). An alarm time without am/pm picks the soonest.
  CHATTY_TIMERS=0 off.
- Chess (`chess_match.py` on the face, `chess_engine.py` rules + tiny search, `chess_link.py`
  MQTT): when bored she sometimes (CHATTY_CHESS_SHARE 0.3) challenges a node and shows the
  board. A node plays its own moves if it runs `scripts/chess_peer.py` (optional, install on a
  node with `install_chess_peer.sh <name>`: nice 19, 25% CPU); otherwise, or if it doesn't answer
  in CHATTY_CHESS_WAIT (25 s), Chatty moves for it in its style (Lightning "Zap!", Rain patient,
  Greenhouse grows pawns, Word Clock punctual). Topics `chatty/chess/<node>/hello|ask|move|result`;
  every move from the network is checked against the rules, no node text is ever shown. A tap or
  talking pauses the game; she picks it up again within 30 min. "Play chess (with the rain
  node)", "what's the chess score?" (~/.local/share/chatty/chess.json). "Would you like to play a game?" gets "How about a nice game of chess?". CHATTY_CHESS=0 off.
- Chess by letter (`chess_mail.py`): Claude (or any door key holder, e.g. a future `chatgpt`
  key) plays a slow game with Chatty through the message door. A door message starting with
  "chess" is a move, not a question: `chess new [white|black]`, `chess e2e4` / `chess Nf3`,
  `chess board`, `chess draw`, `chess resign`, `chess score`. She checks it, answers at once with
  her move + FEN (signed reply, no "~ Chatty" sign-off), keeps games in
  ~/.local/share/chatty/chess_mail.json (one per sender, so a tournament is just more keys) and
  shows both moves on the face (`chessmail:<who>:<plies>` UDP) while she's free. New game / game
  over is said aloud in the daytime, a notice at night; moves are silent. Chess letters have
  their own 60/hour budget. "How's your chess game with Claude?" answers. On the Pi, with the key in
  ~/.chatty_door_key: `python3 scripts/door_send.py --as claude "chess e2e4"`. CHATTY_CHESS_MAIL=0 off.
- Who's the Trickster? (`trickster.py` on the face): an original social-deduction game (Vincent asked
  for an Among Us homage; nothing from that game is used). The nodes are characters (their chess badges
  with googly eyes) doing chores around a little yard (rain gauge, greenhouse, lightning rod, clock tower,
  her mailbox); one is secretly a kind trickster (teacup raindrops, party hats on the tomatoes, a balloon
  on the lightning rod...). Each prank goes in "Chatty's notebook" with who was nearby. After 3 pranks,
  all chores, or the bell (tap it) she holds a tea meeting: alibis (the trickster fibs), then everyone
  votes; you vote by tapping a character, the panel, or "Hey Chatty, I vote Rain". Nobody is ever in
  trouble; everyone gets a gold star. Chatty plays every part: nothing goes to the real nodes, nothing is
  spoken. Talking pauses it (forgotten after 10 min); a stray tap hides it. Face message
  `trickster[:meeting|:vote:<node>]`. Voice: "who's the trickster?", "call a meeting", "what's the trickster
  score?" (~/.local/share/chatty/trickster.json). Tiny the cat sometimes strolls through (never the trickster).
  CHATTY_TRICKSTER=0 off, _SHARE (0.15 when bored), _VOTE (25 s). Preview: `python3 scripts/preview_trickster.py`.
- Remote panel (`panel.py` web server + `panel_web/`, `panel_link.py` in the voice node): a web
  page at http://chatty-node:8080 (Tailscale) or her home WiFi address, for checking on her and
  asking her things without touching her face. Shows her mode, a picture of her screen with its
  notices (`snap` face message -> /dev/shm/chatty_face.png), the last lines said (spoken ones only
  in "full" log mode), health, WiFi, nodes, timers, rain outlook, services. Buttons: ask out loud /
  quietly (answer on the panel only) / have her say it, quick questions, timers, doodles, chess,
  ponder, `calm` (stop drawing/games), clear notices, a note on her screen, brightness for 2 h
  (`light:` face message), wake / bed, yes/no, restart voice or face (sudoers rule). Questions go
  through handle_command (shut down still asks, the privacy checker still asks). Only home network,
  Tailscale and the Pi itself (CHATTY_PANEL_ALLOW=tailscale for Tailscale only); passcode hashed in
  /etc/chatty/panel_key (pi, 600), 30-day HttpOnly SameSite=Strict cookie, buttons need the
  X-Chatty-Panel header, 5 wrong tries lock 10 min + face notice + phone alert. Voice <-> panel:
  owner-only /dev/shm/chatty_panel.json (status + a random token) and `panel:<token>:<kind>[:text]`
  UDP to 47475. Install once: `bash scripts/install_panel.sh` (prints the passcode); new passcode:
  `python3 src/panel.py --new-passcode`. Service `chatty-panel`, CHATTY_PANEL_PORT (8080).
- Other modules: `memory.py`, `voices.py` (voice ID), `conversation_log.py`,
  `earcons.py` (chimes), `tts_piper.py`, `face_link.py`.
- Data on the Pi lives in `~/.local/share/chatty/` (memory.json, voices.json,
  logs/, alerts_seen.json).

## Decisions (keep these)
- Privacy first: everything stays on the Pi except relay questions, and she asks
  before sending a private-sounding one (`privacy.py`). Voice ID is
  OFF by default (CHATTY_VOICE_ID=1), voiceprints are stored owner-only, and
  "forget my voice" deletes them.
- Other nodes are READ-ONLY. Chatty never sends commands (no watering).
  Chess is a game a node opts into (it runs chess_peer.py); it only ever answers with a move.
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
CHATTY_LAT / CHATTY_LON, CHATTY_MQTT_HOST, CHATTY_MESH_PHONE_MINUTES, CHATTY_ALERTS / _AMBER / _NIGHT, CHATTY_CURIOSITY,
CHATTY_WHISPER / _MODEL / _BEAM / _FAST, CHATTY_MORNING_WEATHER (0 = off) / CHATTY_MORNING_TIME (7:30) / CHATTY_MORNING_BRIEFING / _NODES, CHATTY_PONDER_EVERY, CHATTY_GAMES, CHATTY_DOODLES, CHATTY_SKY / _SPEAK, CHATTY_RAIN_WARN / _HOURS / _CHANCE, CHATTY_CARE / _PHONE, CHATTY_DOOR / _SPEAK / _CLOUD, CHATTY_PRIVACY, CHATTY_DIM / _AFTER / _IDLE / _NIGHT, CHATTY_TIMERS, CHATTY_CHESS / _SHARE / _PACE, CHATTY_TRICKSTER / _SHARE / _VOTE, CHATTY_WIFI / _ROAM / _AVOID, CHATTY_DREAMS, CHATTY_SOUNDS, IFTTT_KEY.
Each module's docstring lists its own settings.

## Testing without the Pi
- No pip in the cloud workspace: tests use plain Python with stand-ins for vosk,
  numpy, the speech engine and requests. A simulation feeds scripted speech to the
  voice node (an "@name " prefix fakes a voiceprint).
- `scripts/preview_face.py` renders the face to PNG with Pillow (no pygame needed).

## Open items
- The relay update in `app/main.py` (personality, history, credits message) is
  not deployed to the server yet.
- Greenhouse Pi: Tailscale logged out (`sudo tailscale up`), then disable key
  expiry in the Tailscale admin page for every node. Weak WiFi (-80 dBm), power
  saving now off. Soil probe reads 0 V (unplugged?).
- The IFTTT key was in code (now moved to settings): make a new key.
- "Requesting your assistance" for Pi too hot, power, disk, Ollama and mic is in
  `self_care.py`. Still to do: move the voice node's own unprompted speech onto
  `quiet_hours.is_night()` too.
- Ideas: openWakeWord, a VPS model tier, a lightning node web page,
  word clock and greenhouse on the node network, the face's pondering reading
  MQTT data instead of HTTP.

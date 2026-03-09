# Chatty Node Dev Log

## 2026-03-08

### Completed
- Set up Raspberry Pi 4 Chatty node prototype
- Confirmed PowerConf USB mic/speaker works on Pi
- Built working voice pipeline:
  - record audio
  - transcribe with OpenAI
  - generate ChatGPT reply
  - speak reply with `espeak-ng`
- Added wake phrase handling
- Improved wake phrase reliability with:
  - `Hey Chatty`
  - `Okay Chatty`
- Built animated face UI on Pi screen
- Added face states:
  - idle
  - listening
  - thinking
  - speaking
  - puzzled
  - sleepy
- Replaced file polling with named pipe for faster face updates
- Refactored Chatty into modular Python files:
  - `config.py`
  - `state.py`
  - `audio.py`
  - `ai.py`
  - `main.py`
- Connected local repo to GitHub via SSH
- Pushed current working state to private GitHub repo

### Current Status
- Chatty works as a local voice assistant on Raspberry Pi
- Face updates correctly with state changes
- Wake phrase filtering works better with multi-word phrases
- OpenWakeWord installed but not fully integrated yet
- VPS exists and is secured, but not yet used in live Chatty request flow

### Known Issues
- Wake phrase detection based on transcription can still mishear short phrases
- TV / background speech can still be transcribed before filtering
- `espeak-ng` voice is functional but robotic
- Face is working well enough for now, but could later support richer animation

### Next Priorities
1. Finish OpenWakeWord integration
2. Move AI orchestration path toward VPS / OpenClaw layer
3. Add IR presence sensor support
4. Plan physical moving eyeballs module
5. Upgrade TTS later after architecture stabilizes

### Notes
- Best wake phrase so far: `Okay Chatty`
- PowerConf mic is sensitive and high quality
- Modular architecture is now in place, which should help avoid spaghetti code

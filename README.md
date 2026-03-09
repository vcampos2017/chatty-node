# Chatty Node

A Raspberry Pi–based experimental voice assistant with a simple animated face interface.

Chatty is designed as a local AI node that listens for a wake phrase, processes speech, generates a response, and speaks back while displaying visual states on a screen.

This project explores local AI assistants, modular edge computing, and physical interfaces.

---

# Current Features

- Wake phrase activation
- Speech recording from USB microphone
- Speech transcription
- AI-generated responses
- Spoken replies through speaker
- Animated face display with multiple states

Face states include:

- idle
- listening
- thinking
- speaking
- puzzled
- sleepy

---

# Hardware

Current prototype hardware:

- Raspberry Pi
- USB microphone/speaker (PowerConf)
- HDMI display for animated face

Planned hardware:

- IR presence sensor
- Camera module
- Moving eyeballs / expressive face

---

# Software Architecture

Project structure:

chatty_project/

main.py  
config.py  
state.py  
audio.py  
ai.py  

chatty_face.py  
chatty_voice_loop.py  

DEVLOG.md  
README.md  

---

# Example Interaction

User says:

Okay Chatty, what time is it?

Chatty will:

1. Record audio
2. Transcribe speech
3. Generate a response
4. Speak the reply
5. Update the animated face state

---

# Wake Phrase

Recommended wake phrase:

Okay Chatty

Longer wake phrases are more reliable than single words.

Future versions may integrate OpenWakeWord.

---

# Project Status

Working prototype.

Current capabilities:

- voice input
- AI responses
- speech output
- animated face interface
- GitHub version control

Architecture is still evolving.

---

# Future Plans

- OpenWakeWord integration
- more natural voice synthesis
- IR presence sensor
- camera awareness
- physical moving eyeballs
- optional VPS orchestration layer

---

# Development Log

See DEVLOG.md for project history.

---

# License

Experimental personal project.

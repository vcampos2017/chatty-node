# Chatty Node

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi-red)
![Status](https://img.shields.io/badge/status-experimental-orange)

A privacy-first environmental AI assistant designed for Raspberry Pi and distributed sensor networks.

**Chatty — Harmonized Tech for You**

Chatty Node listens for a wake phrase, processes speech, interprets environmental sensor data, and responds with natural voice feedback.

 # Chatty Node

**Chatty — Harmonized Tech for You**

Unlike traditional assistants, Chatty prioritizes:

- environmental awareness

- local intelligence

- distributed sensor networks

- privacy-first design

 

Chatty is designed to process information locally whenever possible, sharing only minimal data when necessary.

 

Why Chatty Exists

 

Most modern AI assistants are designed to collect data and send it to centralized systems.

 

Chatty explores a different model.

 

Chatty is built around the idea that:

- technology should harmonize with people

- intelligence can exist locally and cooperatively

- sensor networks can help humans understand their environment

- privacy should be the default state

 

Chatty is designed to be a helpful environmental companion, not a surveillance device.

## System Architecture

Environmental Sensors
│
├── Garden Node
├── Weather Node
├── Lightning Node
│
▼
Chatty Node (Raspberry Pi)
│
├── Wake Word Detection
├── Speech Recognition (Vosk)
├── Response Engine
├── Environmental Context Engine
│
▼
Voice Output (Piper TTS)
│
▼
Human Conversation
 
Chatty collects environmental signals, interprets them locally, and communicates useful information to humans through natural conversation.

Chatty harmonizes information from these nodes and presents it in human-friendly language.

 

Design Principles

 

1. Respect privacy by default

2. Process data locally whenever possible

3. Share only necessary information

4. Assist humans during emergencies

5. Return to privacy mode automatically

6. Interact with other intelligences respectfully and cooperatively

 

Current Features

 

- Wake phrase activation

- Speech recording from USB microphone

- Vosk speech transcription

- AI-generated responses

- Piper text-to-speech voice output

- Spoken replies through speakers

- Animated face display

- Multiple emotional states

 

Face states include:

- idle

- listening

- thinking

- speaking

- puzzled

- sleepy

 

Hardware

 

Current prototype hardware:

- Raspberry Pi Zero 2W / Raspberry Pi 4

- USB microphone / speaker (PowerConf)

- HDMI display for animated face

 

Planned hardware:

- IR presence sensor

- camera module

- moving eyes / expressive face

- environmental sensor nodes

- lightning detection node

 

Software Architecture

 

Project structure:

 

chatty-node/

app/ – FastAPI relay service (optional AI relay)

src/ – Core Chatty node logic, speech processing, response generation

scripts/ – deployment utilities

docs/ – project documentation

 

Installation

 

git clone https://github.com/vcampos2017/chatty-node.git

cd chatty-node

 

python3 -m venv venv

source venv/bin/activate

 

pip install -r requirements.txt

 

Configuration

 

cp .env.example .env

 

Example configuration variables:

 

OPENAI_API_KEY=your_api_key_here

CHATTY_TOKEN=generate_a_secure_token

CHATTY_PIPER_BIN=/usr/local/bin/piper

CHATTY_PIPER_MODEL=/path/to/voice.onnx

CHATTY_VOSK_MODEL=/path/to/vosk-model

 

Example Interaction

 

User: “Okay Chatty, what time is it?”

 

Chatty will:

1. Record audio

2. Transcribe speech

3. Generate a response

4. Speak the reply

5. Update the animated face state

 

Wake Phrase

 

Recommended wake phrase:

Okay Chatty

 

Future versions may integrate OpenWakeWord.

 

Project Status

 

Working prototype with voice input, AI responses, speech output, animated face interface, and distributed sensor node integration.

 

Roadmap

 

- OpenWakeWord integration

- improved natural voice synthesis

- IR presence detection

- camera awareness

- expressive physical face hardware

- optional VPS orchestration layer

- distributed environmental sensor network

 

Development Log

 

See DEVLOG.md for project history and milestones.

 

License

 

MIT License



## Philosophy

Chatty explores a cooperative model of AI.

Instead of centralized assistants that collect large amounts of data,
Chatty nodes are designed to:

• run locally  
• protect privacy  
• share knowledge selectively  
• help humans understand their environment  

Chatty is not designed to observe people.

It is designed to **assist them.**

Copyright (c) 2026 Vincent Campos
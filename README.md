# Chatty Node

Raspberry Pi thin-client node for Chatty AI.

This project turns a Raspberry Pi (Pi 4 → Pi 5) into a kiosk-style
AI interface that connects to a VPS backend and the OpenAI API.

## Architecture

Pi (UI + audio + sensors)
→ VPS (orchestration + API relay)
→ OpenAI API (reasoning)

The Pi is designed to be hardware-replaceable.
All logic lives in version-controlled configuration.

## Features (Phase 1)

- Chromium kiosk UI
- Audio input/output
- Basic API interaction
- Systemd-managed service
- Hardware migration ready

## Hardware Targets

- Raspberry Pi 4 (current)
- Raspberry Pi 5 + AI HAT (future)

## Quick Start (Fresh Device)

```bash
git clone https://github.com/USERNAME/chatty-node.git
cd chatty-node
bash scripts/bootstrap.sh

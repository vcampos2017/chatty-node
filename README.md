Chatty Node

Raspberry Pi thin-client node for Chatty AI.

This project turns a Raspberry Pi (Pi 4 → Pi 5) into a kiosk-style AI interface that connects to a VPS backend and the OpenAI API.

⸻

Architecture

Pi (UI + audio + sensors)
→ VPS (orchestration + API relay)
→ OpenAI API (reasoning)

The Pi is designed to be hardware-replaceable.
The VPS and API layer contain all persistent logic.

⸻

Features (Phase 1)
	•	Chromium kiosk UI
	•	Audio input/output
	•	Basic API interaction
	•	Systemd-managed service
	•	Hardware migration ready

⸻

Hardware Targets
	•	Raspberry Pi 4 (current)
	•	Raspberry Pi 5 + AI HAT (future)

⸻

Quick Start (Fresh Device)

git clone https://github.com/vcampos2017/chatty-node.git
cd chatty-node
bash scripts/bootstrap.sh

Security Model

Secrets are never committed.

Create a local file on the device:

/etc/chatty/secrets.env

Example:

      OPENAI_API_KEY=your_key_here 

This file is intentionally excluded from version control.

⸻

Migration Philosophy

Hardware upgrades should require:
	1.	Flash OS
	2.	Clone repo
	3.	Run bootstrap
	4.	Add secrets file
	5.	Reboot

No manual reconstruction.

⸻

Project Structure

chatty-node/
│
├── src/
├── scripts/
├── systemd/
├── config/
├── requirements.txt
└── README.md

requirements.txt

openai
requests
python-dotenv

Minimal src/main.py

import os
import requests
from dotenv import load_dotenv

load_dotenv("/etc/chatty/secrets.env")

def main():
    print("Chatty Node initialized.")
    # Placeholder for future API connection logic

if __name__ == "__main__":
    main()

Version

Chatty Node v1 – Foundation Build

End

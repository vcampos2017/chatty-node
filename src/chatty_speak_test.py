from response_engine import ResponseEngine
import os
import subprocess
import shutil


PIPER_BIN = os.getenv("CHATTY_PIPER_BIN", shutil.which("piper") or "/home/pi/piper/piper/piper")
PIPER_MODEL = os.getenv("CHATTY_PIPER_MODEL", "/home/pi/piper/en_US-amy-low.onnx")


def speak_with_piper(text: str):
    """
    Speak text using Piper and aplay.
    """
    cmd = f'echo "{text}" | {PIPER_BIN} --model {PIPER_MODEL} --output-raw | aplay -D plughw:1,0 -r 16000 -f S16_LE -t raw -c 1'
    subprocess.run(cmd, shell=True, check=True)


def main():
    engine = ResponseEngine()

    context = {
        "current_language": "en",
        "sensor_snapshot": {
            "soil_moisture": 0.22,
            "humidity": 78,
        },
        "recent_events": [
            {"event": "soil_moisture_low"},
            {"event": "rain_expected"},
        ],
        "pending_alerts": [],
    }

    text = engine.generate_summary(context)

    print("Chatty says:", text)

    speak_with_piper(text)


if __name__ == "__main__":
    main()

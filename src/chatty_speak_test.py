from response_engine import ResponseEngine
import subprocess
import shutil


PIPER_BIN = "/home/pi/piper/piper/piper"


def speak_with_piper(text: str):
    """
    Speak text using Piper and aplay.
    """
    cmd = f'echo "{text}" | {PIPER_BIN} --model /home/pi/piper/en_US-amy-low.onnx --output-raw | aplay -r 22050 -f S16_LE -t raw -c 1'
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

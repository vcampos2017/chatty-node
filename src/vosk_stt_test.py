import json
import queue
import sounddevice as sd
from vosk import Model, KaldiRecognizer

MODEL_PATH = "/home/pi/vosk-model/vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000

q = queue.Queue()

def callback(indata, frames, time, status):
    if status:
        print(status)
    q.put(bytes(indata))

print("Loading model...")
model = Model(MODEL_PATH)
rec = KaldiRecognizer(model, SAMPLE_RATE)

print("\nSpeak into the mic. Press Ctrl+C to stop.\n")

with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=8000, dtype="int16",
                       channels=1, callback=callback):
    while True:
        data = q.get()
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            text = result.get("text", "").strip()
            if text:
                print("You said:", text)
        else:
            # Optional: show partials (comment out if noisy)
            partial = json.loads(rec.PartialResult()).get("partial", "").strip()
            if partial:
                print("...", partial)

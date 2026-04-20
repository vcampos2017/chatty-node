import requests
import time

def send_command(action):
    try:
        response = requests.post(
            "http://192.168.1.227:5000/command",
            json={"action": action},
            timeout=5
        )
        print("Command response:", response.json())
    except Exception as e:
        print("Command failed:", e)

url = "http://192.168.1.227:5000/status"

while True:
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        soil_band = data["metrics"]["soil_moisture_band"]
        soil_percent = data["metrics"]["soil_moisture_percent"]
        temp = data["metrics"]["air_temperature_f"]

        print("-" * 40)
        print(f"Soil: {soil_band} ({soil_percent}%)")
        print(f"Temp: {temp} F")
        print()

        if soil_percent < 35:
            print("Chatty: Soil critically dry — activating watering.")
            send_command("water_on")
        elif soil_percent < 50:
            print("Chatty: Soil is moderate — monitor closely.")
        else:
            print("Chatty: Soil moisture is healthy.")
            send_command("water_off")

        if temp > 85:
            print("Chatty: Temperature is high — monitor plant stress.")

    except Exception as e:
        print("Chatty: Error reading greenhouse:", e)

    time.sleep(10)
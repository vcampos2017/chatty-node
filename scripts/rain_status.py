import requests

RAIN_URL = "http://rain-node:5000/status"

def get_rain_summary():
    try:
        response = requests.get(RAIN_URL, timeout=5)
        response.raise_for_status()
        data = response.json()

        rain_mm = data.get("rain_mm", 0)
        rain_in = data.get("rain_in", 0)
        rate = data.get("rate_mm_hr", 0)
        tips = data.get("tip_count", 0)

        return (
            f"Rainfall: {rain_mm:.2f} mm ({rain_in:.3f} in), "
            f"{tips} tips, rate {rate:.2f} mm/hr."
        )

    except Exception as e:
        return f"Rain-node error: {e}"


if __name__ == "__main__":
    print(get_rain_summary())

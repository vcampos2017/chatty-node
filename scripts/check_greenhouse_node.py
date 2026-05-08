#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

GREENHOUSE_BASE_URL = "http://192.168.1.227:5000"


def fetch_json(path: str, timeout: float = 5.0) -> dict:
    url = f"{GREENHOUSE_BASE_URL}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    try:
        health = fetch_json("/health")
        status = fetch_json("/status")
    except urllib.error.URLError as exc:
        print(f"Greenhouse Node unreachable: {exc}")
        return 2
    except json.JSONDecodeError as exc:
        print(f"Greenhouse Node returned invalid JSON: {exc}")
        return 2

    if not health.get("ok"):
        print("Greenhouse Node health check failed.")
        print(json.dumps(health, indent=2, sort_keys=True))
        return 1

    metrics = status.get("metrics", {})
    node = status.get("node", "unknown-node")

    print(f"{node} is online.")
    print(f"Air: {metrics.get('air_temperature_f')} F, {metrics.get('air_humidity')}% humidity")
    print(f"Soil: {metrics.get('soil_moisture_percent')}% moisture, {metrics.get('soil_moisture_band')}")
    print(f"Soil temp: {metrics.get('soil_temperature_f')} F")
    print(f"Pressure: {metrics.get('air_pressure_hpa')} hPa")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

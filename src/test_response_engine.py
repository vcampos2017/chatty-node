from response_engine import ResponseEngine


def main():
    engine = ResponseEngine()

    context_en = {
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

    context_pt = {
        "current_language": "pt",
        "sensor_snapshot": {
            "soil_moisture": 0.22,
        },
        "recent_events": [
            {"event": "lightning_detected"},
        ],
        "pending_alerts": [
            {"event": "lightning_detected", "priority": "high"},
        ],
    }

    context_default = {
        "current_language": "fr",
        "sensor_snapshot": {},
        "recent_events": [],
        "pending_alerts": [],
    }

    print("English summary:")
    print(engine.generate_summary(context_en))
    print()

    print("Portuguese summary:")
    print(engine.generate_summary(context_pt))
    print()

    print("Default French summary:")
    print(engine.generate_summary(context_default))
    print()

    print("Portuguese alert report:")
    for message in engine.generate_alert_report(context_pt):
        print(message)


if __name__ == "__main__":
    main()

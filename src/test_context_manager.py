from event_bus import EventBus
from context_manager import ContextManager


def main():
    bus = EventBus()
    context = ContextManager(bus)

    print("Initial summary:")
    print(context.summarize())
    print()

    bus.publish("state_changed", {"from": "idle", "to": "speaking", "event": "response_ready"})
    bus.publish("language_activated", {"code": "pt"})
    bus.publish("sensor_update", {"sensor": "soil_moisture", "value": 0.22})
    bus.publish("sensor_update", {"sensor": "humidity", "value": 78})

    context.publish_context_event(
        "soil_moisture_low",
        {"zone": "garden_bed_1", "value": 0.22}
    )
    context.publish_context_event(
        "rain_expected",
        {"hours": 4}
    )
    context.publish_context_event(
        "lightning_detected",
        {"distance_km": 11}
    )

    print("Updated summary:")
    print(context.summarize())
    print()

    print("Latest soil moisture sensor:")
    print(context.get_latest_sensor("soil_moisture"))
    print()

    print("Pending alerts:")
    for alert in context.get_pending_alerts():
        print(alert)
    print()

    print("Recent events (last 5):")
    for event in context.get_recent_events(limit=5):
        print(event)


if __name__ == "__main__":
    main()

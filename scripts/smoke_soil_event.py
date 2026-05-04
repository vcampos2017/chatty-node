from src.db import init_db, log_sensor, log_action, get_last_status
from src.event_bus import EventBus


def handle_soil_status_changed(payload):
    node = payload.get("node", "greenhouse-node")
    soil = payload.get("soil_moisture")
    temp = payload.get("temperature")
    status = payload.get("status", "unknown")

    print(f"[EVENT] Soil status changed on {node}: {status}")

    log_sensor(
        node=node,
        soil=soil,
        temp=temp,
        status=status,
    )

    log_action(
        node=node,
        action="soil.status.event",
        result="logged",
        notes=f"Event bus logged soil status '{status}'",
    )


def main():
    init_db()

    bus = EventBus()
    bus.subscribe("soil.status.changed", handle_soil_status_changed)

    errors = bus.publish(
        "soil.status.changed",
        {
            "node": "greenhouse-node",
            "soil_moisture": 44.5,
            "temperature": 73.4,
            "status": "moderate",
        },
    )

    if errors:
        print(f"[ERROR] {len(errors)} handler error(s): {errors}")
        raise SystemExit(1)

    last_status = get_last_status(offset=0)
    print(f"[DB] Last logged status: {last_status}")


if __name__ == "__main__":
    main()

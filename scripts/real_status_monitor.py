from src.db import init_db, log_sensor, log_action, get_last_status
from src.event_bus import EventBus


CURRENT_STATUS = "dry"


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
        action="soil.status.changed",
        result="event_emitted",
        notes=f"Transition detected to '{status}'",
    )


def main():
    init_db()

    previous_status = get_last_status(offset=0)

    print(f"[STATE] Previous: {previous_status}")
    print(f"[STATE] Current: {CURRENT_STATUS}")

    bus = EventBus()
    bus.subscribe("soil.status.changed", handle_soil_status_changed)

    if previous_status != CURRENT_STATUS:
        errors = bus.publish(
            "soil.status.changed",
            {
                "node": "greenhouse-node",
                "soil_moisture": 32.1,
                "temperature": 74.2,
                "status": CURRENT_STATUS,
            },
        )

        if errors:
            print(f"[ERROR] {len(errors)} handler error(s): {errors}")
            raise SystemExit(1)

    else:
        print("[STATE] No status change detected")


if __name__ == "__main__":
    main()

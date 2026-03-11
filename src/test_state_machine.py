from event_bus import EventBus
from state_machine import ChattyStateMachine


def main():
    bus = EventBus()
    machine = ChattyStateMachine(bus)

    def on_state_changed(payload):
        print(
            f"[state_changed] {payload.get('from')} -> {payload.get('to')} "
            f"via {payload.get('event')}"
        )

    bus.subscribe("state_changed", on_state_changed)

    print("Initial state:", machine.get_state())

    bus.publish("wake_word_detected")
    print("Current state:", machine.get_state())

    bus.publish("speech_detected", {"text": "What is the garden status?"})
    print("Current state:", machine.get_state())

    bus.publish("response_ready", {"message": "Soil moisture is slightly low."})
    print("Current state:", machine.get_state())

    bus.publish("speech_output_finished")
    print("Current state:", machine.get_state())

    changed = machine.handle_event("response_ready")
    print("Invalid transition from idle with response_ready:", changed)
    print("Current state:", machine.get_state())

    bus.publish("sleep_requested")
    print("Current state:", machine.get_state())

    bus.publish("wake_requested")
    print("Current state:", machine.get_state())

    bus.publish("alert_triggered", {"level": "warning", "source": "lightning_node"})
    print("Current state:", machine.get_state())

    bus.publish("reset_requested")
    print("Current state:", machine.get_state())

    bus.publish("error_detected", {"source": "sensor_module"})
    print("Current state:", machine.get_state())

    bus.publish("reset_requested")
    print("Current state:", machine.get_state())


if __name__ == "__main__":
    main()

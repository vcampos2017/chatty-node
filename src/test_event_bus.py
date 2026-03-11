from event_bus import EventBus


def main():
    bus = EventBus()

    def on_speech_detected(payload):
        text = payload.get("text", "")
        print(f"[speech_detected] text={text}")

    def on_language_detected(payload):
        code = payload.get("code", "unknown")
        confidence = payload.get("confidence", 0.0)
        print(f"[language_detected] code={code} confidence={confidence}")

    def on_response_ready(payload):
        message = payload.get("message", "")
        print(f"[response_ready] message={message}")

    def on_faulty_handler(payload):
        raise RuntimeError("Intentional test error from faulty handler")

    bus.subscribe("speech_detected", on_speech_detected)
    bus.subscribe("language_detected", on_language_detected)
    bus.subscribe("response_ready", on_response_ready)
    bus.subscribe("response_ready", on_faulty_handler)

    print("Registered events:", bus.list_events())
    print("response_ready subscribers:", bus.get_subscriber_count("response_ready"))

    bus.publish("speech_detected", {"text": "Você pode falar comigo em português?"})
    bus.publish("language_detected", {"code": "pt", "confidence": 0.93})

    errors = bus.publish(
        "response_ready",
        {"message": "Posso falar em português. Quer que eu fale em português?"},
    )

    if errors:
        print(f"[event_bus] captured {len(errors)} handler error(s):")
        for error in errors:
            print(f" - {error}")

    removed = bus.unsubscribe("response_ready", on_faulty_handler)
    print("faulty handler removed:", removed)
    print("response_ready subscribers:", bus.get_subscriber_count("response_ready"))

    bus.publish("response_ready", {"message": "Idioma alterado para português."})

    bus.clear()
    print("Registered events after clear:", bus.list_events())


if __name__ == "__main__":
    main()

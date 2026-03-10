from language_registry import LanguageRegistry, handle_language_detection


def main():
    registry = LanguageRegistry()
    current_language = "en"

    prompt = handle_language_detection(
        registry=registry,
        detected_code="pt",
        detected_name="Portuguese",
        confidence=0.93,
        current_language=current_language,
    )

    if prompt:
        print(prompt)
        # Simulate user saying yes
        registry.enable_for_session("pt")
        print(registry.activation_message("pt"))
        print(registry.remember_prompt("pt"))

    print(registry.export_state())


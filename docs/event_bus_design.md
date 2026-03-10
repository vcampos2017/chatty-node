# Chatty Event Bus Design

## Purpose

Chatty is growing into a modular system with multiple responsibilities:

- wake word detection
- speech handling
- language detection
- multilingual response flow
- sensor monitoring
- face and LED state changes
- alerts and status messages

As these capabilities grow, direct module-to-module calls can become tightly coupled and difficult to maintain.

The Chatty Event Bus provides a lightweight internal messaging system so modules can communicate through events rather than hardcoded dependencies.

---

## Design Goals

1. Keep Chatty modular.
2. Reduce direct coupling between subsystems.
3. Make new features easier to add.
4. Support sensor, voice, language, and UI coordination.
5. Keep the implementation lightweight enough for Raspberry Pi use.
6. Provide a clear path toward future distributed node behavior.

---

## Core Principle

Instead of this:

```text
voice module -> language module -> response module -> face module
```

Chatty should work more like this:

```text
voice module publishes "speech_detected"
language module subscribes to "speech_detected"
response module subscribes to "language_detected"
face module subscribes to "speech_output_started"
```

Each module does one job and reacts to events it cares about.

---

## Benefits

- simpler architecture
- easier debugging
- clearer responsibility boundaries
- better future-proofing
- easier testing of isolated modules
- natural fit for robotics-style systems

---

## Example Event Flow

User says something in Portuguese:

```text
wake_word_detected
-> listening_started
-> speech_detected
-> language_detected
-> language_switch_proposed
-> user_confirmation_received
-> language_activated
-> thinking_started
-> response_ready
-> speech_output_started
-> speech_output_finished
-> idle_resumed
```

This makes the system easier to reason about than nested direct calls.

---

## Suggested Event Names

### Voice and interaction
- wake_word_detected
- listening_started
- listening_stopped
- speech_detected
- user_confirmation_received

### Language
- language_detected
- language_switch_proposed
- language_activated

### Reasoning and response
- thinking_started
- response_ready
- speech_output_started
- speech_output_finished

### Sensors and alerts
- sensor_update
- sensor_alert
- lightning_detected
- soil_moisture_low
- temperature_changed

### State and error handling
- idle_resumed
- alert_triggered
- error_detected

---

## Lightweight Implementation

Chatty does not need a heavy external message broker for internal communication.

A simple in-process Python event bus is enough for the first version:

```python
class EventBus:
    def __init__(self):
        self._handlers = {}

    def subscribe(self, event_name, handler):
        self._handlers.setdefault(event_name, []).append(handler)

    def publish(self, event_name, payload=None):
        for handler in self._handlers.get(event_name, []):
            handler(payload or {})
```

This keeps resource use low and fits Raspberry Pi deployment well.

---

## Recommended Module Roles

### Voice module
Publishes:
- wake_word_detected
- speech_detected
- user_confirmation_received

Subscribes to:
- response_ready


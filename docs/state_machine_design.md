# Chatty State Machine Design

## Purpose

As Chatty grows in complexity, it needs a clear behavioral model for how it moves between interaction phases.

A state machine gives Chatty a predictable internal structure for:

- waiting
- listening
- thinking
- speaking
- alerting
- error handling
- sleeping and waking

This helps keep Chatty responsive, life-like, and maintainable.

---

## Design Goals

1. Make Chatty behavior predictable.
2. Support event-driven transitions.
3. Keep state changes simple and explicit.
4. Allow UI modules to react cleanly to state changes.
5. Support future interrupt handling and distributed node coordination.

---

## Core Principle

Chatty should always be in one clearly defined state.

Instead of many modules independently guessing what Chatty is doing, the system should maintain one authoritative interaction state.

---

## States

### idle
Default resting state.

### listening
Chatty has heard a wake request and is listening for input.

### thinking
Chatty is processing input, checking sensors, or generating a response.

### speaking
Chatty is actively delivering a spoken or displayed response.

### alert
Chatty is handling an urgent or important condition.

### error
Chatty encountered a recoverable problem.

### sleep
Low-activity mode with minimal interaction until reawakened.

---

## Suggested Transitions

```text
idle --wake_word_detected--> listening
listening --speech_detected--> thinking
thinking --response_ready--> speaking
speaking --speech_output_finished--> idle

any state --alert_triggered--> alert
alert --reset_requested--> idle

any state --error_detected--> error
error --reset_requested--> idle

idle --sleep_requested--> sleep
sleep --wake_requested--> idle
```

---

## Event Bus Integration

The state machine should subscribe to key Chatty events and change state accordingly.

Examples:

- `wake_word_detected`
- `speech_detected`
- `response_ready`
- `speech_output_finished`
- `alert_triggered`
- `error_detected`
- `sleep_requested`
- `wake_requested`
- `reset_requested`

When a valid transition occurs, the state machine should publish a `state_changed` event.

---

## Why Publish `state_changed`

Publishing `state_changed` allows other modules to react without tightly coupling themselves to the state machine.

Examples:

- face animation module updates expression
- LED module changes lighting behavior
- logger records state transitions
- UI dashboard reflects current status

---

## Example Event Flow

```text
wake_word_detected
-> state changes: idle -> listening
-> state_changed published

speech_detected
-> state changes: listening -> thinking
-> state_changed published

response_ready
-> state changes: thinking -> speaking
-> state_changed published

speech_output_finished
-> state changes: speaking -> idle
-> state_changed published
```

---

## Invalid Transitions

Some transitions should be ignored if they do not make sense for the current state.

Examples:

- `response_ready` while already `idle`
- `wake_requested` while not in `sleep`

Ignoring invalid transitions is safer than forcing a bad state.

---

## Future Extensions

Possible future upgrades:

- interruptible speaking state

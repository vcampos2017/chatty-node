# Chatty Context Manager Design

## Purpose

Chatty is evolving beyond simple input/output behavior. To feel responsive and life-like, it needs situational awareness.

The Context Manager gives Chatty a lightweight operational awareness layer that tracks:

- current interaction state
- current language
- recent events
- sensor snapshots
- pending alerts
- event priorities

This allows Chatty to combine multiple signals into a coherent response rather than treating every event in isolation.

---

## Design Goals

1. Maintain a lightweight view of what matters right now.
2. Track recent events with timestamps.
3. Track the latest known sensor values.
4. Distinguish between low, medium, and high priority events.
5. Queue non-urgent alerts when Chatty is busy.
6. Support summary generation for future response modules.
7. Stay simple enough for Raspberry Pi use.

---

## Core Principle

The Context Manager is not long-term memory.

It is short-horizon operational awareness.

It should help Chatty answer questions like:

- What is happening right now?
- What just happened recently?
- Is this event urgent enough to interrupt?
- Are several sensor signals related?

---

## What Context Includes

### Current State
Examples:
- idle
- listening
- thinking
- speaking
- alert
- error
- sleep

### Current Language
Examples:
- en
- es
- fr
- pt

### Recent Events
Recent events should include:
- event name
- timestamp
- priority
- payload

### Sensor Snapshot
Latest known values from key sensors, for example:
- soil moisture
- temperature
- humidity
- lightning distance
- rain expected

### Pending Alerts
Alerts that should be delivered later because Chatty was busy when they arrived.

---

## Priority Levels

### low
Normal informational events.

Examples:
- temperature_changed
- normal sensor update

### medium
Important but not immediately urgent events.

Examples:
- soil_moisture_low
- sensor offline
- rain expected

### high
Events that may require interruption or immediate user awareness.

Examples:
- lightning_detected
- leak_detected
- emergency_alert

---

## Suggested Priority Policy

- low priority events should never interrupt speaking
- medium priority events should usually queue while speaking
- high priority events may interrupt or force alert state

This allows Chatty to remain calm and coherent.

---

## Example Situational Fusion

### Garden Example

Events:
- soil_moisture_low
- rain_expected
- humidity_high

Possible response:

> Soil moisture is low, but rain is expected and humidity is high. Waiting to water may be reasonable.

---

### Storm Example

Events:
- barometric_pressure_drop
- lightning_detected
- outdoor_temperature_drop

Possible response:

> Storm conditions appear to be developing nearby.

---

## Event Bus Integration

The Context Manager should subscribe to important events such as:

- state_changed
- language_activated
- sensor_update
- sensor_alert
- lightning_detected
- soil_moisture_low
- response_ready

It should update internal context structures whenever these arrive.

---

## Queueing Behavior

If Chatty is speaking and a medium-priority alert arrives:

- add it to `pending_alerts`
- do not interrupt
- allow later summarization

If a high-priority alert arrives:

- mark it urgent
- allow future policy to interrupt or escalate

---

## Minimal Data Model

```python
context = {
    "current_state": "idle",
    "current_language": "en",

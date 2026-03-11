# Chatty Response Engine Design

## Purpose

The Response Engine converts Chatty's internal context into clear, human-friendly output.

By this stage, Chatty already has:

- an event bus
- a state machine
- a language registry
- a context manager

The Response Engine sits on top of those layers and decides how to express what Chatty knows.

---

## Design Goals

1. Turn context into concise natural-language responses.
2. Support multilingual output.
3. Keep phrasing calm, clear, and helpful.
4. Support summaries of multiple related sensor events.
5. Avoid over-speaking or overly robotic phrasing.
6. Remain lightweight enough for Raspberry Pi use.

---

## Core Principle

The Response Engine should explain the situation, not just repeat raw events.

Instead of saying:

> soil_moisture_low
> rain_expected
> humidity_high

Chatty should say:

> Soil moisture is low, but rain is expected soon.

This makes Chatty feel aware rather than mechanical.

---

## Inputs

The Response Engine may use:

- current Chatty state
- current language
- latest sensor snapshot
- recent events
- pending alerts

---

## Output Style

Responses should be:

- calm
- concise
- informative
- lightly conversational
- privacy-respecting

Avoid:

- alarmist phrasing
- excessive verbosity
- fake emotional claims

---

## Example Response Patterns

### Soil moisture only

> Soil moisture is low.

### Soil moisture + rain expected

> Soil moisture is low, but rain is expected soon.

### Lightning only

> Lightning has been detected nearby.

### Speaking state with pending alerts

> I also have a pending alert.

---

## Language Support

The first version should support simple response templates for:

- English (`en`)
- Spanish (`es`)
- French (`fr`)
- Portuguese (`pt`)

Fallback language should be English.

---

## Suggested Responsibilities

### Summary generation
Build simple environmental summaries from context.

### Alert response generation
Describe pending alerts or urgent conditions.

### Language selection
Use the current language from context when possible.

### Fallback behavior
Return a safe default response if no useful context is present.

---

## Example Situational Summaries

### Garden case

Context:
- soil_moisture = 0.22
- rain_expected event present
- humidity = 78

Response:

> Soil moisture is low, but rain is expected soon.

---

### Storm case

Context:
- lightning_detected pending

Response:

> Lightning has been detected nearby.

---

## Future Extensions

Possible future upgrades:

- richer natural language generation
- interrupt-aware phrasing
- node-specific summaries
- time-aware language such as "recently" or "earlier today"
- multi-sentence reports
- voice style variations

---

## Summary

The Response Engine is the layer that turns Chatty's architecture into user-facing language.

It helps Chatty move from:

- event processing
- state management
- context tracking

to:

- explanation
- guidance
- natural interaction

This completes the core loop of perception, awareness, and response.

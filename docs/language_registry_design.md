# Chatty Language Registry Design

## Purpose

Chatty should support multilingual interaction in a way that is:

- respectful
- adaptive
- privacy-first
- user-controlled
- future-friendly

Rather than relying on a permanently fixed language list, Chatty uses a **language registry** model. This allows Chatty to recognize, propose, and optionally remember additional languages it appears able to support.

---

## Design Goals

1. Start with a small known list of supported languages.
2. Detect when a user is speaking a different language.
3. Ask for confirmation in the detected language when possible.
4. Allow temporary session-only activation.
5. Optionally save the language permanently.
6. Avoid silent switching or silent config changes.
7. Keep the user in control.

---

## Core Principle

Chatty should not automatically and permanently change language settings just because it detects a new language.

Instead, Chatty should:

- detect
- confirm
- enable
- optionally remember

This keeps the interaction natural and prevents unwanted language changes.

---

## Registry Structure

Chatty maintains two language groups:

### Supported Languages
Languages fully configured for normal operation.

Examples:
- English
- Spanish
- French

### Discovered Languages
Languages Chatty has detected with sufficient confidence, but which are not yet part of the permanent supported configuration.

---

## Suggested Data Model

```python
language_registry = {
    "supported": {
        "en": {"name": "English", "status": "active"},
        "es": {"name": "Spanish", "status": "active"},
        "fr": {"name": "French", "status": "active"},
    },
    "discovered": {}
}
```

Example discovered entry:

```python
language_registry["discovered"]["pt"] = {
    "name": "Portuguese",
    "status": "detected",
    "first_seen": "2026-03-10T14:00:00",
    "confidence": 0.93
}
```

---

## Detection Workflow

1. User speaks.
2. Chatty detects probable language and confidence level.
3. If the language is already supported, continue normally.
4. If not supported, check confidence threshold.
5. If confidence is high enough, ask whether the user wants Chatty to speak in that language.
6. If the user agrees, enable it for the current session.
7. Optionally ask whether Chatty should remember it permanently.

---

## Example Interaction

### Spanish

User:
> ¿Puedes decirme la temperatura?

Chatty:
> Sí. ¿Quieres que hable en español?

User:
> Sí.

Chatty:
> Idioma cambiado a español.

---

### Portuguese

User:
> Você pode falar comigo em português?

Chatty:
> Posso falar em português. Quer que eu fale em português?

User:
> Sim.

Chatty:
> Português ativado para esta sessão.

Chatty:
> Quer que eu lembre esse idioma para o futuro?

---

## Confirmation Policy

Chatty should ask before switching languages when:

- the detected language differs from the current language
- confidence is high enough
- the language is not already active

Chatty should not repeatedly ask during the same interaction once the user has already confirmed.


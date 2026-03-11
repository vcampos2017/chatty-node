from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, DefaultDict, Dict, List, Optional


EventHandler = Callable[[Dict[str, Any]], None]


class EventBus:
    """
    Lightweight in-process event bus for Chatty.

    Modules publish named events with optional payloads.
    Other modules subscribe handlers to those event names.
    """

    def __init__(self) -> None:
        self._handlers: DefaultDict[str, List[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """
        Register a handler for an event.
        """
        self._handlers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> bool:
        """
        Remove a handler from an event.
        Returns True if removed, False if not found.
        """
        handlers = self._handlers.get(event_name, [])
        if handler in handlers:
            handlers.remove(handler)
            if not handlers:
                self._handlers.pop(event_name, None)
            return True
        return False

    def publish(self, event_name: str, payload: Optional[Dict[str, Any]] = None) -> List[Exception]:
        """
        Publish an event to all registered handlers.

        Returns a list of exceptions raised by handlers, if any.
        One failing handler should not stop the rest.
        """
        event_payload = payload or {}
        errors: List[Exception] = []

        for handler in list(self._handlers.get(event_name, [])):
            try:
                handler(event_payload)
            except Exception as exc:
                errors.append(exc)

        return errors

    def get_subscriber_count(self, event_name: str) -> int:
        """
        Return the number of handlers subscribed to an event.
        """
        return len(self._handlers.get(event_name, []))

    def list_events(self) -> List[str]:
        """
        Return a sorted list of registered event names.
        """
        return sorted(self._handlers.keys())

    def clear(self) -> None:
        """
        Remove all subscriptions.
        """
        self._handlers.clear()

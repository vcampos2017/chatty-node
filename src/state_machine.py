from __future__ import annotations

from typing import Dict, Optional

from event_bus import EventBus


class ChattyState:
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ALERT = "alert"
    ERROR = "error"
    SLEEP = "sleep"


class ChattyStateMachine:
    """
    Event-driven state machine for Chatty.
    """

    def __init__(self, bus: EventBus, initial_state: str = ChattyState.IDLE) -> None:
        self.bus = bus
        self.state = initial_state
        self.previous_state: Optional[str] = None

        self.transitions: Dict[str, Dict[str, str]] = {
            ChattyState.IDLE: {
                "wake_word_detected": ChattyState.LISTENING,
                "sleep_requested": ChattyState.SLEEP,
                "alert_triggered": ChattyState.ALERT,
                "error_detected": ChattyState.ERROR,
            },
            ChattyState.LISTENING: {
                "speech_detected": ChattyState.THINKING,
                "alert_triggered": ChattyState.ALERT,
                "error_detected": ChattyState.ERROR,
                "reset_requested": ChattyState.IDLE,
            },
            ChattyState.THINKING: {
                "response_ready": ChattyState.SPEAKING,
                "alert_triggered": ChattyState.ALERT,
                "error_detected": ChattyState.ERROR,
                "reset_requested": ChattyState.IDLE,
            },
            ChattyState.SPEAKING: {
                "speech_output_finished": ChattyState.IDLE,
                "alert_triggered": ChattyState.ALERT,
                "error_detected": ChattyState.ERROR,
                "reset_requested": ChattyState.IDLE,
            },
            ChattyState.ALERT: {
                "reset_requested": ChattyState.IDLE,
                "error_detected": ChattyState.ERROR,
            },
            ChattyState.ERROR: {
                "reset_requested": ChattyState.IDLE,
            },
            ChattyState.SLEEP: {
                "wake_requested": ChattyState.IDLE,
                "alert_triggered": ChattyState.ALERT,
                "error_detected": ChattyState.ERROR,
            },
        }

        self._subscribe_events()

    def _subscribe_events(self) -> None:
        event_names = {
            "wake_word_detected",
            "speech_detected",
            "response_ready",
            "speech_output_finished",
            "alert_triggered",
            "error_detected",
            "sleep_requested",
            "wake_requested",
            "reset_requested",
        }

        for event_name in event_names:
            self.bus.subscribe(event_name, self._make_event_handler(event_name))

    def _make_event_handler(self, event_name: str):
        def handler(payload):
            self.handle_event(event_name, payload)
        return handler

    def handle_event(self, event_name: str, payload: Optional[dict] = None) -> bool:
        """
        Process an event and transition state if valid.
        Returns True if a state change occurred, False otherwise.
        """
        next_state = self.transitions.get(self.state, {}).get(event_name)
        if not next_state:
            return False

        self.previous_state = self.state
        self.state = next_state

        self.bus.publish(
            "state_changed",
            {
                "from": self.previous_state,
                "to": self.state,
                "event": event_name,
                "payload": payload or {},
            },
        )
        return True

    def can_transition(self, event_name: str) -> bool:
        """
        Check whether the current state supports the event.
        """
        return event_name in self.transitions.get(self.state, {})

    def get_state(self) -> str:
        """
        Return the current Chatty state.
        """
        return self.state

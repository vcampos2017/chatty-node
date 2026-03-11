from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from event_bus import EventBus


DEFAULT_PRIORITY_MAP = {
    "temperature_changed": "low",
    "sensor_update": "low",
    "soil_moisture_low": "medium",
    "sensor_alert": "medium",
    "rain_expected": "medium",
    "lightning_detected": "high",
    "leak_detected": "high",
    "emergency_alert": "high",
}


class ContextManager:
    """
    Lightweight operational awareness layer for Chatty.
    """

    def __init__(self, bus: EventBus, max_recent_events: int = 50) -> None:
        self.bus = bus
        self.max_recent_events = max_recent_events

        self.current_state: str = "idle"
        self.current_language: str = "en"
        self.sensor_snapshot: Dict[str, Any] = {}
        self.recent_events: List[Dict[str, Any]] = []
        self.pending_alerts: List[Dict[str, Any]] = []

        self.priority_map = dict(DEFAULT_PRIORITY_MAP)

        self._subscribe_events()

    def _subscribe_events(self) -> None:
        self.bus.subscribe("state_changed", self._handle_state_changed)
        self.bus.subscribe("language_activated", self._handle_language_activated)
        self.bus.subscribe("sensor_update", self._handle_sensor_update)
        self.bus.subscribe("sensor_alert", self._handle_generic_event)
        self.bus.subscribe("lightning_detected", self._handle_generic_event)
        self.bus.subscribe("soil_moisture_low", self._handle_generic_event)
        self.bus.subscribe("rain_expected", self._handle_generic_event)
        self.bus.subscribe("response_ready", self._handle_generic_event)

    def _handle_state_changed(self, payload: Dict[str, Any]) -> None:
        new_state = payload.get("to")
        if new_state:
            self.current_state = new_state
        self.record_event("state_changed", payload, priority="low")

    def _handle_language_activated(self, payload: Dict[str, Any]) -> None:
        code = payload.get("code")
        if code:
            self.current_language = code
        self.record_event("language_activated", payload, priority="low")

    def _handle_sensor_update(self, payload: Dict[str, Any]) -> None:
        sensor_name = payload.get("sensor")
        value = payload.get("value")
        if sensor_name is not None:
            self.sensor_snapshot[sensor_name] = value
        self.record_event("sensor_update", payload, priority="low")

    def _handle_generic_event(self, payload: Dict[str, Any]) -> None:
        event_name = payload.get("_event_name", "unknown_event")
        priority = self.get_priority(event_name)
        self.record_event(event_name, payload, priority=priority)

        if priority in {"medium", "high"} and self.current_state == "speaking":
            self.pending_alerts.append(
                {
                    "event": event_name,
                    "priority": priority,
                    "payload": payload,
                    "time": self._now_iso(),
                }
            )

    def record_event(
        self,
        event_name: str,
        payload: Optional[Dict[str, Any]] = None,
        priority: Optional[str] = None,
    ) -> None:
        entry = {
            "event": event_name,
            "priority": priority or self.get_priority(event_name),
            "payload": payload or {},
            "time": self._now_iso(),
        }
        self.recent_events.append(entry)
        self.recent_events = self.recent_events[-self.max_recent_events :]

    def get_priority(self, event_name: str) -> str:
        return self.priority_map.get(event_name, "low")

    def publish_context_event(self, event_name: str, payload: Optional[Dict[str, Any]] = None) -> None:
        event_payload = dict(payload or {})
        event_payload["_event_name"] = event_name
        self.bus.publish(event_name, event_payload)

    def get_latest_sensor(self, sensor_name: str) -> Any:
        return self.sensor_snapshot.get(sensor_name)

    def get_recent_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.recent_events[-limit:]

    def get_pending_alerts(self) -> List[Dict[str, Any]]:
        return list(self.pending_alerts)

    def clear_pending_alerts(self) -> None:
        self.pending_alerts.clear()

    def export_context(self) -> Dict[str, Any]:
        return {
            "current_state": self.current_state,
            "current_language": self.current_language,
            "sensor_snapshot": dict(self.sensor_snapshot),
            "recent_events": list(self.recent_events),
            "pending_alerts": list(self.pending_alerts),
        }

    def summarize(self) -> str:
        summary_parts = [
            f"state={self.current_state}",
            f"language={self.current_language}",
            f"recent_events={len(self.recent_events)}",
            f"pending_alerts={len(self.pending_alerts)}",
        ]

        if self.sensor_snapshot:
            sensor_bits = ", ".join(
                f"{key}={value}" for key, value in sorted(self.sensor_snapshot.items())
            )
            summary_parts.append(f"sensors[{sensor_bits}]")

        return " | ".join(summary_parts)

    @staticmethod

from __future__ import annotations

from typing import Any, Dict, List


class ResponseEngine:
    """
    Lightweight natural-language response layer for Chatty.
    """

    def __init__(self) -> None:
        self.templates = {
            "en": {
                "default": "I do not have enough context yet.",
                "soil_low": "Soil moisture is low.",
                "soil_low_rain": "Soil moisture is low, but rain is expected soon.",
                "lightning": "Lightning has been detected nearby.",
                "pending_alert": "I also have a pending alert.",
            },
            "es": {
                "default": "Todavía no tengo suficiente contexto.",
                "soil_low": "La humedad del suelo es baja.",
                "soil_low_rain": "La humedad del suelo es baja, pero se espera lluvia pronto.",
                "lightning": "Se ha detectado actividad eléctrica cerca.",
                "pending_alert": "También tengo una alerta pendiente.",
            },
            "fr": {
                "default": "Je n’ai pas encore assez de contexte.",
                "soil_low": "L’humidité du sol est faible.",
                "soil_low_rain": "L’humidité du sol est faible, mais de la pluie est attendue bientôt.",
                "lightning": "De la foudre a été détectée à proximité.",
                "pending_alert": "J’ai aussi une alerte en attente.",
            },
            "pt": {
                "default": "Ainda não tenho contexto suficiente.",
                "soil_low": "A umidade do solo está baixa.",
                "soil_low_rain": "A umidade do solo está baixa, mas chuva é esperada em breve.",
                "lightning": "Foi detectada atividade elétrica nas proximidades.",
                "pending_alert": "Também tenho um alerta pendente.",
            },
        }

    def generate_summary(self, context: Dict[str, Any]) -> str:
        language = context.get("current_language", "en")
        templates = self.templates.get(language, self.templates["en"])

        sensor_snapshot = context.get("sensor_snapshot", {})
        recent_events = context.get("recent_events", [])
        pending_alerts = context.get("pending_alerts", [])

        soil_value = sensor_snapshot.get("soil_moisture")
        rain_expected = self._has_event(recent_events, "rain_expected")
        lightning_detected = self._has_event(recent_events, "lightning_detected")

        if lightning_detected:
            return templates["lightning"]

        if soil_value is not None and soil_value < 0.30 and rain_expected:
            return templates["soil_low_rain"]

        if soil_value is not None and soil_value < 0.30:
            return templates["soil_low"]

        if pending_alerts:
            return templates["pending_alert"]

        return templates["default"]

    def generate_alert_report(self, context: Dict[str, Any]) -> List[str]:
        language = context.get("current_language", "en")
        templates = self.templates.get(language, self.templates["en"])
        pending_alerts = context.get("pending_alerts", [])

        messages: List[str] = []
        for alert in pending_alerts:
            event_name = alert.get("event")
            if event_name == "lightning_detected":
                messages.append(templates["lightning"])
            elif event_name == "soil_moisture_low":
                messages.append(templates["soil_low"])
            else:
                messages.append(templates["pending_alert"])
        return messages

    @staticmethod
    def _has_event(events: List[Dict[str, Any]], event_name: str) -> bool:
        for event in events:
            if event.get("event") == event_name:
                return True
        return False

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, Optional


LANGUAGE_DETECTION_THRESHOLD = 0.85


@dataclass
class LanguageEntry:
    code: str
    name: str
    status: str
    first_seen: Optional[str] = None
    confidence: Optional[float] = None


class LanguageRegistry:
    """
    Chatty language registry.

    Maintains:
    - supported languages: fully enabled for normal use
    - discovered languages: detected but not yet permanently enabled
    """

    def __init__(self) -> None:
        self.supported: Dict[str, LanguageEntry] = {
            "en": LanguageEntry(code="en", name="English", status="active"),
            "es": LanguageEntry(code="es", name="Spanish", status="active"),
            "fr": LanguageEntry(code="fr", name="French", status="active"),
        }
        self.discovered: Dict[str, LanguageEntry] = {}

    def is_supported(self, code: str) -> bool:
        return code in self.supported

    def is_discovered(self, code: str) -> bool:
        return code in self.discovered

    def add_discovered(self, code: str, name: str, confidence: float) -> bool:
        """
        Add a newly detected language to discovered_languages
        if confidence is high enough and it is not already supported.
        Returns True if added, False otherwise.
        """
        if self.is_supported(code):
            return False

        if confidence < LANGUAGE_DETECTION_THRESHOLD:
            return False

        if self.is_discovered(code):
            return False

        self.discovered[code] = LanguageEntry(
            code=code,
            name=name,
            status="detected",
            first_seen=self._now_iso(),
            confidence=round(confidence, 3),
        )
        return True

    def enable_for_session(self, code: str, name: Optional[str] = None) -> bool:
        """
        Promote a language into supported for the current runtime.
        Returns True if enabled, False if not possible.
        """
        if self.is_supported(code):
            return True

        if code in self.discovered:
            entry = self.discovered.pop(code)
            self.supported[code] = LanguageEntry(
                code=entry.code,
                name=entry.name,
                status="session",
                first_seen=entry.first_seen,
                confidence=entry.confidence,
            )
            return True

        if name:
            self.supported[code] = LanguageEntry(
                code=code,
                name=name,
                status="session",
            )
            return True

        return False

    def remember_permanently(self, code: str) -> bool:
        """
        Mark an already enabled language as permanently active.
        """
        if not self.is_supported(code):
            return False

        entry = self.supported[code]
        entry.status = "active"
        return True

    def confirmation_prompt(self, code: str) -> str:
        """
        Return a polite confirmation prompt in the detected language,
        falling back to English when needed.
        """
        prompts = {
            "en": "Do you want me to speak in English?",
            "es": "¿Quieres que hable en español?",
            "fr": "Voulez-vous que je parle en français ?",
            "pt": "Quer que eu fale em português?",
            "de": "Möchten Sie, dass ich auf Deutsch spreche?",
            "it": "Vuoi che parli in italiano?",
        }
        return prompts.get(code, "Do you want me to speak in that language?")

    def activation_message(self, code: str) -> str:
        """
        Return a simple activation confirmation in the active language.
        """
        messages = {
            "en": "Language switched to English.",
            "es": "Idioma cambiado a español.",
            "fr": "Langue changée en français.",
            "pt": "Idioma alterado para português.",
            "de": "Sprache auf Deutsch umgestellt.",
            "it": "Lingua cambiata in italiano.",
        }
        return messages.get(code, "Language updated.")

    def remember_prompt(self, code: str) -> str:
        """
        Ask whether the user wants Chatty to remember the language.
        """
        prompts = {
            "en": "Do you want me to remember this language for the future?",
            "es": "¿Quieres que recuerde este idioma para el futuro?",
            "fr": "Voulez-vous que je mémorise cette langue pour l’avenir ?",
            "pt": "Quer que eu lembre esse idioma para o futuro?",
            "de": "Möchten Sie, dass ich mir diese Sprache für die Zukunft merke?",

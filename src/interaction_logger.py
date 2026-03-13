from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class InteractionEvent:
    ts: str
    wake_word: Optional[str] = None
    wake_confidence: Optional[float] = None
    phrase_hash: Optional[str] = None
    intent: Optional[str] = None
    topic: Optional[str] = None
    handled: Optional[bool] = None
    response_type: Optional[str] = None
    duration_s: Optional[float] = None
    language: Optional[str] = None
    fulfillment_mode: Optional[str] = None
    provider: Optional[str] = None
    fallback_used: Optional[bool] = None
    cloud_required: Optional[bool] = None
    notes: Optional[str] = None
    transcript: Optional[str] = None  # debug mode only


class InteractionLogger:
    """
    Privacy-first rolling interaction logger for Chatty.

    Default behavior:
    - stores structured interaction signals only
    - does NOT store raw transcripts
    - rotates log files by size
    - hashes normalized phrases with a local salt
    """

    def __init__(
        self,
        log_dir: str = "logs",
        log_name: str = "chatty_events.jsonl",
        max_bytes: int = 1_000_000,
        keep_rotated: int = 3,
        debug_mode: bool = False,
        salt_env_var: str = "CHATTY_HASH_SALT",
        salt_file: str = "/etc/chatty/hash_salt",
    ) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log_path = self.log_dir / log_name
        self.max_bytes = max_bytes
        self.keep_rotated = keep_rotated
        self.debug_mode = debug_mode

        self.salt = self._load_salt(salt_env_var=salt_env_var, salt_file=salt_file)

    def log_event(
        self,
        *,
        wake_word: Optional[str] = None,
        wake_confidence: Optional[float] = None,
        normalized_phrase: Optional[str] = None,
        intent: Optional[str] = None,
        topic: Optional[str] = None,
        handled: Optional[bool] = None,
        response_type: Optional[str] = None,
        duration_s: Optional[float] = None,
        language: Optional[str] = None,
        fulfillment_mode: Optional[str] = None,
        provider: Optional[str] = None,
        fallback_used: Optional[bool] = None,
        cloud_required: Optional[bool] = None,
        notes: Optional[str] = None,
        transcript: Optional[str] = None,
    ) -> Dict[str, Any]:
        phrase_hash = None
        if normalized_phrase:
            phrase_hash = self.hash_phrase(normalized_phrase)

        event = InteractionEvent(
            ts=self._now_iso(),
            wake_word=wake_word,
            wake_confidence=round(wake_confidence, 4) if wake_confidence is not None else None,
            phrase_hash=phrase_hash,
            intent=intent,
            topic=topic,
            handled=handled,
            response_type=response_type,
            duration_s=round(duration_s, 3) if duration_s is not None else None,
            language=language,
            fulfillment_mode=fulfillment_mode,
            provider=provider,
            fallback_used=fallback_used,
            cloud_required=cloud_required,
            notes=notes,
            transcript=transcript if self.debug_mode else None,
        )

        data = {k: v for k, v in asdict(event).items() if v is not None}
        self._rotate_if_needed()
        self._append_jsonl(data)
        return data

    def hash_phrase(self, normalized_phrase: str) -> str:
        """
        Salted short hash for phrase tracking.
        Only the local node can generate consistent hashes.
        """
        normalized = normalized_phrase.strip().lower()
        digest = hashlib.sha256(f"{self.salt}:{normalized}".encode("utf-8")).hexdigest()
        return digest[:8]

    def _append_jsonl(self, record: Dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _rotate_if_needed(self) -> None:
        if not self.log_path.exists():
            return

        if self.log_path.stat().st_size < self.max_bytes:
            return

        oldest = self.log_dir / f"{self.log_path.name}.{self.keep_rotated}"
        if oldest.exists():
            oldest.unlink()

        for i in range(self.keep_rotated - 1, 0, -1):
            src = self.log_dir / f"{self.log_path.name}.{i}"
            dst = self.log_dir / f"{self.log_path.name}.{i + 1}"
            if src.exists():
                src.rename(dst)

        rotated = self.log_dir / f"{self.log_path.name}.1"
        self.log_path.rename(rotated)

    def _load_salt(self, *, salt_env_var: str, salt_file: str) -> str:
        env_salt = os.getenv(salt_env_var)
        if env_salt:
            return env_salt.strip()

        salt_path = Path(salt_file)
        if salt_path.exists():
            return salt_path.read_text(encoding="utf-8").strip()

        fallback = f"chatty-local-salt-{int(time.time())}"
        return fallback

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    logger = InteractionLogger(debug_mode=False)

    example = logger.log_event(
        wake_word="hey_jarvis",
        wake_confidence=0.98,
        normalized_phrase="time_query",
        intent="time_query",
        topic="system",
        handled=True,
        response_type="time_answer",
        duration_s=1.24,
        language="en",
        fulfillment_mode="local",
        provider="local_runtime",
        fallback_used=False,
        cloud_required=False,
        notes="manual test event",
    )

    print("Logged event:")
    print(example)

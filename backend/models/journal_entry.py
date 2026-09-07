"""Journal entry model and DynamoDB mapping.

Key design (single table):
    PK = USER#{userId}
    SK = ENTRY#{entryDate}#{entryId}

Sorting by SK therefore sorts by date, which is what the history page needs.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

# The only mood values the system accepts. Anything else from Gemini is rejected.
VALID_MOODS = ("POSITIVE", "NEUTRAL", "ANXIOUS", "NEGATIVE")

# Numeric values used only to draw the trend chart. They are not a measurement
# of wellbeing and the UI says so.
MOOD_SCORES = {"POSITIVE": 2, "NEUTRAL": 1, "ANXIOUS": 0, "NEGATIVE": -1}

DEFAULT_MOOD = "NEUTRAL"

ENTITY_TYPE = "ENTRY"


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class JournalEntry:
    """One journal entry and its mood classification."""

    user_id: str
    content: str
    entry_date: str
    title: str = ""
    mood: str = DEFAULT_MOOD
    confidence: float = 0.0
    short_reason: str = ""
    classification_fallback: bool = False
    entry_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @property
    def mood_score(self) -> int:
        return MOOD_SCORES.get(self.mood, MOOD_SCORES[DEFAULT_MOOD])

    @property
    def pk(self) -> str:
        return f"USER#{self.user_id}"

    @property
    def sk(self) -> str:
        return f"ENTRY#{self.entry_date}#{self.entry_id}"

    @property
    def search_text(self) -> str:
        """Title and content folded to lowercase, for case-insensitive search."""
        return f"{self.title} {self.content}".strip().lower()

    def to_item(self) -> dict[str, Any]:
        """Convert to a DynamoDB item.

        Floats are stored as Decimal because DynamoDB rejects Python floats.
        """
        return {
            "PK": self.pk,
            "SK": self.sk,
            "entityType": ENTITY_TYPE,
            "entryId": self.entry_id,
            "userId": self.user_id,
            "title": self.title,
            "content": self.content,
            "entryDate": self.entry_date,
            "mood": self.mood,
            "moodScore": self.mood_score,
            "confidence": Decimal(str(round(self.confidence, 2))),
            "shortReason": self.short_reason,
            "classificationFallback": self.classification_fallback,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            # Lowercased title + content, so the history page's search can use a
            # case-insensitive `contains` filter. DynamoDB has no text index and
            # `contains` does not fold case, so the value it compares against
            # has to be stored already folded.
            "searchText": self.search_text,
        }

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "JournalEntry":
        """Rebuild an entry from a DynamoDB item."""
        return cls(
            user_id=item["userId"],
            content=item["content"],
            entry_date=item["entryDate"],
            title=item.get("title", ""),
            mood=item.get("mood", DEFAULT_MOOD),
            confidence=float(item.get("confidence", 0)),
            short_reason=item.get("shortReason", ""),
            classification_fallback=bool(item.get("classificationFallback", False)),
            entry_id=item["entryId"],
            created_at=item.get("createdAt", ""),
            updated_at=item.get("updatedAt", ""),
        )

    def to_api(self) -> dict[str, Any]:
        """Shape returned to the frontend. PK and SK stay internal."""
        return {
            "entryId": self.entry_id,
            "title": self.title,
            "content": self.content,
            "entryDate": self.entry_date,
            "mood": self.mood,
            "moodScore": self.mood_score,
            "confidence": round(self.confidence, 2),
            "shortReason": self.short_reason,
            "classificationFallback": self.classification_fallback,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

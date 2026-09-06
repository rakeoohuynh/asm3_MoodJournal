"""AI reflection model and DynamoDB mapping.

Key design (single table, shares MoodJournalTable with entries):
    PK = USER#{userId}
    SK = REFLECTION#{createdAt}#{reflectionId}
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from models.journal_entry import utc_now_iso

ENTITY_TYPE = "REFLECTION"

DISCLAIMER = (
    "This AI-generated reflection is for personal journaling and general "
    "self-reflection only. It is not medical or professional advice."
)


@dataclass
class Reflection:
    """A generated summary covering a date range of entries."""

    user_id: str
    period: str
    period_start: str
    period_end: str
    summary: str
    entry_count: int = 0
    generated_by: str = "manual"
    reflection_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def pk(self) -> str:
        return f"USER#{self.user_id}"

    @property
    def sk(self) -> str:
        return f"REFLECTION#{self.created_at}#{self.reflection_id}"

    def to_item(self) -> dict[str, Any]:
        return {
            "PK": self.pk,
            "SK": self.sk,
            "entityType": ENTITY_TYPE,
            "reflectionId": self.reflection_id,
            "userId": self.user_id,
            "period": self.period,
            "periodStart": self.period_start,
            "periodEnd": self.period_end,
            "summary": self.summary,
            "entryCount": self.entry_count,
            "generatedBy": self.generated_by,
            "createdAt": self.created_at,
        }

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "Reflection":
        return cls(
            user_id=item["userId"],
            period=item.get("period", ""),
            period_start=item.get("periodStart", ""),
            period_end=item.get("periodEnd", ""),
            summary=item.get("summary", ""),
            entry_count=int(item.get("entryCount", 0)),
            generated_by=item.get("generatedBy", "manual"),
            reflection_id=item["reflectionId"],
            created_at=item.get("createdAt", ""),
        )

    def to_api(self) -> dict[str, Any]:
        return {
            "reflectionId": self.reflection_id,
            "period": self.period,
            "periodStart": self.period_start,
            "periodEnd": self.period_end,
            "summary": self.summary,
            "entryCount": self.entry_count,
            "generatedBy": self.generated_by,
            "createdAt": self.created_at,
            "disclaimer": DISCLAIMER,
        }

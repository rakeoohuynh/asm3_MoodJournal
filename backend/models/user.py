"""User model and DynamoDB mapping.

Users live in their own table (MoodJournalUsers) rather than the single
journal table, because they are looked up by username at login through a GSI:

    Table:  userId (partition key)
    GSI:    UsernameIndex -> username (partition key)

`to_api` deliberately omits password_hash. It must never leave the backend.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from models.journal_entry import utc_now_iso


@dataclass
class User:
    """A registered account."""

    username: str
    password_hash: str
    user_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_item(self) -> dict[str, Any]:
        return {
            "userId": self.user_id,
            "username": self.username,
            "passwordHash": self.password_hash,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "User":
        return cls(
            username=item["username"],
            password_hash=item["passwordHash"],
            user_id=item["userId"],
            created_at=item.get("createdAt", ""),
            updated_at=item.get("updatedAt", ""),
        )

    def to_api(self) -> dict[str, Any]:
        """Safe representation. Never includes the password hash."""
        return {
            "userId": self.user_id,
            "username": self.username,
            "createdAt": self.created_at,
        }

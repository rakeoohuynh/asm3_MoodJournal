"""Journal entry business logic.

Sits between the handlers (HTTP concerns) and the repository (storage), and
owns the one rule that matters: every saved or edited entry gets classified.
"""

from models.journal_entry import JournalEntry, utc_now_iso
from repositories.journal_repository import JournalRepository
from services import gemini_service
from utils.logging_config import get_logger

logger = get_logger(__name__)


class EntryNotFoundError(Exception):
    """Raised when an entry does not exist for this user."""


def create_entry(
    user_id: str,
    title: str,
    content: str,
    entry_date: str,
    repo: JournalRepository | None = None,
) -> JournalEntry:
    """Classify and store a new entry."""
    repo = repo or JournalRepository()

    result = gemini_service.classify_mood(content)
    entry = JournalEntry(
        user_id=user_id,
        content=content,
        entry_date=entry_date,
        title=title,
        mood=result.mood,
        confidence=result.confidence,
        short_reason=result.short_reason,
        classification_fallback=result.fallback,
    )
    return repo.put_entry(entry)


def update_entry(
    user_id: str,
    entry_id: str,
    title: str,
    content: str,
    entry_date: str,
    repo: JournalRepository | None = None,
) -> JournalEntry:
    """Re-classify and update an existing entry.

    When the date changes the sort key changes too, so the old item is deleted
    before the new one is written.
    """
    repo = repo or JournalRepository()

    existing = repo.get_entry(user_id, entry_id)
    if existing is None:
        raise EntryNotFoundError(entry_id)

    result = gemini_service.classify_mood(content)
    updated = JournalEntry(
        user_id=user_id,
        content=content,
        entry_date=entry_date,
        title=title,
        mood=result.mood,
        confidence=result.confidence,
        short_reason=result.short_reason,
        classification_fallback=result.fallback,
        entry_id=entry_id,
        created_at=existing.created_at,
        updated_at=utc_now_iso(),
    )

    if existing.sk != updated.sk:
        repo.delete_entry(user_id, existing)

    return repo.put_entry(updated)


def delete_entry(
    user_id: str, entry_id: str, repo: JournalRepository | None = None
) -> None:
    """Delete an entry."""
    repo = repo or JournalRepository()

    existing = repo.get_entry(user_id, entry_id)
    if existing is None:
        raise EntryNotFoundError(entry_id)

    repo.delete_entry(user_id, existing)

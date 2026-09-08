"""Shared test setup.

These tests exercise the deployed architecture - services and Lambda handlers -
without AWS and without network access. Repositories are replaced by in-test
stubs and Gemini is monkeypatched, so nothing here needs credentials, a
DynamoDB table, or an API quota.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Lambda unpacks the bundle so that "models", "services" etc. are top level.
# Reproduce that layout rather than importing through a "backend." prefix.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Set before any service module is imported: auth_service reads JWT_SECRET, and
# an absent GEMINI_API_KEY keeps gemini_service from reaching the network even
# if a test forgets to patch it.
os.environ["JWT_SECRET"] = "pytest-secret-at-least-32-bytes-long-for-hs256"
os.environ["ENVIRONMENT"] = "test"
os.environ.pop("GEMINI_API_KEY", None)

import pytest  # noqa: E402
from models.journal_entry import JournalEntry  # noqa: E402
from models.reflection import Reflection  # noqa: E402
from models.user import User  # noqa: E402


def utc_today() -> date:
    """Today in UTC, which is the only "today" the application knows.

    Services derive their date ranges from datetime.now(timezone.utc), and
    entry dates are stored as UTC dates. Using date.today() in a test means the
    *local* date, so anywhere east of UTC the tests seed entries dated
    "tomorrow" for part of every day and the ranges silently miss them.
    """
    return datetime.now(timezone.utc).date()


class StubUserRepository:
    """In-test stand-in for repositories.user_repository.UserRepository."""

    def __init__(self) -> None:
        self.by_id: dict[str, User] = {}
        self.by_username: dict[str, str] = {}

    def find_by_username(self, username: str) -> User | None:
        user_id = self.by_username.get(username)
        return self.by_id.get(user_id) if user_id else None

    def find_by_id(self, user_id: str) -> User | None:
        return self.by_id.get(user_id)

    def create(self, user: User) -> User:
        from repositories.user_repository import UsernameTakenError

        if user.username in self.by_username:
            raise UsernameTakenError(user.username)
        self.by_id[user.user_id] = user
        self.by_username[user.username] = user.user_id
        return user

    def update_password(self, user_id: str, password_hash: str, updated_at: str) -> None:
        user = self.by_id[user_id]
        user.password_hash = password_hash
        user.updated_at = updated_at


class StubJournalRepository:
    """In-test stand-in for repositories.journal_repository.JournalRepository.

    Mirrors the DynamoDB repository's signatures, including the opaque
    start_key/last_key pagination contract, so a test failure means the service
    is wrong rather than the stub being a different shape.
    """

    def __init__(self) -> None:
        self.entries: list[JournalEntry] = []
        self.reflections: list[Reflection] = []

    # -- entries ----------------------------------------------------------
    def put_entry(self, entry: JournalEntry) -> JournalEntry:
        self.entries = [e for e in self.entries if e.entry_id != entry.entry_id]
        self.entries.append(entry)
        return entry

    def get_entry(self, user_id: str, entry_id: str) -> JournalEntry | None:
        return next(
            (e for e in self.entries if e.user_id == user_id and e.entry_id == entry_id),
            None,
        )

    def list_entries(
        self,
        user_id: str,
        mood: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        search: str | None = None,
        limit: int = 20,
        start_key: dict | None = None,
    ) -> tuple[list[JournalEntry], dict | None]:
        found = [e for e in self.entries if e.user_id == user_id]
        if mood:
            found = [e for e in found if e.mood == mood]
        if start_date:
            found = [e for e in found if e.entry_date >= start_date]
        if end_date:
            found = [e for e in found if e.entry_date <= end_date]
        if search and search.strip():
            needle = search.strip().lower()
            found = [e for e in found if needle in e.search_text]

        found.sort(key=lambda e: (e.entry_date, e.created_at), reverse=True)
        offset = int((start_key or {}).get("offset", 0))
        page = found[offset : offset + limit]
        next_offset = offset + len(page)
        return page, ({"offset": next_offset} if next_offset < len(found) else None)

    def list_entries_in_range(
        self, user_id: str, start_date: str, end_date: str
    ) -> list[JournalEntry]:
        found = [
            e
            for e in self.entries
            if e.user_id == user_id and start_date <= e.entry_date <= end_date
        ]
        found.sort(key=lambda e: (e.entry_date, e.created_at), reverse=True)
        return found

    def delete_entry(self, user_id: str, entry: JournalEntry) -> None:
        self.entries = [
            e for e in self.entries
            if not (e.user_id == user_id and e.entry_id == entry.entry_id)
        ]

    # -- reflections ------------------------------------------------------
    def put_reflection(self, reflection: Reflection) -> Reflection:
        self.reflections.append(reflection)
        return reflection

    def list_reflections(
        self, user_id: str, limit: int = 20, start_key: dict | None = None
    ) -> tuple[list[Reflection], dict | None]:
        found = [r for r in self.reflections if r.user_id == user_id]
        found.sort(key=lambda r: r.created_at, reverse=True)
        return found[:limit], None


@pytest.fixture
def users() -> StubUserRepository:
    return StubUserRepository()


@pytest.fixture
def journals() -> StubJournalRepository:
    return StubJournalRepository()


@pytest.fixture
def fake_gemini(monkeypatch):
    """Replace Gemini with deterministic offline responses.

    Returns a dict the test can mutate to simulate failure.
    """
    from services import gemini_service

    state = {"mood": "POSITIVE", "confidence": 0.91, "fail": False}

    def classify_mood(text: str):
        if state["fail"]:
            return gemini_service.MoodResult(
                mood="NEUTRAL", confidence=0.0, short_reason="unavailable", fallback=True
            )
        return gemini_service.MoodResult(
            mood=state["mood"], confidence=state["confidence"], short_reason="stubbed"
        )

    def generate_reflection(period_label: str, summary_data: str) -> str:
        if state["fail"]:
            raise gemini_service.GeminiError("stubbed Gemini outage")
        return f"Stub reflection for {period_label}."

    monkeypatch.setattr(gemini_service, "classify_mood", classify_mood)
    monkeypatch.setattr(gemini_service, "generate_reflection", generate_reflection)
    return state


def api_event(
    user_id: str | None = "user-1",
    query: dict | None = None,
    path: dict | None = None,
    body: str | None = None,
    method: str = "GET",
) -> dict:
    """Build an API Gateway proxy event as the JWT authorizer leaves it."""
    event: dict = {
        "httpMethod": method,
        "queryStringParameters": query,
        "pathParameters": path,
        "body": body,
        "requestContext": {},
    }
    if user_id is not None:
        event["requestContext"] = {"authorizer": {"userId": user_id}}
    return event

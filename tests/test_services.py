"""Service-layer tests.

These cover the business rules that run inside Lambda: authentication,
journal CRUD, dashboard aggregation and reflection generation. Storage is a
stub repository and Gemini is patched, so no AWS or network access is needed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from models.journal_entry import JournalEntry
from repositories.user_repository import UsernameTakenError
from services import analytics_service, auth_service, journal_service, reflection_service
from services.auth_service import AuthError
from services.journal_service import EntryNotFoundError
from services.reflection_service import NoEntriesError

from tests.conftest import utc_today

PASSWORD = "Password123"


def make_user(users, username="alice", password=PASSWORD):
    return auth_service.register(username, password, repo=users)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_register_hashes_password_and_hides_it(users):
    user = make_user(users)

    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert "passwordHash" not in user.to_api()


def test_duplicate_username_is_rejected(users):
    make_user(users, "alice")
    with pytest.raises(UsernameTakenError):
        make_user(users, "alice")


def test_login_succeeds_with_correct_password(users):
    created = make_user(users)
    assert auth_service.login("alice", PASSWORD, repo=users).user_id == created.user_id


@pytest.mark.parametrize(
    "username,password",
    [("alice", "WrongPassword1"), ("nobody", PASSWORD)],
    ids=["wrong-password", "unknown-user"],
)
def test_login_failures_are_indistinguishable(users, username, password):
    """A wrong password and an unknown user must raise the same error.

    Anything else lets an attacker enumerate which usernames exist.
    """
    make_user(users)
    with pytest.raises(AuthError):
        auth_service.login(username, password, repo=users)


def test_token_round_trip_carries_the_user_id(users):
    user = make_user(users)
    token, expires_at = auth_service.issue_token(user)

    claims = auth_service.verify_token(token)
    assert claims["sub"] == user.user_id
    assert claims["username"] == "alice"
    assert expires_at


def test_tampered_token_is_rejected(users):
    user = make_user(users)
    token, _ = auth_service.issue_token(user)

    with pytest.raises(AuthError):
        auth_service.verify_token(token[:-1] + ("x" if token[-1] != "x" else "y"))


def test_change_password_requires_the_current_one(users):
    user = make_user(users)

    with pytest.raises(AuthError):
        auth_service.change_password(user.user_id, "NotMyPassword1", "NewPass456", repo=users)

    # The rejected attempt must not have changed anything.
    assert auth_service.login("alice", PASSWORD, repo=users)

    auth_service.change_password(user.user_id, PASSWORD, "NewPass456", repo=users)
    assert auth_service.login("alice", "NewPass456", repo=users)
    with pytest.raises(AuthError):
        auth_service.login("alice", PASSWORD, repo=users)


# ---------------------------------------------------------------------------
# Journal entries
# ---------------------------------------------------------------------------


def test_create_entry_classifies_and_stores(journals, fake_gemini):
    entry = journal_service.create_entry(
        user_id="u1", title="Good day", content="Felt great.",
        entry_date=utc_today().isoformat(), repo=journals,
    )

    assert entry.mood == "POSITIVE"
    assert entry.classification_fallback is False
    assert journals.get_entry("u1", entry.entry_id) is not None


def test_gemini_outage_still_saves_the_entry(journals, fake_gemini):
    """An external API failure must never lose a user's writing."""
    fake_gemini["fail"] = True

    entry = journal_service.create_entry(
        user_id="u1", title="", content="Something happened.",
        entry_date=utc_today().isoformat(), repo=journals,
    )

    assert journals.get_entry("u1", entry.entry_id) is not None
    # Marked as a fallback, so nothing claims this mood came from Gemini.
    assert entry.classification_fallback is True


def test_update_entry_reclassifies_and_keeps_created_at(journals, fake_gemini):
    original = journal_service.create_entry(
        user_id="u1", title="First", content="Neutral text.",
        entry_date=utc_today().isoformat(), repo=journals,
    )

    fake_gemini["mood"] = "ANXIOUS"
    updated = journal_service.update_entry(
        user_id="u1", entry_id=original.entry_id, title="Second",
        content="Worried now.", entry_date=original.entry_date, repo=journals,
    )

    assert updated.entry_id == original.entry_id
    assert updated.created_at == original.created_at
    assert updated.mood == "ANXIOUS"
    assert len(journals.entries) == 1


def test_update_and_delete_reject_unknown_entries(journals, fake_gemini):
    with pytest.raises(EntryNotFoundError):
        journal_service.update_entry(
            user_id="u1", entry_id="missing", title="x", content="y",
            entry_date=utc_today().isoformat(), repo=journals,
        )
    with pytest.raises(EntryNotFoundError):
        journal_service.delete_entry("u1", "missing", repo=journals)


def test_delete_entry_removes_it(journals, fake_gemini):
    entry = journal_service.create_entry(
        user_id="u1", title="Temp", content="Delete me.",
        entry_date=utc_today().isoformat(), repo=journals,
    )
    journal_service.delete_entry("u1", entry.entry_id, repo=journals)
    assert journals.get_entry("u1", entry.entry_id) is None


def test_one_user_cannot_reach_another_users_entry(journals, fake_gemini):
    entry = journal_service.create_entry(
        user_id="alice", title="Private", content="Alice only.",
        entry_date=utc_today().isoformat(), repo=journals,
    )

    assert journals.get_entry("bob", entry.entry_id) is None
    with pytest.raises(EntryNotFoundError):
        journal_service.delete_entry("bob", entry.entry_id, repo=journals)


def test_search_text_is_folded_for_case_insensitive_matching():
    entry = JournalEntry(
        user_id="u1", title="Deadline Looming", content="I am STRESSED.",
        entry_date=utc_today().isoformat(),
    )
    assert "deadline looming" in entry.search_text
    assert "stressed" in entry.search_text
    assert entry.to_item()["searchText"] == entry.search_text


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def seed_entries(journals, moods: list[str], user_id="u1") -> None:
    today = utc_today()
    for offset, mood in enumerate(moods):
        journals.put_entry(
            JournalEntry(
                user_id=user_id, title=f"Entry {offset}", content="text",
                entry_date=(today - timedelta(days=offset)).isoformat(),
                mood=mood, confidence=0.9,
            )
        )


def test_dashboard_returns_every_field_the_frontend_reads(journals):
    seed_entries(journals, ["POSITIVE", "POSITIVE", "ANXIOUS", "NEUTRAL"])

    dashboard = analytics_service.build_dashboard("u1", 7, repo=journals)

    # dashboard.html reads each of these by name.
    for field in (
        "totalEntries", "mostCommonMood", "averageScore", "moodDistribution",
        "moodTrend", "weeklySummary", "scoreMapping",
    ):
        assert field in dashboard, f"dashboard.html reads {field!r}"

    assert dashboard["totalEntries"] == 4
    assert dashboard["mostCommonMood"] == "POSITIVE"
    # POSITIVE=2, POSITIVE=2, ANXIOUS=0, NEUTRAL=1 -> 5/4
    assert dashboard["averageScore"] == 1.25
    assert len(dashboard["moodDistribution"]) == 4


def test_dashboard_average_is_none_when_empty(journals):
    dashboard = analytics_service.build_dashboard("nobody", 7, repo=journals)

    # None, not 0: the UI shows a dash for "no data", and 0 would be a real score.
    assert dashboard["averageScore"] is None
    assert dashboard["totalEntries"] == 0
    assert dashboard["mostCommonMood"] is None


def test_dashboard_only_counts_the_requested_period(journals):
    today = utc_today()
    journals.put_entry(
        JournalEntry(user_id="u1", title="Old", content="x",
                     entry_date=(today - timedelta(days=40)).isoformat(), mood="NEGATIVE")
    )
    journals.put_entry(
        JournalEntry(user_id="u1", title="Recent", content="x",
                     entry_date=today.isoformat(), mood="POSITIVE")
    )

    assert analytics_service.build_dashboard("u1", 7, repo=journals)["totalEntries"] == 1
    assert analytics_service.build_dashboard("u1", 90, repo=journals)["totalEntries"] == 2


# ---------------------------------------------------------------------------
# Reflections
# ---------------------------------------------------------------------------


def test_reflection_uses_real_entry_data(journals, fake_gemini):
    seed_entries(journals, ["POSITIVE", "ANXIOUS", "POSITIVE"])

    reflection = reflection_service.create_reflection(
        user_id="u1", days=7, generated_by="manual", repo=journals
    )

    assert reflection.entry_count == 3
    assert reflection.generated_by == "manual"
    assert reflection.summary
    assert journals.reflections == [reflection]


def test_reflection_without_entries_is_refused(journals, fake_gemini):
    with pytest.raises(NoEntriesError):
        reflection_service.create_reflection(user_id="u1", days=7, repo=journals)


def test_scheduled_reflection_is_labelled_as_scheduled(journals, fake_gemini):
    seed_entries(journals, ["POSITIVE"])

    reflection = reflection_service.create_reflection(
        user_id="u1", days=7, generated_by="scheduled", repo=journals
    )

    assert reflection.generated_by == "scheduled"
    assert reflection.to_api()["disclaimer"]


def test_reflection_never_leaks_journal_text_to_gemini(journals, fake_gemini, monkeypatch):
    """Only aggregates and titles are sent, never entry bodies."""
    journals.put_entry(
        JournalEntry(
            user_id="u1", title="Tuesday", content="A very private confession.",
            entry_date=utc_today().isoformat(), mood="NEUTRAL",
        )
    )

    captured = {}
    from services import gemini_service

    def capture(period_label: str, summary_data: str) -> str:
        captured["data"] = summary_data
        return "ok"

    monkeypatch.setattr(gemini_service, "generate_reflection", capture)
    reflection_service.create_reflection(user_id="u1", days=7, repo=journals)

    assert "A very private confession." not in captured["data"]
    assert "Total entries: 1" in captured["data"]

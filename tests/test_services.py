"""Service-layer tests.

These cover the business rules that run inside Lambda: authentication,
journal CRUD, dashboard aggregation and reflection generation. Storage is a
stub repository and Gemini is patched, so no AWS or network access is needed.
"""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# Gemini retry policy
# ---------------------------------------------------------------------------


def _record_models(monkeypatch, behaviour):
    """Replace the HTTP call and record which model each attempt used.

    `behaviour` maps a model name to the exception it should raise, or to the
    text it should return.
    """
    from services import gemini_service

    used = []

    def _fake(prompt, json_output=False, model=None):
        used.append(model)
        outcome = behaviour(model)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(gemini_service, "_generate", _fake)
    monkeypatch.setattr(gemini_service, "RETRY_BACKOFF_SECONDS", (0, 0, 0))
    monkeypatch.setenv("GEMINI_MODELS", "model-a,model-b,model-c")
    return used


@pytest.mark.parametrize(
    "raw",
    [
        "model-a,model-b",
        "model-a\\,model-b",          # commas escaped for --parameter-overrides
        " model-a , model-b ",        # stray whitespace
    ],
    ids=["plain", "escaped-commas", "whitespace"],
)
def test_model_list_survives_shell_and_cloudformation_quoting(monkeypatch, raw):
    """A stray backslash would become part of the name and 404 every call."""
    from services import gemini_service

    monkeypatch.setenv("GEMINI_MODELS", raw)

    assert gemini_service.model_sequence() == ["model-a", "model-b"]


def test_a_busy_model_is_skipped_for_the_next_one(monkeypatch):
    """503 on one model must not end the attempt - other models have capacity."""
    from services import gemini_service

    good = json.dumps({"mood": "POSITIVE", "confidence": 0.9, "shortReason": "ok"})
    used = _record_models(
        monkeypatch,
        lambda m: good
        if m == "model-b"
        else gemini_service.GeminiError("busy", status_code=503),
    )

    result = gemini_service.classify_mood("anything")

    assert used == ["model-a", "model-b"], "it should move on rather than retry model-a"
    assert result.mood == "POSITIVE"
    assert result.fallback is False


def test_an_exhausted_model_is_not_asked_twice(monkeypatch):
    """429 means that model's daily allowance is gone; the others still have theirs."""
    from services import gemini_service

    good = json.dumps({"mood": "NEUTRAL", "confidence": 0.7, "shortReason": "ok"})
    used = _record_models(
        monkeypatch,
        lambda m: good
        if m == "model-c"
        else gemini_service.GeminiError("quota exceeded", status_code=429),
    )

    result = gemini_service.classify_mood("anything")

    assert used == ["model-a", "model-b", "model-c"]
    assert len(used) == len(set(used)), "an exhausted model must not be asked again"
    assert result.fallback is False


def test_every_model_failing_falls_back_without_raising(monkeypatch):
    from services import gemini_service

    used = _record_models(
        monkeypatch, lambda m: gemini_service.GeminiError("busy", status_code=503)
    )

    result = gemini_service.classify_mood("anything")

    assert used == ["model-a", "model-b", "model-c"]
    assert result.fallback is True, "the entry is still saved, marked unclassified"


def test_a_writer_ahead_of_utc_can_record_and_see_todays_entry(journals, fake_gemini):
    """Someone east of Greenwich has a local date a day ahead of UTC.

    Their "today" must be accepted rather than rejected as a future date, and
    it must appear on their own dashboard immediately - not once UTC catches up
    some hours later.
    """
    local_today = (utc_today() + timedelta(days=1)).isoformat()

    entry = journal_service.create_entry(
        user_id="u1", title="After midnight", content="Still today where I am.",
        entry_date=local_today, repo=journals,
    )
    assert entry.entry_date == local_today

    dashboard = analytics_service.build_dashboard("u1", 7, repo=journals)
    assert dashboard["totalEntries"] == 1, "the entry must not be hidden until UTC rolls over"


def test_a_genuinely_future_date_is_still_refused(journals):
    """One day of slack for timezones; two days is someone inventing the future."""
    from utils.validation import ValidationError, validate_entry_date

    with pytest.raises(ValidationError):
        validate_entry_date((utc_today() + timedelta(days=2)).isoformat())


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

"""Lambda handler tests.

These cover the HTTP layer that only exists on AWS: reading identity from the
authorizer context, forwarding query parameters, and returning the right status
codes. Repositories are patched onto each handler module, so no AWS is touched.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from tests.conftest import api_event
from handlers import get_dashboard, jwt_authorizer, list_entries
from models.journal_entry import JournalEntry
from services import auth_service


def body_of(response: dict) -> dict:
    return json.loads(response["body"])


# ---------------------------------------------------------------------------
# Identity comes from the authorizer, never from the caller
# ---------------------------------------------------------------------------


def test_handler_rejects_a_request_with_no_authorizer_context(journals, monkeypatch):
    monkeypatch.setattr(list_entries, "JournalRepository", lambda: journals)

    response = list_entries.lambda_handler(api_event(user_id=None), None)

    assert response["statusCode"] == 401


def test_handler_uses_the_authorizer_user_not_a_query_parameter(journals, monkeypatch):
    """A caller must not be able to read another user's entries by asking."""
    monkeypatch.setattr(list_entries, "JournalRepository", lambda: journals)
    journals.put_entry(
        JournalEntry(user_id="alice", title="Alice private", content="hers",
                     entry_date=date.today().isoformat(), mood="POSITIVE")
    )

    response = list_entries.lambda_handler(
        api_event(user_id="bob", query={"userId": "alice"}), None
    )

    assert response["statusCode"] == 200
    assert body_of(response)["entries"] == []


# ---------------------------------------------------------------------------
# Query parameters reach the repository
# ---------------------------------------------------------------------------


def seed(journals, user_id="user-1"):
    today = date.today().isoformat()
    for title, content, mood in [
        ("Deadline looming", "Worried about the deadline.", "ANXIOUS"),
        ("Great day", "Felt happy and proud.", "POSITIVE"),
        ("Ordinary", "Nothing much happened.", "NEUTRAL"),
    ]:
        journals.put_entry(
            JournalEntry(user_id=user_id, title=title, content=content,
                         entry_date=today, mood=mood, confidence=0.9)
        )


def test_search_parameter_is_forwarded(journals, monkeypatch):
    """The history page sends ?search=; it must reach the repository."""
    monkeypatch.setattr(list_entries, "JournalRepository", lambda: journals)
    seed(journals)

    response = list_entries.lambda_handler(api_event(query={"search": "deadline"}), None)

    entries = body_of(response)["entries"]
    assert len(entries) == 1
    assert entries[0]["title"] == "Deadline looming"


def test_search_is_case_insensitive(journals, monkeypatch):
    monkeypatch.setattr(list_entries, "JournalRepository", lambda: journals)
    seed(journals)

    response = list_entries.lambda_handler(api_event(query={"search": "DEADLINE"}), None)

    assert len(body_of(response)["entries"]) == 1


def test_mood_filter_is_applied(journals, monkeypatch):
    monkeypatch.setattr(list_entries, "JournalRepository", lambda: journals)
    seed(journals)

    response = list_entries.lambda_handler(api_event(query={"mood": "positive"}), None)

    entries = body_of(response)["entries"]
    assert len(entries) == 1
    assert entries[0]["mood"] == "POSITIVE"


def test_invalid_mood_is_a_400(journals, monkeypatch):
    monkeypatch.setattr(list_entries, "JournalRepository", lambda: journals)

    response = list_entries.lambda_handler(api_event(query={"mood": "ecstatic"}), None)

    assert response["statusCode"] == 400


def test_dashboard_handler_returns_the_frontend_shape(journals, monkeypatch):
    # get_dashboard calls build_dashboard without a repo, so the default is
    # constructed inside analytics_service - that is the name to patch.
    from services import analytics_service

    monkeypatch.setattr(analytics_service, "JournalRepository", lambda: journals)
    seed(journals)

    response = get_dashboard.lambda_handler(api_event(query={"period": "7d"}), None)

    assert response["statusCode"] == 200
    dashboard = body_of(response)["dashboard"]
    assert dashboard["totalEntries"] == 3
    assert dashboard["averageScore"] is not None


# ---------------------------------------------------------------------------
# JWT authorizer
# ---------------------------------------------------------------------------


def authorizer_event(token: str | None) -> dict:
    event: dict = {"methodArn": "arn:aws:execute-api:us-east-1:1:api/dev/GET/entries"}
    if token is not None:
        event["headers"] = {"Authorization": f"Bearer {token}"}
    return event


def effect_of(policy: dict) -> str:
    return policy["policyDocument"]["Statement"][0]["Effect"]


def test_authorizer_allows_a_valid_token(users):
    user = auth_service.register("alice", "Password123", repo=users)
    token, _ = auth_service.issue_token(user)

    policy = jwt_authorizer.lambda_handler(authorizer_event(token), None)

    assert effect_of(policy) == "Allow"
    # The handler reads userId from here, so it must be present.
    assert policy["context"]["userId"] == user.user_id


@pytest.mark.parametrize(
    "token", [None, "not-a-token", ""], ids=["missing", "garbage", "empty"]
)
def test_authorizer_denies_bad_tokens(token):
    policy = jwt_authorizer.lambda_handler(authorizer_event(token), None)

    assert effect_of(policy) == "Deny"
    assert "context" not in policy


def test_authorizer_denies_a_token_signed_with_another_secret(users, monkeypatch):
    """A token minted with a different secret must not be accepted."""
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"sub": "attacker", "username": "mallory"},
        "a-different-secret-that-is-also-32-bytes-long",
        "HS256",
    )

    policy = jwt_authorizer.lambda_handler(authorizer_event(forged), None)

    assert effect_of(policy) == "Deny"

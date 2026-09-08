"""End-to-end walkthrough of every feature, through the real Lambda handlers.

Each test drives the same handler code that API Gateway invokes, in the order a
user would: register, sign in, write, read back, edit, search, chart, reflect,
change password, sign in again. Repositories are stubs and Gemini is patched, so
this runs offline - but every line of handler, service, model and validation
code in the path is the deployed code.

This is the pre-deployment check: if something here fails, it would have failed
on AWS too.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from handlers import (
    change_password,
    create_entry,
    create_reflection,
    delete_entry,
    get_dashboard,
    get_entry,
    get_me,
    health,
    list_entries,
    list_reflections,
    login,
    register,
    scheduled_reflection,
    update_entry,
)
from services import analytics_service, auth_service, journal_service, reflection_service

from tests.conftest import api_event, utc_today

USERNAME = "e2e.user"
PASSWORD = "Password123"
NEW_PASSWORD = "NewPassword456"


def body_of(response: dict) -> dict:
    return json.loads(response["body"])


def http_event(user_id=None, body=None, query=None, path=None, method="POST") -> dict:
    return api_event(
        user_id=user_id,
        body=json.dumps(body) if body is not None else None,
        query=query,
        path=path,
        method=method,
    )


@pytest.fixture
def wired(users, journals, fake_gemini, monkeypatch):
    """Point every handler and service at the stub repositories."""
    for module in (register, login, get_me, change_password):
        if hasattr(module, "UserRepository"):
            monkeypatch.setattr(module, "UserRepository", lambda: users)
    for module in (
        create_entry, list_entries, get_entry, update_entry,
        delete_entry, create_reflection, list_reflections,
    ):
        if hasattr(module, "JournalRepository"):
            monkeypatch.setattr(module, "JournalRepository", lambda: journals)

    # Services construct their own default when a handler passes no repo.
    monkeypatch.setattr(auth_service, "UserRepository", lambda: users)
    monkeypatch.setattr(journal_service, "JournalRepository", lambda: journals)
    monkeypatch.setattr(analytics_service, "JournalRepository", lambda: journals)
    monkeypatch.setattr(reflection_service, "JournalRepository", lambda: journals)
    monkeypatch.setattr(scheduled_reflection, "boto3", _FakeBoto3(users))

    return {"users": users, "journals": journals, "gemini": fake_gemini}


class _FakeBoto3:
    """Stands in for boto3 in scheduled_reflection, which scans the users table."""

    def __init__(self, users):
        self._users = users

    def resource(self, _name):
        return self

    def Table(self, _name):  # noqa: N802 - mirrors the boto3 API
        return self

    def scan(self, **_kwargs):
        return {"Items": [{"userId": uid} for uid in self._users.by_id]}


# ---------------------------------------------------------------------------
# The full user journey
# ---------------------------------------------------------------------------


def test_complete_user_journey(wired):
    """Register through to signing in again with a changed password."""

    # -- health, unauthenticated ------------------------------------------
    assert body_of(health.lambda_handler(http_event(method="GET"), None))["status"] == "healthy"

    # -- register ----------------------------------------------------------
    response = register.lambda_handler(
        http_event(body={"username": USERNAME, "password": PASSWORD}), None
    )
    assert response["statusCode"] == 201, response["body"]
    registered = body_of(response)
    token = registered["token"]
    assert token
    assert "passwordHash" not in json.dumps(registered), "password hash must never reach the browser"

    user_id = auth_service.verify_token(token)["sub"]

    # -- sign in -----------------------------------------------------------
    response = login.lambda_handler(
        http_event(body={"username": USERNAME, "password": PASSWORD}), None
    )
    assert response["statusCode"] == 200
    assert body_of(response)["token"]

    # -- current user ------------------------------------------------------
    response = get_me.lambda_handler(http_event(user_id=user_id, method="GET"), None)
    assert response["statusCode"] == 200
    assert body_of(response)["user"]["username"] == USERNAME

    # -- write entries across several days ---------------------------------
    today = utc_today()
    written = []
    for days_ago, mood, title, content in [
        (4, "POSITIVE", "Good day", "Felt happy and proud today."),
        (3, "ANXIOUS", "Deadline looming", "Worried about the deadline."),
        (2, "NEUTRAL", "Ordinary", "Nothing much happened."),
        (1, "POSITIVE", "Better", "Excited about the progress."),
    ]:
        wired["gemini"]["mood"] = mood
        response = create_entry.lambda_handler(
            http_event(
                user_id=user_id,
                body={
                    "title": title,
                    "content": content,
                    "entryDate": (today - timedelta(days=days_ago)).isoformat(),
                },
            ),
            None,
        )
        assert response["statusCode"] == 201, response["body"]
        entry = body_of(response)["entry"]
        assert entry["mood"] == mood
        written.append(entry)

    # -- history -----------------------------------------------------------
    response = list_entries.lambda_handler(http_event(user_id=user_id, method="GET"), None)
    assert response["statusCode"] == 200
    assert body_of(response)["count"] == 4

    # -- search ------------------------------------------------------------
    response = list_entries.lambda_handler(
        http_event(user_id=user_id, query={"search": "DEADLINE"}, method="GET"), None
    )
    assert [e["title"] for e in body_of(response)["entries"]] == ["Deadline looming"]

    # -- filter by mood ----------------------------------------------------
    response = list_entries.lambda_handler(
        http_event(user_id=user_id, query={"mood": "POSITIVE"}, method="GET"), None
    )
    assert body_of(response)["count"] == 2

    # -- open one entry ----------------------------------------------------
    target = written[2]
    response = get_entry.lambda_handler(
        http_event(user_id=user_id, path={"entryId": target["entryId"]}, method="GET"), None
    )
    assert response["statusCode"] == 200
    assert body_of(response)["entry"]["title"] == "Ordinary"

    # -- edit it, and confirm it is re-classified --------------------------
    wired["gemini"]["mood"] = "NEGATIVE"
    response = update_entry.lambda_handler(
        http_event(
            user_id=user_id,
            path={"entryId": target["entryId"]},
            body={
                "title": "Actually rough",
                "content": "Thinking about it more, it was a hard day.",
                "entryDate": target["entryDate"],
            },
            method="PUT",
        ),
        None,
    )
    assert response["statusCode"] == 200, response["body"]
    updated = body_of(response)["entry"]
    assert updated["mood"] == "NEGATIVE"
    assert updated["entryId"] == target["entryId"]

    # -- dashboard ---------------------------------------------------------
    response = get_dashboard.lambda_handler(
        http_event(user_id=user_id, query={"period": "7d"}, method="GET"), None
    )
    assert response["statusCode"] == 200
    dashboard = body_of(response)["dashboard"]
    assert dashboard["totalEntries"] == 4
    assert dashboard["averageScore"] is not None, "the Average Score tile would read NaN"
    assert dashboard["mostCommonMood"] == "POSITIVE"
    assert len(dashboard["moodDistribution"]) == 4
    assert dashboard["moodTrend"]
    assert dashboard["weeklySummary"]

    # -- generate a reflection on request ----------------------------------
    response = create_reflection.lambda_handler(
        http_event(user_id=user_id, body={"period": "7d"}), None
    )
    assert response["statusCode"] == 201, response["body"]
    reflection = body_of(response)["reflection"]
    assert reflection["entryCount"] == 4
    assert reflection["generatedBy"] == "manual"
    assert reflection["summary"]
    assert reflection["disclaimer"]

    # -- list reflections --------------------------------------------------
    response = list_reflections.lambda_handler(http_event(user_id=user_id, method="GET"), None)
    assert response["statusCode"] == 200
    assert body_of(response)["count"] == 1

    # -- change password ---------------------------------------------------
    response = change_password.lambda_handler(
        http_event(
            user_id=user_id,
            body={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
        ),
        None,
    )
    assert response["statusCode"] == 200, response["body"]

    # -- old password refused, new one works -------------------------------
    assert login.lambda_handler(
        http_event(body={"username": USERNAME, "password": PASSWORD}), None
    )["statusCode"] == 401
    assert login.lambda_handler(
        http_event(body={"username": USERNAME, "password": NEW_PASSWORD}), None
    )["statusCode"] == 200

    # -- delete an entry ---------------------------------------------------
    response = delete_entry.lambda_handler(
        http_event(user_id=user_id, path={"entryId": target["entryId"]}, method="DELETE"), None
    )
    assert response["statusCode"] in (200, 204)
    assert get_entry.lambda_handler(
        http_event(user_id=user_id, path={"entryId": target["entryId"]}, method="GET"), None
    )["statusCode"] == 404


# ---------------------------------------------------------------------------
# The automatic weekly reflection
# ---------------------------------------------------------------------------


def test_weekly_reflection_runs_without_anyone_pressing_a_button(wired):
    """EventBridge invokes this directly; no HTTP request is involved."""
    user = auth_service.register(USERNAME, PASSWORD, repo=wired["users"])

    today = utc_today()
    for days_ago in range(4):
        journal_service.create_entry(
            user_id=user.user_id,
            title=f"Day {days_ago}",
            content="Something happened today.",
            entry_date=(today - timedelta(days=days_ago)).isoformat(),
            repo=wired["journals"],
        )

    result = scheduled_reflection.lambda_handler({"source": "aws.events"}, None)

    assert result == {"generated": 1, "skipped": 0, "failed": 0}

    stored = wired["journals"].reflections
    assert len(stored) == 1
    # The frontend badge reads this to show "Automatic (weekly)".
    assert stored[0].generated_by == "scheduled"
    assert stored[0].entry_count == 4


def test_weekly_reflection_skips_users_with_no_entries(wired):
    auth_service.register(USERNAME, PASSWORD, repo=wired["users"])

    result = scheduled_reflection.lambda_handler({"source": "aws.events"}, None)

    assert result == {"generated": 0, "skipped": 1, "failed": 0}
    assert wired["journals"].reflections == []


def test_change_password_checks_the_current_one_before_anything_else(wired):
    """A wrong current password must be reported as such.

    Even when the new password is also invalid: telling someone their new
    password is too short implies the current one was accepted, which is
    misleading and hides the real reason the change failed.
    """
    user = auth_service.register(USERNAME, PASSWORD, repo=wired["users"])

    # Wrong current password AND a new one that fails validation.
    response = change_password.lambda_handler(
        http_event(
            user_id=user.user_id,
            body={"currentPassword": "WrongPassword9", "newPassword": "short1"},
        ),
        None,
    )
    assert response["statusCode"] == 401, "the credential decides the outcome, not the format"
    assert "current password" in body_of(response)["error"]["message"].lower()
    # Not UNAUTHORIZED: the frontend signs the user out when it sees that code,
    # so a mistyped current password would end a perfectly valid session.
    assert body_of(response)["error"]["code"] == "INVALID_CURRENT_PASSWORD"

    # Correct current password, invalid new one -> now the format matters.
    response = change_password.lambda_handler(
        http_event(
            user_id=user.user_id,
            body={"currentPassword": PASSWORD, "newPassword": "short1"},
        ),
        None,
    )
    assert response["statusCode"] == 400
    assert "8 characters" in body_of(response)["error"]["message"]

    # Neither attempt changed anything.
    assert auth_service.login(USERNAME, PASSWORD, repo=wired["users"])


def test_reflection_with_no_entries_returns_a_clear_message(wired):
    """The user should be told why, not shown a 500."""
    user = auth_service.register(USERNAME, PASSWORD, repo=wired["users"])

    response = create_reflection.lambda_handler(
        http_event(user_id=user.user_id, body={"period": "7d"}), None
    )

    assert response["statusCode"] == 400
    assert "no entries" in body_of(response)["error"]["message"].lower()


def test_reflection_reports_a_clean_error_when_gemini_fails(wired):
    """Gemini's raw error body must not reach the browser."""
    user = auth_service.register(USERNAME, PASSWORD, repo=wired["users"])
    journal_service.create_entry(
        user_id=user.user_id, title="Today", content="A day.",
        entry_date=utc_today().isoformat(), repo=wired["journals"],
    )
    wired["gemini"]["fail"] = True

    response = create_reflection.lambda_handler(
        http_event(user_id=user.user_id, body={"period": "7d"}), None
    )

    assert response["statusCode"] == 502
    message = body_of(response)["error"]["message"]
    assert "try again later" in message.lower()
    assert "quota" not in message.lower(), "Gemini's raw error must not be echoed to the browser"

"""Athena service and /analytics/athena handler tests.

A fake Athena client stands in for boto3, so these run without AWS. They pin
down what the dashboard relies on: every query is scoped to the caller, the
repeated daily exports are de-duplicated, and failures come back as readable
errors instead of an API Gateway timeout.
"""

from __future__ import annotations

import json

import pytest
from handlers import run_athena_query
from services import athena_service


class FakeAthenaClient:
    """Records calls and replays a scripted sequence of query states."""

    def __init__(self, states=("SUCCEEDED",), rows=None):
        self.states = list(states)
        self.rows = rows or []
        self.started: list[dict] = []
        self.stopped: list[str] = []

    def start_query_execution(self, **kwargs):
        self.started.append(kwargs)
        return {"QueryExecutionId": "exec-1"}

    # Parameter names mirror boto3's keyword arguments, hence the noqa.
    def get_query_execution(self, QueryExecutionId):  # noqa: N803
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"QueryExecution": {"Status": {"State": state, "StateChangeReason": "boom"}}}

    def get_query_results(self, QueryExecutionId, MaxResults):  # noqa: N803
        return {"ResultSet": {"Rows": self.rows}}

    def stop_query_execution(self, QueryExecutionId):  # noqa: N803
        self.stopped.append(QueryExecutionId)


def athena_rows(header, *values):
    as_row = lambda cells: {"Data": [{"VarCharValue": c} for c in cells]}  # noqa: E731
    return [as_row(header), *(as_row(v) for v in values)]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(athena_service.time, "sleep", lambda _seconds: None)


# ---------------------------------------------------------------------------
# Query text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query_name", athena_service.available_queries())
def test_every_query_is_scoped_to_the_caller_and_deduplicated(query_name):
    """One placeholder only, and counts come from the latest export of each entry."""
    client = FakeAthenaClient()

    athena_service.run_query(query_name, "user-1", client=client)

    started = client.started[0]
    assert started["ExecutionParameters"] == ["user-1"]
    assert started["QueryString"].count("?") == 1
    assert "export_rank = 1" in started["QueryString"]
    assert "{db}" not in started["QueryString"]


def test_unknown_query_name_never_reaches_athena():
    client = FakeAthenaClient()

    with pytest.raises(ValueError):
        athena_service.run_query("DROP TABLE journal_entries", "user-1", client=client)

    assert client.started == []


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def test_results_are_returned_as_dicts_keyed_by_column():
    client = FakeAthenaClient(
        states=("RUNNING", "SUCCEEDED"),
        rows=athena_rows(["entrydate", "entry_count"], ["2026-09-14", "2"], ["2026-09-13", "1"]),
    )

    result = athena_service.run_query("entry_count_by_day", "user-1", client=client)

    assert result["rowCount"] == 2
    assert result["rows"][0] == {"entrydate": "2026-09-14", "entry_count": "2"}


def test_failed_query_raises_athena_error():
    client = FakeAthenaClient(states=("FAILED",))

    with pytest.raises(athena_service.AthenaError):
        athena_service.run_query("entry_count_by_day", "user-1", client=client)


def test_slow_query_is_stopped_before_api_gateway_gives_up():
    client = FakeAthenaClient(states=("RUNNING",))

    with pytest.raises(athena_service.AthenaTimeoutError):
        athena_service.run_query("entry_count_by_day", "user-1", client=client)

    assert client.stopped == ["exec-1"]
    # API Gateway's integration timeout is 29 seconds.
    assert athena_service._MAX_POLL_ATTEMPTS * athena_service._POLL_INTERVAL_SECONDS < 29


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def event(user_id="user-1", query=None):
    from tests.conftest import api_event

    return api_event(user_id=user_id, query=query)


def test_handler_requires_a_query_name():
    response = run_athena_query.lambda_handler(event(query=None), None)

    assert response["statusCode"] == 400


def test_handler_runs_the_query_for_the_authorizer_user(monkeypatch):
    calls = []

    def fake_run_query(query_name, user_id):
        calls.append((query_name, user_id))
        return {"queryName": query_name, "executionId": "exec-1", "rowCount": 0, "rows": []}

    monkeypatch.setattr(athena_service, "run_query", fake_run_query)

    response = run_athena_query.lambda_handler(
        event(user_id="bob", query={"query": "mood_count_by_week", "userId": "alice"}), None
    )

    assert response["statusCode"] == 200
    assert calls == [("mood_count_by_week", "bob")]
    assert json.loads(response["body"])["result"]["queryName"] == "mood_count_by_week"


def test_handler_reports_a_timeout_as_504(monkeypatch):
    def slow(query_name, user_id):
        raise athena_service.AthenaTimeoutError("too slow")

    monkeypatch.setattr(athena_service, "run_query", slow)

    response = run_athena_query.lambda_handler(event(query={"query": "entry_count_by_day"}), None)

    assert response["statusCode"] == 504

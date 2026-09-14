"""Athena query execution.

Only the named queries below can run. The frontend sends a query name, never
SQL, so there is no way to inject arbitrary statements through the API.

Athena is asynchronous: start the query, poll until it finishes, then fetch
results. Polling happens inside the Lambda with a hard cap, so a slow query
returns 504 rather than running until the Lambda times out.
"""

import os
import time
from typing import Any

import boto3
from utils.logging_config import get_logger

logger = get_logger(__name__)

ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "moodjournal")
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "primary")
OUTPUT_LOCATION = os.environ.get("ATHENA_OUTPUT_LOCATION", "")

_POLL_INTERVAL_SECONDS = 1.0
# API Gateway abandons an integration after 29 seconds, and that timeout
# reaches the browser without CORS headers - an opaque network error. Giving up
# well before it means the dashboard receives a readable 504 instead.
_MAX_POLL_ATTEMPTS = 20
_MAX_ROWS = 200

TABLE = "journal_entries"

# Every daily export rewrites the last 90 days of entries into a new
# day= partition, so one entry appears in up to 90 partitions. Counting the
# table directly would multiply every figure. This keeps only the most recent
# export of each entry, which also picks up an edited entry's latest mood.
#
# It is the only place the user id parameter appears, so every query below
# stays scoped to the caller.
_LATEST_ENTRIES = f"""
    latest AS (
        SELECT entryid, entrydate, mood, moodscore,
               row_number() OVER (
                   PARTITION BY entryid ORDER BY year DESC, month DESC, day DESC
               ) AS export_rank
        FROM {{db}}.{TABLE}
        WHERE userid = ?
    ),
    entries AS (
        SELECT entryid, entrydate, mood, moodscore FROM latest WHERE export_rank = 1
    )
"""

# Named queries. {db} is filled in from the environment, never from user input.
QUERIES: dict[str, str] = {
    "mood_count_by_week": f"""
        WITH {_LATEST_ENTRIES}
        SELECT cast(date_trunc('week', date_parse(entrydate, '%Y-%m-%d')) AS date)
                   AS week_start,
               count(*) AS entry_count,
               round(avg(cast(moodscore AS double)), 2) AS avg_mood_score,
               count_if(mood = 'POSITIVE') AS positive,
               count_if(mood = 'NEUTRAL') AS neutral,
               count_if(mood = 'ANXIOUS') AS anxious,
               count_if(mood = 'NEGATIVE') AS negative
        FROM entries
        GROUP BY 1
        ORDER BY week_start DESC
        LIMIT {_MAX_ROWS}
    """,
    "most_common_mood_by_month": f"""
        WITH {_LATEST_ENTRIES},
        monthly AS (
            SELECT substr(entrydate, 1, 7) AS month,
                   mood,
                   count(*) AS mood_count,
                   sum(count(*)) OVER (PARTITION BY substr(entrydate, 1, 7)) AS entry_count,
                   row_number() OVER (
                       PARTITION BY substr(entrydate, 1, 7) ORDER BY count(*) DESC, mood
                   ) AS rnk
            FROM entries
            GROUP BY 1, 2
        )
        SELECT month, mood AS most_common_mood, mood_count, entry_count
        FROM monthly
        WHERE rnk = 1
        ORDER BY month DESC
        LIMIT {_MAX_ROWS}
    """,
    "average_mood_score_over_time": f"""
        WITH {_LATEST_ENTRIES}
        SELECT entrydate,
               round(avg(cast(moodscore AS double)), 2) AS avg_mood_score,
               count(*) AS entry_count
        FROM entries
        GROUP BY entrydate
        ORDER BY entrydate DESC
        LIMIT {_MAX_ROWS}
    """,
    "entry_count_by_day": f"""
        WITH {_LATEST_ENTRIES}
        SELECT entrydate, count(*) AS entry_count
        FROM entries
        GROUP BY entrydate
        ORDER BY entrydate DESC
        LIMIT {_MAX_ROWS}
    """,
}


class AthenaError(Exception):
    """Raised when a query fails."""


class AthenaTimeoutError(Exception):
    """Raised when a query does not finish within the polling window."""


def available_queries() -> list[str]:
    """Names the API will accept."""
    return sorted(QUERIES)


def run_query(
    query_name: str, user_id: str, client: Any = None
) -> dict[str, Any]:
    """Run a named query and return its results.

    The user id is passed as an execution parameter rather than interpolated
    into the SQL string.
    """
    if query_name not in QUERIES:
        raise ValueError(f"Unknown query: {query_name}")

    client = client or boto3.client("athena")
    sql = QUERIES[query_name].format(db=ATHENA_DATABASE).strip()

    start = client.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": ATHENA_DATABASE},
        ResultConfiguration={"OutputLocation": OUTPUT_LOCATION},
        WorkGroup=ATHENA_WORKGROUP,
        ExecutionParameters=[user_id],
    )
    execution_id = start["QueryExecutionId"]
    logger.info("Started Athena query %s (%s)", query_name, execution_id)

    _wait_for_completion(client, execution_id)
    rows = _fetch_results(client, execution_id)

    return {
        "queryName": query_name,
        "executionId": execution_id,
        "rowCount": len(rows),
        "rows": rows,
    }


def _wait_for_completion(client: Any, execution_id: str) -> None:
    """Poll until the query succeeds, fails, or the cap is reached."""
    for _ in range(_MAX_POLL_ATTEMPTS):
        response = client.get_query_execution(QueryExecutionId=execution_id)
        status = response["QueryExecution"]["Status"]
        state = status["State"]

        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            reason = status.get("StateChangeReason", "No reason given.")
            logger.error("Athena query %s %s: %s", execution_id, state, reason)
            raise AthenaError(f"Query {state.lower()}.")

        time.sleep(_POLL_INTERVAL_SECONDS)

    # Stop the query so it does not keep consuming scan quota after we give up.
    try:
        client.stop_query_execution(QueryExecutionId=execution_id)
    except Exception as exc:  # noqa: BLE001 - best effort cleanup
        logger.warning("Could not stop query %s: %s", execution_id, exc)

    raise AthenaTimeoutError("The analytics query took too long to complete.")


def _fetch_results(client: Any, execution_id: str) -> list[dict[str, str]]:
    """Convert the Athena result set into a list of dicts.

    The first row of an Athena result is the column header.
    """
    response = client.get_query_results(
        QueryExecutionId=execution_id, MaxResults=_MAX_ROWS + 1
    )
    result_rows = response["ResultSet"]["Rows"]
    if not result_rows:
        return []

    headers = [c.get("VarCharValue", "") for c in result_rows[0]["Data"]]
    rows = []
    for row in result_rows[1:]:
        values = [c.get("VarCharValue") for c in row["Data"]]
        rows.append(dict(zip(headers, values, strict=False)))
    return rows

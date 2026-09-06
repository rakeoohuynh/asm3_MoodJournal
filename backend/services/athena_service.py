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
_MAX_POLL_ATTEMPTS = 30
_MAX_ROWS = 200

TABLE = "journal_entries"

# Named queries. {db} is filled in from the environment, never from user input.
QUERIES: dict[str, str] = {
    "mood_count_by_week": f"""
        SELECT date_trunc('week', date_parse(entrydate, '%Y-%m-%d')) AS week_start,
               mood,
               count(*) AS entry_count
        FROM {{db}}.{TABLE}
        WHERE userid = ?
        GROUP BY 1, 2
        ORDER BY week_start DESC, mood
        LIMIT {_MAX_ROWS}
    """,
    "most_common_mood_by_month": f"""
        WITH monthly AS (
            SELECT substr(entrydate, 1, 7) AS month,
                   mood,
                   count(*) AS entry_count,
                   row_number() OVER (
                       PARTITION BY substr(entrydate, 1, 7) ORDER BY count(*) DESC
                   ) AS rnk
            FROM {{db}}.{TABLE}
            WHERE userid = ?
            GROUP BY 1, 2
        )
        SELECT month, mood AS most_common_mood, entry_count
        FROM monthly
        WHERE rnk = 1
        ORDER BY month DESC
        LIMIT {_MAX_ROWS}
    """,
    "average_mood_score_over_time": f"""
        SELECT entrydate,
               round(avg(cast(moodscore AS double)), 2) AS avg_mood_score,
               count(*) AS entry_count
        FROM {{db}}.{TABLE}
        WHERE userid = ?
        GROUP BY entrydate
        ORDER BY entrydate DESC
        LIMIT {_MAX_ROWS}
    """,
    "entry_count_by_day": f"""
        SELECT entrydate, count(*) AS entry_count
        FROM {{db}}.{TABLE}
        WHERE userid = ?
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

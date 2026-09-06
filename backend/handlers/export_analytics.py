"""POST /analytics/export, and a daily EventBridge target.

Writes analytics records to S3 so Athena has something to query. Invoked two
ways: by the frontend for the signed-in user, or on a schedule for everyone.
"""

import os
from typing import Any

import boto3

from services import analytics_service
from utils import api_response
from utils.logging_config import get_logger
from utils.request_context import MissingIdentityError, get_user_id

logger = get_logger(__name__)

EXPORT_DAYS = 90
USERS_TABLE_NAME = os.environ.get("USERS_TABLE_NAME", "MoodJournalUsers")


def _is_scheduled(event: dict[str, Any]) -> bool:
    """EventBridge events carry a source; API Gateway events do not."""
    return event.get("source") == "aws.events" or "httpMethod" not in event


def _all_user_ids() -> list[str]:
    """Every registered user id, for the scheduled run."""
    table = boto3.resource("dynamodb").Table(USERS_TABLE_NAME)
    user_ids: list[str] = []
    start_key: dict[str, Any] | None = None

    while True:
        params: dict[str, Any] = {"ProjectionExpression": "userId"}
        if start_key:
            params["ExclusiveStartKey"] = start_key

        response = table.scan(**params)
        user_ids.extend(item["userId"] for item in response.get("Items", []))

        start_key = response.get("LastEvaluatedKey")
        if not start_key:
            return user_ids


def lambda_handler(event: dict[str, Any], context: Any) -> Any:
    if _is_scheduled(event):
        return _run_scheduled()
    return _run_for_request(event)


def _run_scheduled() -> dict[str, Any]:
    """Export analytics for every user."""
    total_records = 0
    failed = 0

    for user_id in _all_user_ids():
        try:
            result = analytics_service.export_to_s3(user_id, days=EXPORT_DAYS)
            total_records += result["exported"]
        except Exception:  # noqa: BLE001 - one bad user must not stop the rest
            logger.exception("Scheduled export failed for user %s", user_id)
            failed += 1

    logger.info("Scheduled export complete: %d records, %d failures", total_records, failed)
    return {"exported": total_records, "failed": failed}


def _run_for_request(event: dict[str, Any]) -> dict[str, Any]:
    """Export analytics for the signed-in user only."""
    try:
        user_id = get_user_id(event)
    except MissingIdentityError:
        return api_response.unauthorized()

    try:
        result = analytics_service.export_to_s3(user_id, days=EXPORT_DAYS)
    except ValueError as exc:
        return api_response.validation_error(str(exc))
    except Exception:
        logger.exception("Export failed for user %s", user_id)
        return api_response.internal_error()

    return api_response.success(
        {"exported": result["exported"], "location": result["location"]}
    )

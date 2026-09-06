"""EventBridge target - generate weekly reflections without a user request.

This is what makes the reflection feature run automatically rather than
depending on someone pressing a button in the AWS Console.

Runs for every registered user. Users with no entries in the period are
skipped rather than treated as errors.
"""

import os
from typing import Any

import boto3

from services import reflection_service
from services.reflection_service import NoEntriesError
from utils.logging_config import get_logger

logger = get_logger(__name__)

REFLECTION_DAYS = 7
USERS_TABLE_NAME = os.environ.get("USERS_TABLE_NAME", "MoodJournalUsers")


def _all_user_ids() -> list[str]:
    """Read every registered user id.

    A Scan is acceptable here: this runs once a week off a schedule, not on a
    user request, and the users table is small.
    """
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


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Generate a weekly reflection for each user that has entries."""
    generated = 0
    skipped = 0
    failed = 0

    for user_id in _all_user_ids():
        try:
            reflection_service.create_reflection(
                user_id=user_id, days=REFLECTION_DAYS, generated_by="scheduled"
            )
            generated += 1
        except NoEntriesError:
            skipped += 1
        except Exception:  # noqa: BLE001 - one bad user must not stop the rest
            logger.exception("Scheduled reflection failed for user %s", user_id)
            failed += 1

    logger.info(
        "Scheduled reflections complete: %d generated, %d skipped, %d failed",
        generated,
        skipped,
        failed,
    )
    return {"generated": generated, "skipped": skipped, "failed": failed}

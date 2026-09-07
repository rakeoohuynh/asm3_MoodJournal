"""GET /entries - list entries with optional filters and pagination."""

from typing import Any

from models.journal_entry import VALID_MOODS
from repositories.journal_repository import JournalRepository
from utils import api_response
from utils.logging_config import get_logger
from utils.pagination import decode_token, encode_token
from utils.request_context import MissingIdentityError, get_user_id, query_params
from utils.validation import (
    ValidationError,
    validate_limit,
    validate_optional_date,
)

logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        user_id = get_user_id(event)
    except MissingIdentityError:
        return api_response.unauthorized()

    params = query_params(event)

    try:
        mood = params.get("mood")
        if mood and mood.upper() not in VALID_MOODS:
            allowed = ", ".join(VALID_MOODS)
            raise ValidationError(f"Mood must be one of: {allowed}.")

        start_date = validate_optional_date(params.get("startDate"), "startDate")
        end_date = validate_optional_date(params.get("endDate"), "endDate")
        limit = validate_limit(params.get("limit"))
        start_key = decode_token(params.get("nextToken"))
    except ValidationError as exc:
        return api_response.validation_error(str(exc))

    if start_date and end_date and start_date > end_date:
        return api_response.validation_error("startDate must be on or before endDate.")

    try:
        entries, last_key = JournalRepository().list_entries(
            user_id=user_id,
            mood=mood.upper() if mood else None,
            start_date=start_date,
            end_date=end_date,
            search=(params.get("search") or "")[:200] or None,
            limit=limit,
            start_key=start_key,
        )
    except Exception:
        logger.exception("Failed to list entries for user %s", user_id)
        return api_response.internal_error()

    return api_response.success(
        {
            "entries": [e.to_api() for e in entries],
            "count": len(entries),
            "nextToken": encode_token(last_key),
        }
    )

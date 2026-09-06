"""GET /reflections - list stored reflections, newest first."""

from typing import Any

from repositories.journal_repository import JournalRepository
from utils import api_response
from utils.logging_config import get_logger
from utils.pagination import decode_token, encode_token
from utils.request_context import MissingIdentityError, get_user_id, query_params
from utils.validation import ValidationError, validate_limit

logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        user_id = get_user_id(event)
    except MissingIdentityError:
        return api_response.unauthorized()

    params = query_params(event)

    try:
        limit = validate_limit(params.get("limit"))
        start_key = decode_token(params.get("nextToken"))
    except ValidationError as exc:
        return api_response.validation_error(str(exc))

    try:
        reflections, last_key = JournalRepository().list_reflections(
            user_id=user_id, limit=limit, start_key=start_key
        )
    except Exception:
        logger.exception("Failed to list reflections for user %s", user_id)
        return api_response.internal_error()

    return api_response.success(
        {
            "reflections": [r.to_api() for r in reflections],
            "count": len(reflections),
            "nextToken": encode_token(last_key),
        }
    )

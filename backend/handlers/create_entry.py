"""POST /entries - save a journal entry and classify its mood."""

from typing import Any

from services import journal_service
from utils import api_response
from utils.logging_config import get_logger
from utils.request_context import MissingIdentityError, get_user_id
from utils.validation import (
    ValidationError,
    validate_content,
    validate_entry_date,
    validate_title,
)

logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        user_id = get_user_id(event)
    except MissingIdentityError:
        return api_response.unauthorized()

    try:
        body = api_response.parse_body(event)
        title = validate_title(body.get("title"))
        content = validate_content(body.get("content"))
        entry_date = validate_entry_date(body.get("entryDate"))
    except (ValueError, ValidationError) as exc:
        return api_response.validation_error(str(exc))

    try:
        entry = journal_service.create_entry(
            user_id=user_id, title=title, content=content, entry_date=entry_date
        )
    except Exception:
        logger.exception("Failed to create entry for user %s", user_id)
        return api_response.internal_error()

    return api_response.success({"entry": entry.to_api()}, status_code=201)

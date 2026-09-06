"""PUT /entries/{entryId} - edit an entry and re-classify its mood."""

from typing import Any

from services import journal_service
from services.journal_service import EntryNotFoundError
from utils import api_response
from utils.logging_config import get_logger
from utils.request_context import MissingIdentityError, get_user_id, path_params
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

    entry_id = path_params(event).get("entryId")
    if not entry_id:
        return api_response.validation_error("Entry id is required.")

    try:
        body = api_response.parse_body(event)
        title = validate_title(body.get("title"))
        content = validate_content(body.get("content"))
        entry_date = validate_entry_date(body.get("entryDate"))
    except (ValueError, ValidationError) as exc:
        return api_response.validation_error(str(exc))

    try:
        entry = journal_service.update_entry(
            user_id=user_id,
            entry_id=entry_id,
            title=title,
            content=content,
            entry_date=entry_date,
        )
    except EntryNotFoundError:
        return api_response.not_found("Entry not found.")
    except Exception:
        logger.exception("Failed to update entry %s", entry_id)
        return api_response.internal_error()

    return api_response.success({"entry": entry.to_api()})

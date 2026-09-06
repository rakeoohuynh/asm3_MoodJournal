"""DELETE /entries/{entryId} - remove an entry."""

from typing import Any

from services import journal_service
from services.journal_service import EntryNotFoundError
from utils import api_response
from utils.logging_config import get_logger
from utils.request_context import MissingIdentityError, get_user_id, path_params

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
        journal_service.delete_entry(user_id, entry_id)
    except EntryNotFoundError:
        return api_response.not_found("Entry not found.")
    except Exception:
        logger.exception("Failed to delete entry %s", entry_id)
        return api_response.internal_error()

    return api_response.no_content()

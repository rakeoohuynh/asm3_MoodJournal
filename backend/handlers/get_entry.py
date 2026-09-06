"""GET /entries/{entryId} - fetch one entry."""

from typing import Any

from repositories.journal_repository import JournalRepository
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
        # The query is scoped to this user's partition, so one user can never
        # read another user's entry by guessing an id.
        entry = JournalRepository().get_entry(user_id, entry_id)
    except Exception:
        logger.exception("Failed to load entry %s", entry_id)
        return api_response.internal_error()

    if entry is None:
        return api_response.not_found("Entry not found.")

    return api_response.success({"entry": entry.to_api()})

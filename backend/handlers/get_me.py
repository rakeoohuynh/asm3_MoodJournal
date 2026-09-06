"""GET /auth/me - return the signed-in user."""

from typing import Any

from repositories.user_repository import UserRepository
from utils import api_response
from utils.logging_config import get_logger
from utils.request_context import MissingIdentityError, get_user_id

logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        user_id = get_user_id(event)
    except MissingIdentityError:
        return api_response.unauthorized()

    try:
        user = UserRepository().find_by_id(user_id)
    except Exception:
        logger.exception("Failed to load user %s", user_id)
        return api_response.internal_error()

    if user is None:
        return api_response.not_found("User not found.")

    return api_response.success({"user": user.to_api()})

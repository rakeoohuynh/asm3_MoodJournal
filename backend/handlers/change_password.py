"""POST /auth/change-password - replace the signed-in user's password."""

from typing import Any

from services import auth_service
from services.auth_service import AuthError
from utils import api_response
from utils.logging_config import get_logger
from utils.request_context import MissingIdentityError, get_user_id
from utils.validation import ValidationError, validate_password

logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        user_id = get_user_id(event)
    except MissingIdentityError:
        return api_response.unauthorized()

    try:
        body = api_response.parse_body(event)
        current_password = body.get("currentPassword")
        new_password = validate_password(body.get("newPassword"))
    except (ValueError, ValidationError) as exc:
        return api_response.validation_error(str(exc))

    if not isinstance(current_password, str) or not current_password:
        return api_response.validation_error("Current password is required.")

    if current_password == new_password:
        return api_response.validation_error(
            "The new password must be different from the current one."
        )

    try:
        auth_service.change_password(user_id, current_password, new_password)
    except AuthError as exc:
        return api_response.error(api_response.UNAUTHORIZED, str(exc), 401)
    except Exception:
        logger.exception("Password change failed for user %s", user_id)
        return api_response.internal_error()

    return api_response.success({"message": "Password updated successfully."})

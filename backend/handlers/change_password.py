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
    except ValueError as exc:
        return api_response.validation_error(str(exc))

    current_password = body.get("currentPassword")
    if not isinstance(current_password, str) or not current_password:
        return api_response.validation_error("Current password is required.")

    # Prove who you are before anything else is judged. Otherwise someone who
    # types the wrong current password is told their new one is too short,
    # which reads as though the change was accepted and only the format was
    # wrong. The credential check is the one that decides the outcome.
    try:
        auth_service.verify_current_password(user_id, current_password)
    except AuthError as exc:
        # INVALID_CURRENT_PASSWORD, not UNAUTHORIZED: the caller's session is
        # perfectly valid, they simply mistyped. Returning UNAUTHORIZED makes
        # the frontend clear the token and log them out over a typo.
        return api_response.error(api_response.INVALID_CURRENT_PASSWORD, str(exc), 401)
    except Exception:
        logger.exception("Password check failed for user %s", user_id)
        return api_response.internal_error()

    try:
        new_password = validate_password(body.get("newPassword"))
    except ValidationError as exc:
        return api_response.validation_error(str(exc))

    if current_password == new_password:
        return api_response.validation_error(
            "The new password must be different from the current one."
        )

    try:
        # Already verified above, so this writes the new hash without repeating
        # the deliberately slow password check.
        auth_service.set_password(user_id, new_password)
    except Exception:
        logger.exception("Password change failed for user %s", user_id)
        return api_response.internal_error()

    return api_response.success({"message": "Password updated successfully."})

"""POST /auth/register - create a new account."""

from typing import Any

from repositories.user_repository import UsernameTakenError
from services import auth_service
from utils import api_response
from utils.logging_config import get_logger
from utils.validation import ValidationError, validate_password, validate_username

logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        body = api_response.parse_body(event)
        username = validate_username(body.get("username"))
        password = validate_password(body.get("password"))
    except (ValueError, ValidationError) as exc:
        return api_response.validation_error(str(exc))

    try:
        user = auth_service.register(username, password)
    except UsernameTakenError:
        return api_response.conflict("That username is already taken.")
    except Exception:
        logger.exception("Registration failed")
        return api_response.internal_error()

    token, expires_at = auth_service.issue_token(user)
    return api_response.success(
        {"user": user.to_api(), "token": token, "expiresAt": expires_at},
        status_code=201,
    )

"""POST /auth/login - exchange credentials for a token."""

from typing import Any

from services import auth_service
from services.auth_service import AuthError
from utils import api_response
from utils.logging_config import get_logger

logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        body = api_response.parse_body(event)
    except ValueError as exc:
        return api_response.validation_error(str(exc))

    username = str(body.get("username", "")).strip().lower()
    password = body.get("password")

    # Credentials are checked as supplied. Applying the registration rules here
    # would let an attacker learn which usernames exist from the error text.
    if not username or not isinstance(password, str) or not password:
        return api_response.validation_error("Username and password are required.")

    try:
        user = auth_service.login(username, password)
    except AuthError as exc:
        return api_response.error(api_response.UNAUTHORIZED, str(exc), 401)
    except Exception:
        logger.exception("Login failed")
        return api_response.internal_error()

    token, expires_at = auth_service.issue_token(user)
    return api_response.success(
        {"user": user.to_api(), "token": token, "expiresAt": expires_at}
    )

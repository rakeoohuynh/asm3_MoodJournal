"""Registration, login, and JWT issuing/verification.

Tokens are signed with HS256 using a secret supplied by the SAM template.
The secret is never sent to the frontend, and tokens are never stored in
DynamoDB - they are self-contained and expire on their own.
"""

import os
from datetime import datetime, timedelta, timezone

import jwt

from models.journal_entry import utc_now_iso
from models.user import User
from repositories.user_repository import UserRepository, UsernameTakenError
from utils.logging_config import get_logger
from utils.passwords import hash_password, verify_password

logger = get_logger(__name__)

JWT_ALGORITHM = "HS256"
TOKEN_TTL_HOURS = int(os.environ.get("JWT_TTL_HOURS", "24"))


class AuthError(Exception):
    """Raised when credentials are rejected or a token is invalid."""


def _get_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise AuthError("JWT_SECRET is not configured.")
    return secret


def issue_token(user: User) -> tuple[str, str]:
    """Create a signed token for a user.

    Returns (token, expires_at_iso).
    """
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
    payload = {
        "sub": user.user_id,
        "username": user.username,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)
    return token, expires_at.isoformat(timespec="seconds")


def verify_token(token: str) -> dict[str, str]:
    """Validate a token and return its claims.

    The algorithm is pinned so a token claiming "alg": "none" is rejected.
    """
    try:
        return jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Session has expired. Please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid authentication token.") from exc


def register(username: str, password: str, repo: UserRepository | None = None) -> User:
    """Create a new account.

    Raises UsernameTakenError when the username already exists.
    """
    repo = repo or UserRepository()
    user = User(username=username, password_hash=hash_password(password))
    return repo.create(user)


def login(username: str, password: str, repo: UserRepository | None = None) -> User:
    """Verify credentials and return the user.

    The same error is raised whether the username or the password was wrong,
    so the response cannot be used to discover which usernames exist.
    """
    repo = repo or UserRepository()
    user = repo.find_by_username(username)

    if user is None or not verify_password(password, user.password_hash):
        logger.info("Failed login attempt for username %s", username)
        raise AuthError("Incorrect username or password.")

    logger.info("User %s signed in", user.user_id)
    return user


def verify_current_password(
    user_id: str, current_password: str, repo: UserRepository | None = None
) -> None:
    """Raise AuthError unless this is the user's current password.

    Separate from change_password so a caller can reject a wrong password
    before spending time validating anything else. Hashing is deliberately
    slow, so this is not something to run twice per request.
    """
    repo = repo or UserRepository()
    user = repo.find_by_id(user_id)

    if user is None or not verify_password(current_password, user.password_hash):
        raise AuthError("Current password is incorrect.")


def set_password(
    user_id: str, new_password: str, repo: UserRepository | None = None
) -> None:
    """Write a new password hash. The caller must already have authenticated."""
    repo = repo or UserRepository()
    repo.update_password(user_id, hash_password(new_password), utc_now_iso())


def change_password(
    user_id: str,
    current_password: str,
    new_password: str,
    repo: UserRepository | None = None,
) -> None:
    """Replace a user's password after verifying the current one."""
    repo = repo or UserRepository()
    verify_current_password(user_id, current_password, repo=repo)
    set_password(user_id, new_password, repo=repo)


__all__ = [
    "AuthError",
    "UsernameTakenError",
    "change_password",
    "issue_token",
    "login",
    "register",
    "set_password",
    "verify_current_password",
    "verify_token",
]

"""Identity and query-string helpers for handlers.

`get_user_id` is the single place that knows where identity comes from.
The JWT authorizer puts the user id into the request context; swapping to
Cognito later would change this function and nothing else.
"""

from typing import Any


class MissingIdentityError(Exception):
    """Raised when a request reaches a handler without an authenticated user."""


def get_user_id(event: dict[str, Any]) -> str:
    """Read the authenticated user id from the authorizer context."""
    context = (
        event.get("requestContext", {}).get("authorizer", {}) or {}
    )

    # REQUEST authorizers place custom fields directly on the authorizer object;
    # JWT/Cognito authorizers nest them under "claims".
    user_id = context.get("userId") or context.get("claims", {}).get("sub")

    if not user_id:
        raise MissingIdentityError("No authenticated user on the request.")
    return str(user_id)


def query_params(event: dict[str, Any]) -> dict[str, str]:
    """Query string parameters, defaulting to an empty dict."""
    return event.get("queryStringParameters") or {}


def path_params(event: dict[str, Any]) -> dict[str, str]:
    """Path parameters, defaulting to an empty dict."""
    return event.get("pathParameters") or {}

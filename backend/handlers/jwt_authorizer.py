"""API Gateway REQUEST authorizer.

Runs before every protected endpoint. Validates the bearer token and passes
the user id down to the handler through the authorizer context, so no handler
ever parses a token itself.

Returning an explicit Deny policy (rather than raising) gives the caller a
clean 403 instead of a 500.
"""

from typing import Any

from services.auth_service import AuthError, verify_token
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _policy(principal_id: str, effect: str, resource: str, context: dict | None = None):
    document: dict[str, Any] = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}
            ],
        },
    }
    if context:
        document["context"] = context
    return document


def _extract_token(event: dict[str, Any]) -> str | None:
    """Read the bearer token from the event.

    Handles both authorizer payload shapes. A TOKEN authorizer receives the
    header value as `authorizationToken` and no `headers` at all; a REQUEST
    authorizer receives `headers`. Supporting both means the function keeps
    working if the authorizer type changes.
    """
    raw = event.get("authorizationToken")

    if not raw:
        headers = event.get("headers") or {}
        # API Gateway header casing is not guaranteed.
        raw = headers.get("Authorization") or headers.get("authorization")

    if not raw:
        return None
    parts = raw.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Authorize an API Gateway request."""
    # Allow the whole API for a valid token rather than the exact method ARN,
    # so the cached policy works across endpoints.
    resource = event.get("methodArn", "*")
    api_wildcard = resource.split("/")[0] + "/*" if "/" in resource else resource

    token = _extract_token(event)
    if not token:
        return _policy("anonymous", "Deny", api_wildcard)

    try:
        claims = verify_token(token)
    except AuthError as exc:
        logger.info("Rejected token: %s", exc)
        return _policy("anonymous", "Deny", api_wildcard)

    user_id = str(claims.get("sub", ""))
    if not user_id:
        return _policy("anonymous", "Deny", api_wildcard)

    return _policy(
        user_id,
        "Allow",
        api_wildcard,
        context={"userId": user_id, "username": str(claims.get("username", ""))},
    )

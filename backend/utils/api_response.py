"""Consistent API Gateway responses.

Success bodies look like:   {"success": true, "entry": {...}}
Error bodies look like:     {"success": false, "error": {"code": ..., "message": ...}}
"""

import json
import os
from decimal import Decimal
from typing import Any

CORS_ORIGIN = os.environ.get("CORS_ALLOWED_ORIGIN", "*")

# Error codes returned to the frontend. Messages must stay generic enough
# that they never leak internal detail.
VALIDATION_ERROR = "VALIDATION_ERROR"
NOT_FOUND = "NOT_FOUND"
CONFLICT = "CONFLICT"
UNAUTHORIZED = "UNAUTHORIZED"
INTERNAL_ERROR = "INTERNAL_ERROR"
EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"
TIMEOUT = "TIMEOUT"


class _DecimalEncoder(json.JSONEncoder):
    """DynamoDB returns numbers as Decimal, which json cannot serialise."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return int(o) if o % 1 == 0 else float(o)
        return super().default(o)


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": CORS_ORIGIN,
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    }


def success(payload: dict[str, Any], status_code: int = 200) -> dict[str, Any]:
    """Build a successful API Gateway response."""
    body = {"success": True, **payload}
    return {
        "statusCode": status_code,
        "headers": _headers(),
        "body": json.dumps(body, cls=_DecimalEncoder),
    }


def no_content() -> dict[str, Any]:
    """204 response for a successful delete."""
    return {"statusCode": 204, "headers": _headers(), "body": ""}


def error(code: str, message: str, status_code: int = 400) -> dict[str, Any]:
    """Build an error API Gateway response."""
    body = {"success": False, "error": {"code": code, "message": message}}
    return {
        "statusCode": status_code,
        "headers": _headers(),
        "body": json.dumps(body),
    }


def validation_error(message: str) -> dict[str, Any]:
    return error(VALIDATION_ERROR, message, 400)


def not_found(message: str = "The requested resource was not found.") -> dict[str, Any]:
    return error(NOT_FOUND, message, 404)


def unauthorized(message: str = "Authentication is required.") -> dict[str, Any]:
    return error(UNAUTHORIZED, message, 401)


def conflict(message: str) -> dict[str, Any]:
    return error(CONFLICT, message, 409)


def internal_error() -> dict[str, Any]:
    return error(INTERNAL_ERROR, "An unexpected error occurred.", 500)


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """Read and decode the JSON request body.

    Raises ValueError when the body is missing or not a JSON object.
    """
    raw = event.get("body")
    if raw is None or raw == "":
        raise ValueError("Request body is required.")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Request body must be a JSON object.")
    return parsed

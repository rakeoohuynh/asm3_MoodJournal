"""Pagination tokens.

DynamoDB returns LastEvaluatedKey as a dict. The frontend cannot be trusted
with a raw key, and it must survive a URL query string, so it is encoded as
URL-safe base64 and validated on the way back in.
"""

import base64
import json
from typing import Any

from utils.validation import ValidationError

# A page key is only ever {"PK": ..., "SK": ...} in this application.
_ALLOWED_KEYS = {"PK", "SK"}


def encode_token(last_key: dict[str, Any] | None) -> str | None:
    """Turn a DynamoDB LastEvaluatedKey into an opaque token."""
    if not last_key:
        return None
    raw = json.dumps(last_key, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_token(token: str | None) -> dict[str, Any] | None:
    """Turn a token back into a DynamoDB ExclusiveStartKey.

    Raises ValidationError when the token is malformed or contains unexpected
    keys, so a tampered token becomes a 400 rather than a 500.
    """
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        decoded = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("Invalid pagination token.") from exc

    if not isinstance(decoded, dict) or not decoded:
        raise ValidationError("Invalid pagination token.")
    if set(decoded) - _ALLOWED_KEYS:
        raise ValidationError("Invalid pagination token.")
    if not all(isinstance(v, str) for v in decoded.values()):
        raise ValidationError("Invalid pagination token.")
    return decoded

"""Input validation.

Every value that reaches DynamoDB or Gemini passes through here first.
Each function returns the cleaned value or raises ValidationError.
"""

import re
from datetime import date, datetime, timedelta, timezone

MIN_CONTENT_LENGTH = 1
MAX_CONTENT_LENGTH = 5000
MAX_TITLE_LENGTH = 200

MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 30
_USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]+$")

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

VALID_PERIODS = {"7d", "14d", "30d", "90d"}
_PERIOD_DAYS = {"7d": 7, "14d": 14, "30d": 30, "90d": 90}

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


class ValidationError(Exception):
    """Raised when user input fails validation."""


def validate_content(value: object) -> str:
    """Journal body text. Required, trimmed, 1-5000 characters."""
    if not isinstance(value, str):
        raise ValidationError("Journal content is required.")
    cleaned = value.strip()
    if len(cleaned) < MIN_CONTENT_LENGTH:
        raise ValidationError("Journal content is required.")
    if len(cleaned) > MAX_CONTENT_LENGTH:
        raise ValidationError(
            f"Journal content must be {MAX_CONTENT_LENGTH} characters or fewer."
        )
    return cleaned


def validate_title(value: object) -> str:
    """Entry title. Optional; empty string when absent."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError("Title must be text.")
    cleaned = value.strip()
    if len(cleaned) > MAX_TITLE_LENGTH:
        raise ValidationError(f"Title must be {MAX_TITLE_LENGTH} characters or fewer.")
    return cleaned


def validate_entry_date(value: object) -> str:
    """Entry date as YYYY-MM-DD. Defaults to today (UTC) when absent.

    The browser sends the writer's local date, which can be a day ahead of UTC
    for anyone east of Greenwich - it is already the 9th in Sydney while UTC is
    still the 8th. Rejecting that as "in the future" would stop those users
    recording today's entry for the first hours of every day, so the ceiling is
    UTC tomorrow. Timezones reach UTC+14, which is still inside one day.
    """
    if value is None or value == "":
        return datetime.now(timezone.utc).date().isoformat()
    if not isinstance(value, str):
        raise ValidationError("Entry date must be in YYYY-MM-DD format.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("Entry date must be in YYYY-MM-DD format.") from exc
    if parsed.year < 2000 or parsed.year > 2100:
        raise ValidationError("Entry date is outside the supported range.")
    if parsed > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise ValidationError("Entry date cannot be in the future.")
    return parsed.isoformat()


def validate_optional_date(value: object, field_name: str) -> str | None:
    """Optional YYYY-MM-DD filter value."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be in YYYY-MM-DD format.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be in YYYY-MM-DD format.") from exc


def validate_limit(value: object) -> int:
    """Page size for list endpoints."""
    if value is None or value == "":
        return DEFAULT_PAGE_SIZE
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Limit must be a whole number.") from exc
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise ValidationError(f"Limit must be between 1 and {MAX_PAGE_SIZE}.")
    return limit


def validate_period(value: object) -> int:
    """Dashboard/reflection period. Returns the number of days."""
    if value is None or value == "":
        return _PERIOD_DAYS["7d"]
    if value not in VALID_PERIODS:
        allowed = ", ".join(sorted(VALID_PERIODS))
        raise ValidationError(f"Period must be one of: {allowed}.")
    return _PERIOD_DAYS[str(value)]


def validate_username(value: object) -> str:
    """Username. Stored lowercase, 3-30 chars, [a-z0-9_.-] only."""
    if not isinstance(value, str):
        raise ValidationError("Username is required.")
    cleaned = value.strip().lower()
    if len(cleaned) < MIN_USERNAME_LENGTH or len(cleaned) > MAX_USERNAME_LENGTH:
        raise ValidationError(
            f"Username must be between {MIN_USERNAME_LENGTH} and "
            f"{MAX_USERNAME_LENGTH} characters."
        )
    if not _USERNAME_PATTERN.match(cleaned):
        raise ValidationError(
            "Username may only contain letters, numbers, underscore, hyphen and period."
        )
    return cleaned


def validate_password(value: object) -> str:
    """Password. At least 8 characters, with a letter and a number.

    Returned unchanged so it can be hashed. It is never stored or logged.
    """
    if not isinstance(value, str):
        raise ValidationError("Password is required.")
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(value) > MAX_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be {MAX_PASSWORD_LENGTH} characters or fewer."
        )
    if not any(c.isalpha() for c in value):
        raise ValidationError("Password must contain at least one letter.")
    if not any(c.isdigit() for c in value):
        raise ValidationError("Password must contain at least one number.")
    return value

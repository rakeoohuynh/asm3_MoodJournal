"""Structured logging for Lambda.

Journal content is private. Never pass raw entry text to a logger; log the
length instead. `redact` is provided for that.
"""

import logging
import os

_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured for the Lambda runtime."""
    logger = logging.getLogger(name)
    logger.setLevel(_LOG_LEVEL)
    return logger


def redact(text: str | None) -> str:
    """Describe user text without revealing it."""
    if not text:
        return "<empty>"
    return f"<{len(text)} chars>"

"""Shared in-memory storage for local development only.

Data survives across HTTP requests while the Python process is running.
Restarting the backend clears everything by design.
"""

from __future__ import annotations

from threading import RLock

USERS_BY_ID: dict[str, object] = {}
USER_ID_BY_USERNAME: dict[str, str] = {}
JOURNALS_BY_USER: dict[str, list[object]] = {}
REFLECTIONS_BY_USER: dict[str, list[object]] = {}
STORE_LOCK = RLock()


def reset_memory_store() -> None:
    """Clear all local data. Useful for tests."""
    with STORE_LOCK:
        USERS_BY_ID.clear()
        USER_ID_BY_USERNAME.clear()
        JOURNALS_BY_USER.clear()
        REFLECTIONS_BY_USER.clear()

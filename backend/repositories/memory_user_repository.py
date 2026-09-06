"""RAM-backed user repository used only by the local application."""

from __future__ import annotations

from models.user import User
from repositories.memory_store import STORE_LOCK, USERS_BY_ID, USER_ID_BY_USERNAME


class UsernameTakenError(Exception):
    """Raised when a username already exists in the local store."""


class MemoryUserRepository:
    def find_by_username(self, username: str) -> User | None:
        with STORE_LOCK:
            user_id = USER_ID_BY_USERNAME.get(username)
            return USERS_BY_ID.get(user_id) if user_id else None

    def find_by_id(self, user_id: str) -> User | None:
        with STORE_LOCK:
            return USERS_BY_ID.get(user_id)

    def create(self, user: User) -> User:
        with STORE_LOCK:
            if user.username in USER_ID_BY_USERNAME:
                raise UsernameTakenError(user.username)
            USERS_BY_ID[user.user_id] = user
            USER_ID_BY_USERNAME[user.username] = user.user_id
            return user

    def update_password(self, user_id: str, password_hash: str, updated_at: str) -> None:
        with STORE_LOCK:
            user = USERS_BY_ID.get(user_id)
            if user is None:
                raise KeyError(user_id)
            user.password_hash = password_hash
            user.updated_at = updated_at

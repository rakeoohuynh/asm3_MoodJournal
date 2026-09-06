"""DynamoDB access for user accounts.

Username lookups always go through UsernameIndex. A Scan is never used:
it would read every user on every login attempt.
"""

import os
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from models.user import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

USERS_TABLE_NAME = os.environ.get("USERS_TABLE_NAME", "MoodJournalUsers")
USERNAME_INDEX = "UsernameIndex"


class UsernameTakenError(Exception):
    """Raised when a username is already registered."""


class UserRepository:
    """Reads and writes user records."""

    def __init__(self, table: Any = None) -> None:
        # The table is injectable so tests can pass a stub or a moto table.
        if table is None:
            table = boto3.resource("dynamodb").Table(USERS_TABLE_NAME)
        self._table = table

    def find_by_username(self, username: str) -> User | None:
        """Look up a user by username through the GSI."""
        response = self._table.query(
            IndexName=USERNAME_INDEX,
            KeyConditionExpression=Key("username").eq(username),
            Limit=1,
        )
        items = response.get("Items", [])
        return User.from_item(items[0]) if items else None

    def find_by_id(self, user_id: str) -> User | None:
        """Look up a user by primary key."""
        response = self._table.get_item(Key={"userId": user_id})
        item = response.get("Item")
        return User.from_item(item) if item else None

    def create(self, user: User) -> User:
        """Insert a new user.

        The GSI is eventually consistent, so two simultaneous registrations
        could both pass the duplicate check. The conditional write on userId
        plus this second username check keeps the window small; a fully
        race-free version would need a separate uniqueness item.
        """
        if self.find_by_username(user.username) is not None:
            raise UsernameTakenError(user.username)

        self._table.put_item(
            Item=user.to_item(),
            ConditionExpression="attribute_not_exists(userId)",
        )
        logger.info("Created user %s", user.user_id)
        return user

    def update_password(self, user_id: str, password_hash: str, updated_at: str) -> None:
        """Replace a user's password hash."""
        self._table.update_item(
            Key={"userId": user_id},
            UpdateExpression="SET passwordHash = :h, updatedAt = :u",
            ExpressionAttributeValues={":h": password_hash, ":u": updated_at},
            ConditionExpression="attribute_exists(userId)",
        )
        logger.info("Updated password for user %s", user_id)

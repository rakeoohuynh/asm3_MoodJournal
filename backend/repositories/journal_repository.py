"""DynamoDB access for journal entries and reflections.

Both live in one table, separated by the SK prefix:
    ENTRY#{entryDate}#{entryId}
    REFLECTION#{createdAt}#{reflectionId}

`user_id` is always passed in as an argument rather than read from the
environment, so swapping the source of identity (demo user, JWT, Cognito)
never changes this file.
"""

import os
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key

from models.journal_entry import JournalEntry
from models.reflection import Reflection
from utils.logging_config import get_logger

logger = get_logger(__name__)

TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "MoodJournalTable")

# Cap on items read while resolving a single entryId, so a large history
# cannot turn one lookup into an expensive full-partition read.
_LOOKUP_PAGE_LIMIT = 200


class JournalRepository:
    """Reads and writes journal entries and reflections."""

    def __init__(self, table: Any = None) -> None:
        if table is None:
            table = boto3.resource("dynamodb").Table(TABLE_NAME)
        self._table = table

    # -- entries ------------------------------------------------------------

    def put_entry(self, entry: JournalEntry) -> JournalEntry:
        """Insert or replace an entry."""
        self._table.put_item(Item=entry.to_item())
        logger.info("Saved entry %s for user %s", entry.entry_id, entry.user_id)
        return entry

    def get_entry(self, user_id: str, entry_id: str) -> JournalEntry | None:
        """Find one entry by id.

        The sort key contains the date, which the caller does not know, so this
        queries the user's ENTRY items and filters. It is a Query on one
        partition, not a table Scan.
        """
        response = self._table.query(
            KeyConditionExpression=Key("PK").eq(f"USER#{user_id}")
            & Key("SK").begins_with("ENTRY#"),
            FilterExpression=Attr("entryId").eq(entry_id),
            Limit=_LOOKUP_PAGE_LIMIT,
        )
        items = response.get("Items", [])
        return JournalEntry.from_item(items[0]) if items else None

    def list_entries(
        self,
        user_id: str,
        mood: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
        start_key: dict[str, Any] | None = None,
    ) -> tuple[list[JournalEntry], dict[str, Any] | None]:
        """List entries newest first, with optional filters.

        Date filtering uses the sort key range so DynamoDB does the work.
        Mood filtering is a FilterExpression, which is applied after the read.
        """
        low = f"ENTRY#{start_date}" if start_date else "ENTRY#"
        high = f"ENTRY#{end_date}￿" if end_date else "ENTRY#￿"

        params: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(f"USER#{user_id}")
            & Key("SK").between(low, high),
            "ScanIndexForward": False,  # newest first
            "Limit": limit,
        }
        if mood:
            params["FilterExpression"] = Attr("mood").eq(mood)
        if start_key:
            params["ExclusiveStartKey"] = start_key

        response = self._table.query(**params)
        entries = [JournalEntry.from_item(i) for i in response.get("Items", [])]
        return entries, response.get("LastEvaluatedKey")

    def list_entries_in_range(
        self, user_id: str, start_date: str, end_date: str
    ) -> list[JournalEntry]:
        """Read every entry in a date range, following pagination.

        Used by the dashboard, reflections and analytics export, which all need
        the complete set rather than one page.
        """
        entries: list[JournalEntry] = []
        start_key: dict[str, Any] | None = None

        while True:
            params: dict[str, Any] = {
                "KeyConditionExpression": Key("PK").eq(f"USER#{user_id}")
                & Key("SK").between(f"ENTRY#{start_date}", f"ENTRY#{end_date}￿"),
                "ScanIndexForward": False,
            }
            if start_key:
                params["ExclusiveStartKey"] = start_key

            response = self._table.query(**params)
            entries.extend(JournalEntry.from_item(i) for i in response.get("Items", []))

            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return entries

    def delete_entry(self, user_id: str, entry: JournalEntry) -> None:
        """Delete an entry by its full key."""
        self._table.delete_item(Key={"PK": entry.pk, "SK": entry.sk})
        logger.info("Deleted entry %s for user %s", entry.entry_id, user_id)

    # -- reflections --------------------------------------------------------

    def put_reflection(self, reflection: Reflection) -> Reflection:
        """Insert a reflection."""
        self._table.put_item(Item=reflection.to_item())
        logger.info(
            "Saved reflection %s for user %s", reflection.reflection_id, reflection.user_id
        )
        return reflection

    def list_reflections(
        self,
        user_id: str,
        limit: int = 20,
        start_key: dict[str, Any] | None = None,
    ) -> tuple[list[Reflection], dict[str, Any] | None]:
        """List reflections newest first."""
        params: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(f"USER#{user_id}")
            & Key("SK").begins_with("REFLECTION#"),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if start_key:
            params["ExclusiveStartKey"] = start_key

        response = self._table.query(**params)
        reflections = [Reflection.from_item(i) for i in response.get("Items", [])]
        return reflections, response.get("LastEvaluatedKey")

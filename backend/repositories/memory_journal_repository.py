"""RAM-backed journal/reflection repository for local development."""

from __future__ import annotations

from models.journal_entry import JournalEntry
from models.reflection import Reflection
from repositories.memory_store import JOURNALS_BY_USER, REFLECTIONS_BY_USER, STORE_LOCK


class MemoryJournalRepository:
    def put_entry(self, entry: JournalEntry) -> JournalEntry:
        with STORE_LOCK:
            entries = JOURNALS_BY_USER.setdefault(entry.user_id, [])
            for i, existing in enumerate(entries):
                if existing.entry_id == entry.entry_id:
                    entries[i] = entry
                    break
            else:
                entries.append(entry)
            return entry

    def get_entry(self, user_id: str, entry_id: str) -> JournalEntry | None:
        with STORE_LOCK:
            return next(
                (e for e in JOURNALS_BY_USER.get(user_id, []) if e.entry_id == entry_id),
                None,
            )

    def list_entries(
        self,
        user_id: str,
        mood: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[JournalEntry], int | None]:
        with STORE_LOCK:
            entries = list(JOURNALS_BY_USER.get(user_id, []))

        if mood:
            entries = [e for e in entries if e.mood == mood]
        if start_date:
            entries = [e for e in entries if e.entry_date >= start_date]
        if end_date:
            entries = [e for e in entries if e.entry_date <= end_date]
        if search:
            needle = search.strip().lower()
            if needle:
                entries = [
                    e for e in entries
                    if needle in (e.title or "").lower() or needle in (e.content or "").lower()
                ]

        entries.sort(key=lambda e: (e.entry_date, e.created_at, e.entry_id), reverse=True)
        page = entries[offset : offset + limit]
        next_offset = offset + len(page)
        if next_offset >= len(entries):
            next_offset = None
        return page, next_offset

    def list_entries_in_range(self, user_id: str, start_date: str, end_date: str):
        with STORE_LOCK:
            entries = [
                e for e in JOURNALS_BY_USER.get(user_id, [])
                if start_date <= e.entry_date <= end_date
            ]
        entries.sort(key=lambda e: (e.entry_date, e.created_at, e.entry_id), reverse=True)
        return entries

    def delete_entry(self, user_id: str, entry: JournalEntry) -> None:
        with STORE_LOCK:
            items = JOURNALS_BY_USER.get(user_id, [])
            JOURNALS_BY_USER[user_id] = [e for e in items if e.entry_id != entry.entry_id]

    def put_reflection(self, reflection: Reflection) -> Reflection:
        with STORE_LOCK:
            REFLECTIONS_BY_USER.setdefault(reflection.user_id, []).append(reflection)
            return reflection

    def list_reflections(self, user_id: str, limit: int = 20, offset: int = 0):
        with STORE_LOCK:
            items = list(REFLECTIONS_BY_USER.get(user_id, []))
        items.sort(key=lambda r: (r.created_at, r.reflection_id), reverse=True)
        page = items[offset : offset + limit]
        next_offset = offset + len(page)
        if next_offset >= len(items):
            next_offset = None
        return page, next_offset

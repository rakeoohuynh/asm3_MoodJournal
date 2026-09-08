"""Aggregation for the dashboard, and export of analytics records to S3.

Only derived values leave DynamoDB - counts, scores, and content length.
Journal text is never written to the analytics bucket.
"""

import json
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

import boto3

from models.journal_entry import MOOD_SCORES, VALID_MOODS, JournalEntry
from repositories.journal_repository import JournalRepository
from utils.logging_config import get_logger

logger = get_logger(__name__)

ANALYTICS_BUCKET = os.environ.get("ANALYTICS_BUCKET_NAME", "")
EXPORT_PREFIX = "moodjournal"


def date_range(days: int) -> tuple[str, str]:
    """Inclusive start and end dates covering the last `days` days.

    The end is UTC tomorrow, not UTC today. Entries carry the writer's local
    date, which is a day ahead of UTC for part of every day east of Greenwich,
    so stopping at UTC today would hide an entry the user just wrote from their
    own dashboard until UTC caught up.
    """
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    return start.isoformat(), (today + timedelta(days=1)).isoformat()


def build_dashboard(
    user_id: str, days: int, repo: JournalRepository | None = None
) -> dict[str, Any]:
    """Aggregate entries into the numbers the dashboard displays."""
    repo = repo or JournalRepository()
    start_date, end_date = date_range(days)
    entries = repo.list_entries_in_range(user_id, start_date, end_date)

    total = len(entries)
    mood_counts = Counter(e.mood for e in entries)
    scores = [e.mood_score for e in entries]

    distribution = [
        {
            "mood": mood,
            "count": mood_counts.get(mood, 0),
            "percentage": round(mood_counts.get(mood, 0) / total * 100, 1) if total else 0.0,
        }
        for mood in VALID_MOODS
    ]

    most_common = mood_counts.most_common(1)[0][0] if mood_counts else None

    # Average score per day, oldest first, so the line chart reads left to right.
    by_day: dict[str, list[int]] = {}
    for entry in entries:
        by_day.setdefault(entry.entry_date, []).append(entry.mood_score)

    trend = [
        {
            "date": day,
            "averageScore": round(sum(scores) / len(scores), 2),
            "entryCount": len(scores),
        }
        for day, scores in sorted(by_day.items())
    ]

    return {
        "period": f"{days}d",
        "periodStart": start_date,
        "periodEnd": end_date,
        "totalEntries": total,
        "mostCommonMood": most_common,
        # dashboard.html renders this in the "Average Score" tile and shows a
        # dash when it is null. Omitting it entirely made the tile read NaN.
        "averageScore": round(sum(scores) / len(scores), 2) if scores else None,
        "entriesInPeriod": total,
        "moodDistribution": distribution,
        "moodTrend": trend,
        "weeklySummary": _weekly_summary(entries),
        "scoreMapping": MOOD_SCORES,
        "scoreNote": (
            "Mood scores are used only to visualise trends. They are not a "
            "measurement of wellbeing."
        ),
    }


def _weekly_summary(entries: list[JournalEntry]) -> list[dict[str, Any]]:
    """Group entries into ISO weeks for the summary table."""
    weeks: dict[str, list[JournalEntry]] = {}
    for entry in entries:
        entry_day = date.fromisoformat(entry.entry_date)
        week_start = entry_day - timedelta(days=entry_day.weekday())
        weeks.setdefault(week_start.isoformat(), []).append(entry)

    summary = []
    for week_start, week_entries in sorted(weeks.items(), reverse=True):
        counts = Counter(e.mood for e in week_entries)
        scores = [e.mood_score for e in week_entries]
        summary.append(
            {
                "weekStart": week_start,
                "entryCount": len(week_entries),
                "averageScore": round(sum(scores) / len(scores), 2),
                "dominantMood": counts.most_common(1)[0][0],
                "moodCounts": {mood: counts.get(mood, 0) for mood in VALID_MOODS},
            }
        )
    return summary


def to_analytics_record(entry: JournalEntry) -> dict[str, Any]:
    """Reduce an entry to the fields Athena queries.

    Note that `content` is absent by design - only its length is exported.
    """
    return {
        "entryid": entry.entry_id,
        "userid": entry.user_id,
        "entrydate": entry.entry_date,
        "mood": entry.mood,
        "moodscore": entry.mood_score,
        "confidence": round(entry.confidence, 2),
        "contentlength": len(entry.content),
        "classificationfallback": entry.classification_fallback,
        "createdat": entry.created_at,
    }


def export_to_s3(
    user_id: str,
    days: int = 90,
    repo: JournalRepository | None = None,
    s3_client: Any = None,
) -> dict[str, Any]:
    """Write analytics records to S3 as JSON Lines for Athena.

    Object key:
        moodjournal/year=YYYY/month=MM/day=DD/{userId}.json
    """
    if not ANALYTICS_BUCKET:
        raise ValueError("ANALYTICS_BUCKET_NAME is not configured.")

    repo = repo or JournalRepository()
    s3_client = s3_client or boto3.client("s3")

    start_date, end_date = date_range(days)
    entries = repo.list_entries_in_range(user_id, start_date, end_date)

    if not entries:
        logger.info("No entries to export for user %s", user_id)
        return {"exported": 0, "location": None}

    # JSON Lines: one object per line, which is what the Athena SerDe expects.
    body = "\n".join(json.dumps(to_analytics_record(e)) for e in entries)

    today = datetime.now(timezone.utc).date()
    key = (
        f"{EXPORT_PREFIX}/year={today.year:04d}/month={today.month:02d}/"
        f"day={today.day:02d}/{user_id}.json"
    )

    s3_client.put_object(
        Bucket=ANALYTICS_BUCKET,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/x-ndjson",
    )
    logger.info("Exported %d records to s3://%s/%s", len(entries), ANALYTICS_BUCKET, key)

    return {"exported": len(entries), "location": f"s3://{ANALYTICS_BUCKET}/{key}"}

"""Generation and storage of AI reflection summaries.

Gemini receives aggregated statistics and short excerpts, never the full text
of every entry. That keeps the prompt small and limits how much private
content leaves AWS.
"""

from collections import Counter

from models.reflection import Reflection
from repositories.journal_repository import JournalRepository
from services import gemini_service, offline_reflection
from services.analytics_service import date_range
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Number of entry titles included as context. Titles are short and
# user-written, so they add useful signal without sending whole entries.
_MAX_TITLE_SAMPLES = 10

_PERIOD_LABELS = {7: "the last 7 days", 14: "the last 14 days", 30: "the last 30 days"}


class NoEntriesError(Exception):
    """Raised when there is nothing in the period to reflect on."""


def _build_summary_data(entries: list) -> str:
    """Turn entries into a compact text summary for the prompt."""
    counts = Counter(e.mood for e in entries)
    scores = [e.mood_score for e in entries]
    average = sum(scores) / len(scores)

    lines = [
        f"Total entries: {len(entries)}",
        f"Average mood score: {average:.2f} (Positive=2, Neutral=1, Anxious=0, Negative=-1)",
        "Mood counts:",
    ]
    lines.extend(f"  {mood}: {count}" for mood, count in counts.most_common())

    titles = [e.title for e in entries if e.title][:_MAX_TITLE_SAMPLES]
    if titles:
        lines.append("Some entry titles:")
        lines.extend(f"  - {title}" for title in titles)

    return "\n".join(lines)


def create_reflection(
    user_id: str,
    days: int,
    generated_by: str = "manual",
    repo: JournalRepository | None = None,
) -> Reflection:
    """Generate and store a reflection for the given period.

    Raises NoEntriesError when the period contains no entries.
    """
    repo = repo or JournalRepository()
    start_date, end_date = date_range(days)
    entries = repo.list_entries_in_range(user_id, start_date, end_date)

    if not entries:
        raise NoEntriesError(f"No entries between {start_date} and {end_date}")

    period_label = _PERIOD_LABELS.get(days, f"the last {days} days")

    # Gemini answers a busy model with 503, and asking for several sentences of
    # prose is refused sooner than the small classification calls are. Failing
    # the whole request would leave the user with an error and nothing to read,
    # so the summary is written from the same aggregates instead. The stored
    # record is marked, so nothing presents this as Gemini's work.
    try:
        summary_text = gemini_service.generate_reflection(
            period_label=period_label,
            summary_data=_build_summary_data(entries),
        )
    except gemini_service.GeminiError as exc:
        logger.warning(
            "Gemini unavailable for user %s (%s); writing the summary offline",
            user_id,
            exc,
        )
        summary_text = offline_reflection.build_reflection(entries, days)
        generated_by = f"{generated_by}-offline"

    reflection = Reflection(
        user_id=user_id,
        period=f"{days}d",
        period_start=start_date,
        period_end=end_date,
        summary=summary_text,
        entry_count=len(entries),
        generated_by=generated_by,
    )
    return repo.put_reflection(reflection)

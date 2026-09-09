"""Reflection text written without Gemini.

Used when the Gemini API is unavailable - typically a 503 while the model is
under heavy demand. Rather than failing the request and showing the user an
error, a summary is written here from the same aggregates Gemini would have
been given: entry count, mood distribution, average score and the direction of
travel across the period.

Every number in the output is real. Nothing is invented, and the caller marks
the stored reflection so the interface can say plainly that this was written
offline rather than by Gemini.
"""

from __future__ import annotations

from collections import Counter

# How the four moods read in a sentence.
_MOOD_WORDS = {
    "POSITIVE": "positive",
    "NEUTRAL": "steady",
    "ANXIOUS": "anxious",
    "NEGATIVE": "difficult",
}


def _trend_sentence(entries: list) -> str:
    """Compare the first and second half of the period.

    Entries arrive newest first, so they are reversed to read chronologically.
    """
    if len(entries) < 4:
        return ""

    chronological = list(reversed(entries))
    midpoint = len(chronological) // 2
    earlier = chronological[:midpoint]
    later = chronological[midpoint:]

    first_half = sum(e.mood_score for e in earlier) / len(earlier)
    second_half = sum(e.mood_score for e in later) / len(later)
    shift = second_half - first_half

    if shift >= 0.5:
        return " The later entries score higher than the earlier ones, so the period ended on a brighter note than it began."
    if shift <= -0.5:
        return " The later entries score lower than the earlier ones, so the period became harder as it went on."
    return " The scores stayed fairly level from the start of the period to the end."


def build_reflection(entries: list, days: int) -> str:
    """Summarise a period from real aggregates, with no model involved."""
    if not entries:
        return f"There are no entries in the last {days} days to reflect on."

    counts = Counter(e.mood for e in entries)
    scores = [e.mood_score for e in entries]
    average = sum(scores) / len(scores)
    dominant, dominant_count = counts.most_common(1)[0]

    total = len(entries)
    plural = "entry" if total == 1 else "entries"
    share = round(dominant_count / total * 100)

    opening = (
        f"Over the last {days} days you wrote {total} {plural}, "
        f"averaging a mood score of {average:.2f}."
    )
    pattern = (
        f" {_MOOD_WORDS.get(dominant, dominant.lower()).capitalize()} entries were the most "
        f"common, making up {share}% of what you wrote."
    )

    named = [
        f"{count} {_MOOD_WORDS.get(mood, mood.lower())}"
        for mood, count in counts.most_common()
        if mood != dominant
    ]
    breakdown = f" Alongside those there were {', '.join(named)}." if named else ""

    closing = (
        " Writing regularly is what makes a pattern like this visible at all, "
        "so it is worth keeping up."
    )

    return opening + pattern + breakdown + _trend_sentence(entries) + closing

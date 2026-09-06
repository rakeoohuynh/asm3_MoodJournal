"""Offline/local fallback helpers for MoodJournal.

These helpers are used only by ``backend.local_app``.  They make it possible
for the full local application to be tested without AWS and without a Gemini
API key.  Results are deliberately labelled as fallback output and are not
presented as Gemini-generated content.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from models.journal_entry import DEFAULT_MOOD


@dataclass
class LocalMoodResult:
    mood: str
    confidence: float
    short_reason: str
    fallback: bool = True


_WORD_RE = re.compile(r"[a-zA-Z']+")

_POSITIVE = {
    "amazing",
    "better",
    "calm",
    "confident",
    "delighted",
    "enjoyed",
    "excited",
    "fantastic",
    "fun",
    "glad",
    "good",
    "grateful",
    "great",
    "happy",
    "hopeful",
    "joy",
    "joyful",
    "love",
    "peaceful",
    "pleased",
    "proud",
    "relaxed",
    "thankful",
    "wonderful",
}

_ANXIOUS = {
    "afraid",
    "anxious",
    "concerned",
    "fear",
    "nervous",
    "overwhelmed",
    "panic",
    "panicked",
    "pressure",
    "scared",
    "stress",
    "stressed",
    "tense",
    "uncertain",
    "uneasy",
    "worried",
    "worry",
}

_NEGATIVE = {
    "angry",
    "annoyed",
    "awful",
    "bad",
    "disappointed",
    "exhausted",
    "frustrated",
    "hate",
    "hurt",
    "lonely",
    "miserable",
    "sad",
    "terrible",
    "tired",
    "unhappy",
    "upset",
}


def classify_mood_local(text: str) -> LocalMoodResult:
    """Return a deterministic keyword-based mood for offline testing.

    This is not intended as a production sentiment model.  It exists so that
    dashboard, filtering and reflection features can be exercised locally.
    """
    words = [w.lower() for w in _WORD_RE.findall(text or "")]
    counts = Counter()
    for word in words:
        if word in _POSITIVE:
            counts["POSITIVE"] += 1
        if word in _ANXIOUS:
            counts["ANXIOUS"] += 1
        if word in _NEGATIVE:
            counts["NEGATIVE"] += 1

    if not counts:
        return LocalMoodResult(
            mood=DEFAULT_MOOD,
            confidence=0.55,
            short_reason="Local fallback found no strong mood keywords, so this entry was marked neutral.",
        )

    # Deterministic tie-break order keeps tests stable.
    order = ("ANXIOUS", "NEGATIVE", "POSITIVE")
    mood = max(order, key=lambda m: (counts[m], -order.index(m)))
    best = counts[mood]
    total = sum(counts.values())
    confidence = min(0.95, 0.60 + (best / max(total, 1)) * 0.30)
    label = mood.lower()
    return LocalMoodResult(
        mood=mood,
        confidence=round(confidence, 2),
        short_reason=f"Local keyword fallback detected mostly {label} language in this entry.",
    )


def build_local_reflection(entries: list, days: int) -> str:
    """Generate a short deterministic reflection from aggregated local data."""
    counts = Counter(e.mood for e in entries)
    dominant = counts.most_common(1)[0][0] if counts else "NEUTRAL"
    scores = [e.mood_score for e in entries]
    average = sum(scores) / len(scores) if scores else 0.0

    if dominant == "POSITIVE":
        observation = "Positive moments appeared most often in the entries from this period."
    elif dominant == "ANXIOUS":
        observation = "Anxious language appeared more often than the other mood categories in this period."
    elif dominant == "NEGATIVE":
        observation = "More of the entries in this period were classified as negative than any other category."
    else:
        observation = "Most entries in this period were relatively neutral in tone."

    if average >= 1.25:
        trend = "Overall, the mood pattern leaned on the more positive side."
    elif average <= 0:
        trend = "Overall, the mood pattern was on the more difficult side during this period."
    else:
        trend = "Overall, the mood pattern was mixed rather than strongly positive or negative."

    return (
        f"You wrote {len(entries)} journal entr{'y' if len(entries) == 1 else 'ies'} over the last {days} days, "
        f"averaging a mood score of {average:.2f}. "
        f"{observation} {trend} "
        "Keeping up a regular writing habit is what makes patterns like this visible over time."
    )

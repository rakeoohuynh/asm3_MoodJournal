"""Google Gemini integration for mood classification and reflections.

Talks to the Gemini REST API directly over urllib rather than through the
google-generativeai SDK. That SDK pulls in grpcio, which ships compiled
binaries that must match Lambda's Linux runtime - building it from Windows
produces a package that fails to import. Using the REST endpoint keeps this
module dependency-free, so `sam build` works from any machine.

Two rules shape this module:

1. The model's output is never trusted. It is parsed, validated against the
   four allowed moods, and rejected if it does not fit. A failed
   classification falls back to NEUTRAL rather than failing the save, so a
   user never loses an entry because an external API had a bad day.
2. Journal text is sent to Gemini but never written to logs.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from models.journal_entry import DEFAULT_MOOD, VALID_MOODS
from utils.logging_config import get_logger, redact

logger = get_logger(__name__)

# An alias rather than a pinned version: pinned models get retired and start
# returning 404 to new API keys, which silently degrades every classification
# to the NEUTRAL fallback. Override with GEMINI_MODEL if a specific one is needed.
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Gemini answers a demand spike with 503 "try again later". Retrying instantly
# lands in the same spike, so attempts are spaced out. The budget has to fit
# inside the 30s Lambda timeout set in template.yaml, with room to spare for
# the DynamoDB write afterwards:
#
# A 503 comes back in well under a second, so in practice the retries cost
# only the waiting; the timeout budget below is the worst case where every
# attempt hangs instead. It fits inside the 60s timeout that template.yaml
# gives the entry-writing functions:
#
#     4 attempts x 7s  +  0.5 + 1.5 + 3s of waiting  =  33s worst case
MAX_ATTEMPTS = 4
REQUEST_TIMEOUT_SECONDS = 7
RETRY_BACKOFF_SECONDS = (0.5, 1.5, 3.0)

# Strips ```json ... ``` fences that the model sometimes adds despite the prompt.
_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

CLASSIFY_PROMPT = """Classify the mood expressed in the following journal entry.

Return valid JSON only using this exact structure:

{{
  "mood": "POSITIVE | NEUTRAL | ANXIOUS | NEGATIVE",
  "confidence": 0.00,
  "shortReason": "A brief and non-clinical explanation"
}}

Rules:
- Return exactly one mood.
- Confidence must be between 0 and 1.
- Do not diagnose any medical or mental health condition.
- Do not return Markdown.
- Do not include additional fields.

Journal entry:
{journal_text}"""

REFLECTION_PROMPT = """You are helping someone reflect on their personal journal.

Below is a summary of their journal entries over {period_label}.

{summary_data}

Write a short reflection of 4 to 6 sentences that:
- Names the specific pattern in the data (which mood dominated, how the average score trended, any notable shifts) rather than speaking in generalities.
- Offers one or two constructive, encouraging observations grounded in that pattern.
- Closes with a concrete, affirming statement about their reflection practice or progress - not a question.

Rules:
- Be warm and supportive, never clinical.
- Do not diagnose any medical or mental health condition.
- Do not claim certainty about how they feel.
- Do not present this as medical or professional advice.
- Do not end with a question.
- Return plain text only, with no Markdown or headings."""


class GeminiError(Exception):
    """Raised when Gemini cannot be reached or returns nothing usable."""


@dataclass
class MoodResult:
    """Outcome of a classification attempt."""

    mood: str
    confidence: float
    short_reason: str
    fallback: bool = False


def _pause_before_retry(attempt: int) -> None:
    """Wait between attempts, so a retry does not land in the same spike.

    `attempt` is 1-based and counts the attempt that just failed; nothing is
    slept after the final one.
    """
    if attempt <= len(RETRY_BACKOFF_SECONDS):
        time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])


def _get_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY is not configured.")
    return api_key


def _extract_text(payload: dict[str, Any]) -> str:
    """Pull the generated text out of a generateContent response.

    Raises GeminiError when the model returned no usable candidate, which
    happens if the prompt was blocked by a safety filter.
    """
    candidates = payload.get("candidates") or []
    if not candidates:
        reason = (payload.get("promptFeedback") or {}).get("blockReason", "none")
        raise GeminiError(f"Gemini returned no candidates (block reason: {reason}).")

    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise GeminiError("Gemini returned an empty response.")
    return text


def _generate(prompt: str, json_output: bool = False) -> str:
    """Send one prompt to Gemini and return the generated text."""
    url = f"{API_BASE}/{MODEL_NAME}:generateContent"
    body: dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}]}
    if json_output:
        # Asking for JSON directly means the fence stripping below is only a
        # fallback rather than the primary defence.
        body["generationConfig"] = {"responseMimeType": "application/json"}

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": _get_api_key(),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # The error body carries Google's reason; the API key is not in it.
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise GeminiError(f"Gemini HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GeminiError(f"Could not reach Gemini: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise GeminiError("Gemini returned a non-JSON response.") from exc

    return _extract_text(payload)


def _strip_fences(text: str) -> str:
    """Remove Markdown code fences the model may have added."""
    return _FENCE_PATTERN.sub("", text).strip()


def parse_mood_response(raw_text: str) -> MoodResult:
    """Parse and validate a classification response.

    Raises ValueError when the payload is not usable, which triggers a retry.
    """
    cleaned = _strip_fences(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("Gemini did not return valid JSON.") from exc

    if not isinstance(data, dict):
        raise ValueError("Gemini did not return a JSON object.")

    mood = str(data.get("mood", "")).strip().upper()
    if mood not in VALID_MOODS:
        raise ValueError(f"Gemini returned an unknown mood: {mood!r}")

    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Gemini returned a non-numeric confidence.") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("Gemini returned a confidence outside 0-1.")

    reason = str(data.get("shortReason", "")).strip()[:300]

    return MoodResult(mood=mood, confidence=confidence, short_reason=reason)


def classify_mood(journal_text: str) -> MoodResult:
    """Classify one journal entry.

    Tries twice. If both attempts fail, returns NEUTRAL with fallback=True so
    the entry can still be saved.
    """
    logger.info("Classifying entry %s", redact(journal_text))
    prompt = CLASSIFY_PROMPT.format(journal_text=journal_text)

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = _generate(prompt, json_output=True)
            result = parse_mood_response(raw)
            logger.info(
                "Classified as %s (confidence %.2f) on attempt %d",
                result.mood,
                result.confidence,
                attempt,
            )
            return result
        except Exception as exc:  # noqa: BLE001 - any failure should retry then fall back
            last_error = exc
            logger.warning("Classification attempt %d failed: %s", attempt, exc)
            _pause_before_retry(attempt)

    logger.error("Classification failed after %d attempts: %s", MAX_ATTEMPTS, last_error)
    return MoodResult(
        mood=DEFAULT_MOOD,
        confidence=0.0,
        short_reason="Automatic classification was unavailable for this entry.",
        fallback=True,
    )


def generate_reflection(period_label: str, summary_data: str) -> str:
    """Generate a reflection summary from aggregated mood data.

    Only aggregated counts are sent, not full journal text, which keeps the
    request small and limits how much private content leaves AWS. Tries
    twice, since a transient error (e.g. a 503 while the model is under
    heavy load) should not immediately fall back to the local summary.
    """
    prompt = REFLECTION_PROMPT.format(
        period_label=period_label, summary_data=summary_data
    )

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _strip_fences(_generate(prompt)).strip()
        except Exception as exc:  # noqa: BLE001 - any failure should retry then raise
            last_error = exc
            logger.warning("Reflection generation attempt %d failed: %s", attempt, exc)
            _pause_before_retry(attempt)

    logger.error("Reflection generation failed after %d attempts: %s", MAX_ATTEMPTS, last_error)
    if isinstance(last_error, GeminiError):
        raise last_error
    raise GeminiError("Could not generate a reflection at this time.") from last_error

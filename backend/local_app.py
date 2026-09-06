"""Feature-complete local MoodJournal backend using RAM only.

Run from project root:

    python -m uvicorn backend.local_app:app --host 127.0.0.1 --port 8000 --reload

No AWS SDK or AWS credentials are required.  AWS/Lambda/SAM files are kept in
this project for the later deployment phase but are not imported here.
"""

from __future__ import annotations

import base64
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Existing Lambda-oriented modules import from "models", "utils", etc.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from models.journal_entry import JournalEntry, MOOD_SCORES, VALID_MOODS, utc_now_iso
from models.reflection import Reflection
from models.user import User
from repositories.memory_journal_repository import MemoryJournalRepository
from repositories.memory_user_repository import MemoryUserRepository, UsernameTakenError
from services import gemini_service
from services.local_mood_service import build_local_reflection, classify_mood_local
from utils.passwords import hash_password, verify_password
from utils.validation import (
    ValidationError,
    validate_content,
    validate_entry_date,
    validate_limit,
    validate_optional_date,
    validate_password,
    validate_period,
    validate_title,
    validate_username,
)

APP_ENV = os.getenv("APP_ENV", "local").lower()
JWT_SECRET = os.getenv("JWT_SECRET", "local-development-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = int(os.getenv("JWT_TTL_HOURS", "24"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if APP_ENV != "local":
    raise RuntimeError("backend.local_app is local-only. Set APP_ENV=local.")

app = FastAPI(
    title="MoodJournal Local API",
    version="1.1-local",
    description="Local RAM backend for testing MoodJournal before AWS deployment.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

users = MemoryUserRepository()
journals = MemoryJournalRepository()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AuthBody(BaseModel):
    username: str
    password: str


class ChangePasswordBody(BaseModel):
    currentPassword: str
    newPassword: str


class EntryBody(BaseModel):
    title: str | None = ""
    content: str
    entryDate: str | None = None


class ReflectionBody(BaseModel):
    period: str | None = "7d"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@app.exception_handler(HTTPException)
async def http_exception_handler(_request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        payload = {"error": detail}
    else:
        payload = {"error": {"code": "HTTP_ERROR", "message": str(detail)}}
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request, exc: Exception):
    # Keep the local API shape predictable without leaking tracebacks to the UI.
    print(f"Unhandled local API error: {exc!r}")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected local server error occurred.",
            }
        },
    )


def issue_token(user: User) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=JWT_TTL_HOURS)
    token = jwt.encode(
        {"sub": user.user_id, "username": user.username, "iat": now, "exp": exp},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return token, exp.isoformat(timespec="seconds")


def current_user(authorization: str | None) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise api_error(401, "UNAUTHORIZED", "Authentication is required.")

    token = authorization[7:].strip()
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise api_error(401, "UNAUTHORIZED", "Session has expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise api_error(401, "UNAUTHORIZED", "Invalid authentication token.")

    user = users.find_by_id(str(claims.get("sub", "")))
    if user is None:
        raise api_error(401, "UNAUTHORIZED", "User no longer exists.")
    return user


def classify(content: str):
    """Use Gemini when configured; otherwise use an explicit local fallback."""
    if GEMINI_API_KEY:
        result = gemini_service.classify_mood(content)
        if not result.fallback:
            return result
        # Gemini was configured but failed. Continue with a useful offline result.
    return classify_mood_local(content)


def date_range(days: int) -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    return start.isoformat(), today.isoformat()


def weekly_summary(entries: list[JournalEntry]) -> list[dict[str, Any]]:
    weeks: dict[str, list[JournalEntry]] = {}
    for entry in entries:
        d = date.fromisoformat(entry.entry_date)
        week_start = d - timedelta(days=d.weekday())
        weeks.setdefault(week_start.isoformat(), []).append(entry)

    output: list[dict[str, Any]] = []
    for week_start, week_entries in sorted(weeks.items(), reverse=True):
        counts = Counter(e.mood for e in week_entries)
        scores = [e.mood_score for e in week_entries]
        output.append(
            {
                "weekStart": week_start,
                "entryCount": len(week_entries),
                "averageScore": round(sum(scores) / len(scores), 2),
                "dominantMood": counts.most_common(1)[0][0],
                "moodCounts": {m: counts.get(m, 0) for m in VALID_MOODS},
            }
        )
    return output


def encode_offset(offset: int | None) -> str | None:
    if offset is None:
        return None
    raw = str(offset).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_offset(token: str | None) -> int:
    if not token:
        return 0
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        offset = int(raw)
        if offset < 0:
            raise ValueError
        return offset
    except Exception as exc:  # noqa: BLE001
        raise api_error(400, "VALIDATION_ERROR", "Invalid pagination token.") from exc


# ---------------------------------------------------------------------------
# Health / auth
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mode": "local",
        "storage": "memory",
        "awsConnected": False,
        "geminiConfigured": bool(GEMINI_API_KEY),
        "moodFallback": "local-keyword" if not GEMINI_API_KEY else "gemini-with-local-fallback",
    }


@app.post("/auth/register", status_code=201)
def register(body: AuthBody):
    try:
        username = validate_username(body.username)
        password = validate_password(body.password)
    except ValidationError as exc:
        raise api_error(400, "VALIDATION_ERROR", str(exc))

    try:
        user = users.create(User(username=username, password_hash=hash_password(password)))
    except UsernameTakenError:
        raise api_error(409, "CONFLICT", "That username is already taken.")

    token, expires_at = issue_token(user)
    return {"user": user.to_api(), "token": token, "expiresAt": expires_at}


@app.post("/auth/login")
def login(body: AuthBody):
    username = str(body.username).strip().lower()
    user = users.find_by_username(username)
    if user is None or not verify_password(body.password, user.password_hash):
        raise api_error(401, "INVALID_CREDENTIALS", "Invalid username or password.")

    token, expires_at = issue_token(user)
    return {"user": user.to_api(), "token": token, "expiresAt": expires_at}


@app.get("/auth/me")
def me(authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    return {"user": user.to_api()}


@app.post("/auth/change-password")
def change_password(body: ChangePasswordBody, authorization: str | None = Header(default=None)):
    user = current_user(authorization)

    if not verify_password(body.currentPassword, user.password_hash):
        raise api_error(401, "INVALID_CURRENT_PASSWORD", "Current password is incorrect.")

    try:
        new_password = validate_password(body.newPassword)
    except ValidationError as exc:
        raise api_error(400, "VALIDATION_ERROR", str(exc))

    if body.currentPassword == new_password:
        raise api_error(
            400,
            "VALIDATION_ERROR",
            "The new password must be different from the current password.",
        )

    users.update_password(user.user_id, hash_password(new_password), utc_now_iso())
    return {"message": "Password updated successfully."}


# ---------------------------------------------------------------------------
# Journal CRUD
# ---------------------------------------------------------------------------


@app.post("/entries", status_code=201)
def create_entry(body: EntryBody, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    try:
        title = validate_title(body.title)
        content = validate_content(body.content)
        entry_date = validate_entry_date(body.entryDate)
    except ValidationError as exc:
        raise api_error(400, "VALIDATION_ERROR", str(exc))

    mood = classify(content)
    entry = JournalEntry(
        user_id=user.user_id,
        title=title,
        content=content,
        entry_date=entry_date,
        mood=mood.mood,
        confidence=mood.confidence,
        short_reason=mood.short_reason,
        classification_fallback=mood.fallback,
    )
    journals.put_entry(entry)
    return {"entry": entry.to_api()}


@app.get("/entries")
def list_entries(
    authorization: str | None = Header(default=None),
    mood: str | None = Query(default=None),
    startDate: str | None = Query(default=None),
    endDate: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: str | None = Query(default=None),
    nextToken: str | None = Query(default=None),
):
    user = current_user(authorization)
    try:
        normalized_mood = mood.upper() if mood else None
        if normalized_mood and normalized_mood not in VALID_MOODS:
            raise ValidationError("Mood must be one of: " + ", ".join(VALID_MOODS) + ".")
        start = validate_optional_date(startDate, "startDate")
        end = validate_optional_date(endDate, "endDate")
        page_size = validate_limit(limit)
    except ValidationError as exc:
        raise api_error(400, "VALIDATION_ERROR", str(exc))

    if start and end and start > end:
        raise api_error(400, "VALIDATION_ERROR", "startDate must be on or before endDate.")

    offset = decode_offset(nextToken)
    entries, next_offset = journals.list_entries(
        user.user_id,
        mood=normalized_mood,
        start_date=start,
        end_date=end,
        search=search,
        limit=page_size,
        offset=offset,
    )
    return {
        "entries": [e.to_api() for e in entries],
        "count": len(entries),
        "nextToken": encode_offset(next_offset),
    }


@app.get("/entries/{entry_id}")
def get_entry(entry_id: str, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    entry = journals.get_entry(user.user_id, entry_id)
    if entry is None:
        raise api_error(404, "NOT_FOUND", "Entry not found.")
    return {"entry": entry.to_api()}


@app.put("/entries/{entry_id}")
def update_entry(
    entry_id: str,
    body: EntryBody,
    authorization: str | None = Header(default=None),
):
    user = current_user(authorization)
    existing = journals.get_entry(user.user_id, entry_id)
    if existing is None:
        raise api_error(404, "NOT_FOUND", "Entry not found.")

    try:
        title = validate_title(body.title)
        content = validate_content(body.content)
        entry_date = validate_entry_date(body.entryDate)
    except ValidationError as exc:
        raise api_error(400, "VALIDATION_ERROR", str(exc))

    mood = classify(content)
    updated = JournalEntry(
        user_id=user.user_id,
        title=title,
        content=content,
        entry_date=entry_date,
        mood=mood.mood,
        confidence=mood.confidence,
        short_reason=mood.short_reason,
        classification_fallback=mood.fallback,
        entry_id=existing.entry_id,
        created_at=existing.created_at,
        updated_at=utc_now_iso(),
    )
    journals.put_entry(updated)
    return {"entry": updated.to_api()}


@app.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: str, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    existing = journals.get_entry(user.user_id, entry_id)
    if existing is None:
        raise api_error(404, "NOT_FOUND", "Entry not found.")
    journals.delete_entry(user.user_id, existing)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@app.get("/dashboard")
def dashboard(period: str = "7d", authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    try:
        days = validate_period(period)
    except ValidationError as exc:
        raise api_error(400, "VALIDATION_ERROR", str(exc))

    start, end = date_range(days)
    entries = journals.list_entries_in_range(user.user_id, start, end)
    total = len(entries)
    counts = Counter(e.mood for e in entries)
    scores = [e.mood_score for e in entries]

    distribution = [
        {
            "mood": mood_name,
            "count": counts.get(mood_name, 0),
            "percentage": round(counts.get(mood_name, 0) / total * 100, 1) if total else 0.0,
        }
        for mood_name in VALID_MOODS
    ]

    by_day: dict[str, list[int]] = {}
    for entry in entries:
        by_day.setdefault(entry.entry_date, []).append(entry.mood_score)
    trend = [
        {
            "date": day,
            "averageScore": round(sum(values) / len(values), 2),
            "entryCount": len(values),
        }
        for day, values in sorted(by_day.items())
    ]

    result = {
        "period": f"{days}d",
        "periodStart": start,
        "periodEnd": end,
        "totalEntries": total,
        "entriesInPeriod": total,
        "mostCommonMood": counts.most_common(1)[0][0] if counts else None,
        "averageScore": round(sum(scores) / len(scores), 2) if scores else None,
        "moodDistribution": distribution,
        "moodTrend": trend,
        "weeklySummary": weekly_summary(entries),
        "scoreMapping": MOOD_SCORES,
        "scoreNote": (
            "Mood scores are used only to visualise trends. "
            "They are not a measurement of wellbeing."
        ),
    }
    return {"dashboard": result}


# ---------------------------------------------------------------------------
# Reflections
# ---------------------------------------------------------------------------


@app.post("/reflections", status_code=201)
def create_reflection(body: ReflectionBody, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    try:
        days = validate_period(body.period)
    except ValidationError as exc:
        raise api_error(400, "VALIDATION_ERROR", str(exc))

    start, end = date_range(days)
    entries = journals.list_entries_in_range(user.user_id, start, end)
    if not entries:
        raise api_error(400, "NO_ENTRIES", "There are no entries in this period to reflect on.")

    generated_by = "local-fallback"
    summary: str

    if GEMINI_API_KEY:
        counts = Counter(e.mood for e in entries)
        scores = [e.mood_score for e in entries]
        summary_data = (
            f"Total entries: {len(entries)}\n"
            f"Average mood score: {sum(scores) / len(scores):.2f}\n"
            + "\n".join(f"{mood}: {count}" for mood, count in counts.items())
        )
        try:
            summary = gemini_service.generate_reflection(f"the last {days} days", summary_data)
            generated_by = "gemini"
        except Exception:  # noqa: BLE001 - local fallback is intentional
            summary = build_local_reflection(entries, days)
    else:
        summary = build_local_reflection(entries, days)

    reflection = Reflection(
        user_id=user.user_id,
        period=f"{days}d",
        period_start=start,
        period_end=end,
        summary=summary,
        entry_count=len(entries),
        generated_by=generated_by,
    )
    journals.put_reflection(reflection)
    return {"reflection": reflection.to_api()}


@app.get("/reflections")
def list_reflections(
    authorization: str | None = Header(default=None),
    limit: str | None = Query(default=None),
    nextToken: str | None = Query(default=None),
):
    user = current_user(authorization)
    try:
        page_size = validate_limit(limit)
    except ValidationError as exc:
        raise api_error(400, "VALIDATION_ERROR", str(exc))

    offset = decode_offset(nextToken)
    items, next_offset = journals.list_reflections(user.user_id, limit=page_size, offset=offset)
    return {
        "reflections": [r.to_api() for r in items],
        "count": len(items),
        "nextToken": encode_offset(next_offset),
    }


# ---------------------------------------------------------------------------
# AWS-only placeholders — explicit rather than accidentally invoking AWS
# ---------------------------------------------------------------------------


@app.post("/analytics/export")
def analytics_export(authorization: str | None = Header(default=None)):
    current_user(authorization)
    raise api_error(
        501,
        "NOT_AVAILABLE_IN_LOCAL_MODE",
        "Analytics export is available after AWS deployment.",
    )


@app.get("/analytics/athena")
def athena_query(authorization: str | None = Header(default=None)):
    current_user(authorization)
    raise api_error(
        501,
        "NOT_AVAILABLE_IN_LOCAL_MODE",
        "Athena analytics is available after AWS deployment.",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.local_app:app", host="127.0.0.1", port=8000, reload=False)

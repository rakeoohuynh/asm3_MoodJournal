from __future__ import annotations

import os
from datetime import date, timedelta

os.environ["APP_ENV"] = "local"
os.environ["JWT_SECRET"] = "pytest-local-secret-at-least-32-bytes-long"
os.environ.pop("GEMINI_API_KEY", None)

from fastapi.testclient import TestClient

from backend.local_app import app
from repositories.memory_store import reset_memory_store

client = TestClient(app)


def setup_function():
    reset_memory_store()


def register(username="alice", password="Password123"):
    r = client.post("/auth/register", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_is_local_ram_and_no_aws():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["storage"] == "memory"
    assert r.json()["awsConnected"] is False


def test_register_login_me_and_change_password():
    data = register()
    token = data["token"]
    assert data["user"]["username"] == "alice"
    assert "passwordHash" not in data["user"]

    me = client.get("/auth/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "alice"

    wrong = client.post("/auth/login", json={"username": "alice", "password": "Wrong1234"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"

    change = client.post(
        "/auth/change-password",
        headers=auth_headers(token),
        json={"currentPassword": "Password123", "newPassword": "NewPassword456"},
    )
    assert change.status_code == 200

    old_login = client.post("/auth/login", json={"username": "alice", "password": "Password123"})
    assert old_login.status_code == 401
    new_login = client.post("/auth/login", json={"username": "alice", "password": "NewPassword456"})
    assert new_login.status_code == 200


def test_duplicate_username_is_rejected_case_insensitively():
    register("Alice")
    r = client.post("/auth/register", json={"username": " alice ", "password": "Password456"})
    assert r.status_code == 409


def test_entry_crud_search_filter_and_dashboard():
    token = register()["token"]
    h = auth_headers(token)

    today = date.today()
    entries = [
        {"entryDate": today.isoformat(), "title": "Great day", "content": "I feel happy, proud and excited today."},
        {"entryDate": (today - timedelta(days=1)).isoformat(), "title": "Deadline", "content": "I am stressed and worried about the deadline."},
        {"entryDate": (today - timedelta(days=2)).isoformat(), "title": "Normal", "content": "I worked on my project and went home."},
    ]
    created = []
    for payload in entries:
        r = client.post("/entries", headers=h, json=payload)
        assert r.status_code == 201, r.text
        created.append(r.json()["entry"])

    assert created[0]["mood"] == "POSITIVE"
    assert created[1]["mood"] == "ANXIOUS"
    assert created[2]["mood"] == "NEUTRAL"
    assert all(e["classificationFallback"] for e in created)

    listing = client.get("/entries?limit=20", headers=h)
    assert listing.status_code == 200
    assert len(listing.json()["entries"]) == 3

    search = client.get("/entries?search=deadline", headers=h)
    assert search.status_code == 200
    assert len(search.json()["entries"]) == 1
    assert search.json()["entries"][0]["title"] == "Deadline"

    positive = client.get("/entries?mood=POSITIVE", headers=h)
    assert len(positive.json()["entries"]) == 1

    entry_id = created[2]["entryId"]
    get_one = client.get(f"/entries/{entry_id}", headers=h)
    assert get_one.status_code == 200

    updated = client.put(
        f"/entries/{entry_id}",
        headers=h,
        json={"entryDate": (today - timedelta(days=2)).isoformat(), "title": "Better", "content": "I feel great and happy now."},
    )
    assert updated.status_code == 200
    assert updated.json()["entry"]["mood"] == "POSITIVE"

    dashboard = client.get("/dashboard?period=7d", headers=h)
    assert dashboard.status_code == 200
    d = dashboard.json()["dashboard"]
    assert d["totalEntries"] == 3
    assert d["averageScore"] is not None
    assert len(d["moodDistribution"]) == 4

    deleted = client.delete(f"/entries/{entry_id}", headers=h)
    assert deleted.status_code == 204
    missing = client.get(f"/entries/{entry_id}", headers=h)
    assert missing.status_code == 404


def test_reflection_works_without_gemini_key():
    token = register()["token"]
    h = auth_headers(token)
    client.post(
        "/entries",
        headers=h,
        json={"entryDate": date.today().isoformat(), "title": "Today", "content": "I had a great and happy day."},
    )

    r = client.post("/reflections", headers=h, json={"period": "7d"})
    assert r.status_code == 201, r.text
    reflection = r.json()["reflection"]
    assert reflection["generatedBy"] == "local-fallback"
    assert "local test version" in reflection["summary"].lower()

    listing = client.get("/reflections", headers=h)
    assert listing.status_code == 200
    assert len(listing.json()["reflections"]) == 1


def test_user_data_isolation():
    alice = register("alice")["token"]
    bob = register("bob")["token"]
    ah = auth_headers(alice)
    bh = auth_headers(bob)

    created = client.post(
        "/entries",
        headers=ah,
        json={"entryDate": date.today().isoformat(), "title": "Private", "content": "Alice only entry"},
    ).json()["entry"]

    bob_list = client.get("/entries", headers=bh)
    assert bob_list.status_code == 200
    assert bob_list.json()["entries"] == []

    bob_get = client.get(f"/entries/{created['entryId']}", headers=bh)
    assert bob_get.status_code == 404


def test_protected_routes_reject_missing_token():
    assert client.get("/entries").status_code == 401
    assert client.get("/dashboard").status_code == 401
    assert client.get("/reflections").status_code == 401


def test_pagination_returns_all_entries_without_duplicates():
    token = register()["token"]
    h = auth_headers(token)
    for i in range(25):
        r = client.post(
            "/entries",
            headers=h,
            json={
                "entryDate": date.today().isoformat(),
                "title": f"Entry {i}",
                "content": f"A normal journal entry number {i}",
            },
        )
        assert r.status_code == 201

    first = client.get("/entries?limit=20", headers=h).json()
    assert len(first["entries"]) == 20
    assert first["nextToken"]

    second = client.get(f"/entries?limit=20&nextToken={first['nextToken']}", headers=h).json()
    assert len(second["entries"]) == 5
    assert second["nextToken"] is None

    ids = [e["entryId"] for e in first["entries"] + second["entries"]]
    assert len(ids) == len(set(ids)) == 25

"""Phase 1 password gate.

The most important case here is the first one: with LOCUS_AUTH_PASSWORD unset
the gate must be completely absent, because every other test module in this
suite calls the API without a token.
"""

import os

import pytest

os.environ["LOCUS_DATABASE_URL"] = "sqlite:///./test_locus.db"

from fastapi.testclient import TestClient

from backend.app import auth as auth_module
from sqlalchemy import select

from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.models import SecretChatMessage


PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def reset_login_throttle():
    auth_module._login_failures.clear()
    yield
    auth_module._login_failures.clear()


@pytest.fixture
def client():
    # Other modules delete test_locus.db in their teardown; disposing drops any
    # pooled connection still pointing at that removed file.
    engine.dispose()
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


def teardown_module():
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("test_locus.db"):
        os.remove("test_locus.db")
    # Removing the file out from under pooled connections leaves them pointing at
    # a deleted inode, which SQLite reports as "readonly database" in whichever
    # module runs next. Dispose so the next connection opens a fresh file.
    engine.dispose()


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setenv("LOCUS_AUTH_PASSWORD", PASSWORD)


def sign_in(client) -> str:
    response = client.post("/api/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return response.json()["token"]


def test_gate_is_absent_without_a_configured_password(client, monkeypatch):
    monkeypatch.delenv("LOCUS_AUTH_PASSWORD", raising=False)
    assert client.get("/api/auth/status").json() == {"auth_required": False, "authenticated": False, "expires_at": None}
    assert client.get("/api/collections").status_code == 200


def test_guarded_routes_reject_missing_and_forged_tokens(client, locked):
    assert client.get("/api/collections").status_code == 401
    assert client.get("/api/collections", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    payload, _, signature = sign_in(client).partition(".")
    tampered = f"{payload}.{signature[:-4]}xxxx"
    assert client.get("/api/collections", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401


def test_login_returns_a_token_that_opens_guarded_routes(client, locked):
    headers = {"Authorization": f"Bearer {sign_in(client)}"}
    assert client.get("/api/collections", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).json()["authenticated"] is True


def test_login_rejects_the_wrong_password(client, locked):
    response = client.post("/api/auth/login", json={"password": "guess"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect password"


def test_login_throttles_repeated_failures(client, locked):
    for _ in range(auth_module.LOGIN_MAX_FAILURES):
        assert client.post("/api/auth/login", json={"password": "guess"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "guess"}).status_code == 429
    # The throttle must hold even once the caller finally guesses right.
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 429


def test_health_and_status_stay_public(client, locked):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/status").json()["auth_required"] is True


def test_rotating_the_password_invalidates_issued_tokens(client, locked, monkeypatch):
    headers = {"Authorization": f"Bearer {sign_in(client)}"}
    monkeypatch.setenv("LOCUS_AUTH_PASSWORD", "a different password")
    assert client.get("/api/collections", headers=headers).status_code == 401


def test_expired_tokens_are_rejected(client, locked, monkeypatch):
    monkeypatch.setattr(auth_module, "_session_seconds", lambda: -1)
    token = sign_in(client)
    assert auth_module.token_expiry(token) is None
    assert client.get("/api/collections", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_guests_can_use_a_shared_room_but_not_manage_rooms(client, locked):
    headers = {"Authorization": f"Bearer {sign_in(client)}"}
    token = client.post("/api/secret-chat", headers=headers).json()["token"]

    # A guest holds the link and nothing else.
    assert client.get(f"/api/secret-chat/{token}").status_code == 200
    assert client.get(f"/api/secret-chat/{token}/messages").status_code == 200
    assert client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Guest", "content": "hi"}).status_code == 201

    # Everything that manages rooms belongs to the host.
    assert client.post("/api/secret-chat").status_code == 401
    assert client.get("/api/secret-chat").status_code == 401
    assert client.patch(f"/api/secret-chat/{token}", json={"title": "Renamed"}).status_code == 401
    assert client.delete(f"/api/secret-chat/{token}").status_code == 401


def test_host_lists_renames_and_deletes_rooms(client, locked):
    headers = {"Authorization": f"Bearer {sign_in(client)}"}
    first = client.post("/api/secret-chat", headers=headers).json()["token"]
    second = client.post("/api/secret-chat", headers=headers).json()["token"]
    client.post(f"/api/secret-chat/{first}/messages", json={"sender": "Guest", "content": "hi"})

    assert client.patch(f"/api/secret-chat/{first}", json={"title": "Design review"}, headers=headers).status_code == 200

    rooms = client.get("/api/secret-chat", headers=headers).json()
    by_token = {room["token"]: room for room in rooms}
    assert by_token[first]["title"] == "Design review"
    assert by_token[first]["message_count"] == 1
    assert by_token[second]["message_count"] == 0

    assert client.delete(f"/api/secret-chat/{second}", headers=headers).status_code == 204
    # Other tests share this database, so check these two tokens rather than the whole list.
    remaining = {room["token"] for room in client.get("/api/secret-chat", headers=headers).json()}
    assert first in remaining and second not in remaining


def test_deleting_a_room_revokes_its_link(client, locked):
    headers = {"Authorization": f"Bearer {sign_in(client)}"}
    token = client.post("/api/secret-chat", headers=headers).json()["token"]
    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Guest", "content": "hi"})

    assert client.delete(f"/api/secret-chat/{token}", headers=headers).status_code == 204

    # Every guest-facing route the link could reach is now a dead end.
    assert client.get(f"/api/secret-chat/{token}").status_code == 404
    assert client.get(f"/api/secret-chat/{token}/messages").status_code == 404
    assert client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Guest", "content": "again"}).status_code == 404
    assert client.get(f"/api/secret-chat/{token}/stream").status_code == 404

    # The messages went with it rather than lingering for a recreated token.
    with SessionLocal() as db:
        assert db.scalars(select(SecretChatMessage).where(SecretChatMessage.session_token == token)).all() == []


def test_rooms_stay_open_when_no_password_is_configured(client, monkeypatch):
    monkeypatch.delenv("LOCUS_AUTH_PASSWORD", raising=False)
    token = client.post("/api/secret-chat").json()["token"]
    assert client.get("/api/secret-chat").status_code == 200
    assert client.delete(f"/api/secret-chat/{token}").status_code == 204

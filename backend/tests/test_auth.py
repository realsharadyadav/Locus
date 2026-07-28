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
from backend.app.database import Base, engine
from backend.app.main import app


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


def test_health_and_secret_chat_stay_public(client, locked):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/status").json()["auth_required"] is True
    created = client.post("/api/secret-chat")
    assert created.status_code == 201
    token = created.json()["token"]
    assert client.get(f"/api/secret-chat/{token}").status_code == 200
    assert client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Guest", "content": "hi"}).status_code == 201


def test_rotating_the_password_invalidates_issued_tokens(client, locked, monkeypatch):
    headers = {"Authorization": f"Bearer {sign_in(client)}"}
    monkeypatch.setenv("LOCUS_AUTH_PASSWORD", "a different password")
    assert client.get("/api/collections", headers=headers).status_code == 401


def test_expired_tokens_are_rejected(client, locked, monkeypatch):
    monkeypatch.setattr(auth_module, "_session_seconds", lambda: -1)
    token = sign_in(client)
    assert auth_module.token_expiry(token) is None
    assert client.get("/api/collections", headers={"Authorization": f"Bearer {token}"}).status_code == 401

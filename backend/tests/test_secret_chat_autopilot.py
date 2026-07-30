"""Autopilot answers from the server, so the host's browser does not have to be open.

It also has to look like a person did it: a pause before the reply, a typing indicator while
it is "writing", and no marker in the thread that a guest could read as "this was a bot".
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import SecretChatMessage, SecretChatParticipant, SecretChatSession, UserPreference
import backend.app.secret_chat as secret_chat

HOST = {"host_key": "autopilot-host"}


@pytest.fixture(autouse=True)
def instant_pauses(monkeypatch):
    """Keep the human pauses out of the test clock, but record that they happened."""
    slept = []
    monkeypatch.setattr(secret_chat.time, "sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(secret_chat.random, "uniform", lambda low, high: (low + high) / 2)
    return slept


@pytest.fixture(autouse=True)
def clean_rooms():
    yield
    with SessionLocal() as db:
        db.query(SecretChatMessage).delete()
        db.query(SecretChatParticipant).delete()
        db.query(SecretChatSession).delete()
        db.query(UserPreference).delete()
        db.commit()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _room_with_host(client, **options):
    token = client.post("/api/secret-chat", json={**HOST, **options}).json()["token"]
    client.post(f"/api/secret-chat/{token}/presence", json={
        "client_id": "host-client", "name": "Sharad", "role": "host", **HOST,
    })
    client.patch(f"/api/secret-chat/{token}", json={**HOST, "ai_autopilot": True})
    return token


def _replies(monkeypatch, text="on my way"):
    captured = {}

    def fake_chat(system, prompt, model, **kwargs):
        captured["model"] = model
        captured["system"] = system
        captured["prompt"] = prompt
        return f'{{"replies": ["{text}"]}}'

    monkeypatch.setattr(secret_chat, "_chat", fake_chat)
    return captured


def test_guest_message_gets_an_answer_without_the_host_present(client, monkeypatch, instant_pauses):
    token = _room_with_host(client)
    captured = _replies(monkeypatch, "almost there")

    # Only the guest posts — nothing here stands in for the host's browser.
    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Riya|||guest-1", "content": "where are you?"})
    for thread in [t for t in __import__("threading").enumerate() if t.name.startswith("locus-autopilot")]:
        thread.join(timeout=10)

    messages = client.get(f"/api/secret-chat/{token}/messages").json()
    assert [m["content"] for m in messages] == ["where are you?", "almost there"]
    reply = messages[-1]
    assert reply["sender"] == "Sharad|||host-client", "the reply must come from the host, not a bot identity"
    assert reply["via_ai"] is True, "stored as AI so it is excluded from talk-like-me samples"
    assert captured["prompt"].count("where are you?") == 1


def test_the_reply_waits_like_a_person(client, monkeypatch, instant_pauses):
    token = _room_with_host(client)
    _replies(monkeypatch, "yeah give me five minutes, just leaving now")

    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Riya|||guest-1", "content": "you coming?"})
    for thread in [t for t in __import__("threading").enumerate() if t.name.startswith("locus-autopilot")]:
        thread.join(timeout=10)

    assert len(instant_pauses) == 2, "expected a pause before writing and time spent typing"
    notice, typing = instant_pauses
    assert 1.0 <= notice <= 5.0, f"noticing the message took {notice}s"
    # Longer replies take longer to type.
    assert typing > secret_chat._autopilot_typing_seconds("ok")


def test_autopilot_uses_the_model_chosen_in_settings(client, monkeypatch):
    token = _room_with_host(client)
    with SessionLocal() as db:
        db.add(UserPreference(key="explore_ai", value={"provider": "groq", "model": "settings-choice-model"}))
        db.commit()
    captured = _replies(monkeypatch)

    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Riya|||guest-1", "content": "hi"})
    for thread in [t for t in __import__("threading").enumerate() if t.name.startswith("locus-autopilot")]:
        thread.join(timeout=10)

    assert captured["model"] == "settings-choice-model"


def test_suggestions_also_use_the_settings_model(client, monkeypatch):
    token = _room_with_host(client)
    with SessionLocal() as db:
        db.add(UserPreference(key="explore_ai", value={"model": "settings-choice-model"}))
        db.commit()
    captured = _replies(monkeypatch)

    response = client.post(f"/api/secret-chat/{token}/assist", json={**HOST, "client_id": "host-client"})
    assert response.status_code == 200
    assert response.json()["model"] == "settings-choice-model"
    assert captured["model"] == "settings-choice-model"


def test_autopilot_ignores_its_own_and_the_hosts_messages(client, monkeypatch):
    token = _room_with_host(client)
    _replies(monkeypatch)

    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Sharad|||host-client", "content": "typed by me"})
    client.post(f"/api/secret-chat/{token}/messages", json={
        "sender": "Sharad|||host-client", "content": "drafted earlier", "via_ai": True,
    })
    for thread in [t for t in __import__("threading").enumerate() if t.name.startswith("locus-autopilot")]:
        thread.join(timeout=10)

    contents = [m["content"] for m in client.get(f"/api/secret-chat/{token}/messages").json()]
    assert contents == ["typed by me", "drafted earlier"], "autopilot should not answer itself or the host"


def test_nothing_happens_while_autopilot_is_off(client, monkeypatch):
    token = client.post("/api/secret-chat", json=HOST).json()["token"]
    client.post(f"/api/secret-chat/{token}/presence", json={
        "client_id": "host-client", "name": "Sharad", "role": "host", **HOST,
    })
    _replies(monkeypatch)

    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Riya|||guest-1", "content": "hello?"})
    for thread in [t for t in __import__("threading").enumerate() if t.name.startswith("locus-autopilot")]:
        thread.join(timeout=10)

    assert len(client.get(f"/api/secret-chat/{token}/messages").json()) == 1

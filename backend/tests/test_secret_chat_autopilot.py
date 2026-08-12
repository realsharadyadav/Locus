"""Autopilot answers from the server, so the host's browser does not have to be open.

It also has to look like a person did it: a pause before the reply, a typing indicator while
it is "writing", and no marker in the thread that a guest could read as "this was a bot".

That "writing" stretch doubles as a review window: the draft is held in memory, readable by
the host alone, and the host can stop it or push it out early before it lands.
"""

import time

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

    def instant_hold(entry):
        """The review window is real wall-clock time; note its length and let the draft go."""
        slept.append(entry["hold_seconds"])
        return entry["action"] if entry["decision"].is_set() else "send"

    monkeypatch.setattr(secret_chat, "_wait_for_decision", instant_hold)
    return slept


@pytest.fixture()
def held_drafts(monkeypatch):
    """Hold drafts for real, so a test can act on one the way the host's browser would."""
    def blocking_hold(entry):
        entry["decision"].wait(10)
        return entry["action"]

    monkeypatch.setattr(secret_chat, "_wait_for_decision", blocking_hold)


def _await_draft(client, token):
    """Wait for the worker to draft a reply and put it up for review.

    `time.sleep` is stubbed out module-wide by `instant_pauses`, so this spins on the clock
    instead — it returns as soon as the worker thread gets there, typically first try.
    """
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        pending = client.get(f"/api/secret-chat/{token}/autopilot", params=HOST).json()["pending"]
        if pending:
            return pending
    raise AssertionError("autopilot never held a draft for review")


def _join_autopilot_threads():
    for thread in [t for t in __import__("threading").enumerate() if t.name.startswith("locus-autopilot")]:
        thread.join(timeout=10)


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
    # However short the reply, the host gets long enough to read it and say no.
    assert secret_chat._autopilot_hold_seconds("ok") >= secret_chat.AUTOPILOT_REVIEW_MIN_SECONDS


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


def test_the_host_sees_the_draft_before_it_is_sent(client, monkeypatch, held_drafts):
    token = _room_with_host(client)
    _replies(monkeypatch, "five minutes away")

    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Riya|||guest-1", "content": "where are you?"})
    pending = _await_draft(client, token)

    assert pending["content"] == "five minutes away"
    assert pending["remaining_seconds"] > 0, "the host needs time left to act on it"
    assert pending["hold_seconds"] >= secret_chat.AUTOPILOT_REVIEW_MIN_SECONDS
    # Nothing is in the room yet — the draft only exists in memory.
    assert [m["content"] for m in client.get(f"/api/secret-chat/{token}/messages").json()] == ["where are you?"]

    sent = client.post(f"/api/secret-chat/{token}/autopilot", json={
        **HOST, "draft_id": pending["id"], "action": "send",
    })
    assert sent.json()["status"] == "sending"
    _join_autopilot_threads()

    assert [m["content"] for m in client.get(f"/api/secret-chat/{token}/messages").json()] == [
        "where are you?", "five minutes away",
    ]
    assert client.get(f"/api/secret-chat/{token}/autopilot", params=HOST).json()["pending"] is None


def test_the_host_can_stop_a_reply_before_it_lands(client, monkeypatch, held_drafts):
    token = _room_with_host(client)
    _replies(monkeypatch, "sure, tonight works")

    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Riya|||guest-1", "content": "dinner?"})
    pending = _await_draft(client, token)

    stopped = client.post(f"/api/secret-chat/{token}/autopilot", json={
        **HOST, "draft_id": pending["id"], "action": "cancel",
    })
    assert stopped.json()["status"] == "stopped"
    _join_autopilot_threads()

    assert [m["content"] for m in client.get(f"/api/secret-chat/{token}/messages").json()] == ["dinner?"]
    assert client.get(f"/api/secret-chat/{token}/autopilot", params=HOST).json()["pending"] is None
    # The typing indicator has to stop too, or the room shows the host typing forever.
    participants = client.post(f"/api/secret-chat/{token}/presence", json={
        "client_id": "guest-1", "name": "Riya", "role": "guest",
    }).json()["participants"]
    assert not any(item["typing"] for item in participants)


def test_switching_autopilot_off_stops_the_held_reply(client, monkeypatch, held_drafts):
    token = _room_with_host(client)
    _replies(monkeypatch, "on my way")

    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Riya|||guest-1", "content": "coming?"})
    _await_draft(client, token)

    client.patch(f"/api/secret-chat/{token}", json={**HOST, "ai_autopilot": False})
    _join_autopilot_threads()

    assert [m["content"] for m in client.get(f"/api/secret-chat/{token}/messages").json()] == ["coming?"]


def test_the_host_answering_by_hand_stops_the_held_reply(client, monkeypatch, held_drafts):
    token = _room_with_host(client)
    _replies(monkeypatch, "drafted answer")

    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Riya|||guest-1", "content": "you there?"})
    _await_draft(client, token)

    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Sharad|||host-client", "content": "yep, here"})
    _join_autopilot_threads()

    assert [m["content"] for m in client.get(f"/api/secret-chat/{token}/messages").json()] == [
        "you there?", "yep, here",
    ], "the host said it themselves, so the draft must not follow"


def test_a_guest_cannot_see_the_held_draft(client, monkeypatch, held_drafts):
    token = _room_with_host(client)
    _replies(monkeypatch, "secret draft")

    client.post(f"/api/secret-chat/{token}/messages", json={"sender": "Riya|||guest-1", "content": "hello?"})
    _await_draft(client, token)

    assert client.get(f"/api/secret-chat/{token}/autopilot").status_code == 403
    assert client.get(f"/api/secret-chat/{token}/autopilot", params={"host_key": "not-the-host"}).status_code == 403
    assert client.post(f"/api/secret-chat/{token}/autopilot", json={
        "host_key": "not-the-host", "action": "cancel",
    }).status_code == 403

    client.post(f"/api/secret-chat/{token}/autopilot", json={**HOST, "action": "cancel"})
    _join_autopilot_threads()


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

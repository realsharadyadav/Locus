"""Private chat: room lifecycle, presence, disappearing messages and the reply copilot."""

from datetime import datetime, timedelta

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import SecretChatMessage, SecretChatParticipant, SecretChatSession
import backend.app.secret_chat as secret_chat

HOST = {"host_key": "host-key-1"}
DEVICE_HEADERS = {
    "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
}


def _clear_private_chat_tables():
    with SessionLocal() as db:
        db.execute(delete(SecretChatMessage))
        db.execute(delete(SecretChatParticipant))
        db.execute(delete(SecretChatSession))
        db.commit()


def setup_module():
    # conftest.py owns the database URL and hands every module an empty schema, so there is
    # no sqlite file being deleted under this engine any more (see AGENTS.md note 16).
    _clear_private_chat_tables()


def teardown_module():
    _clear_private_chat_tables()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def create_room(client, **options):
    response = client.post("/api/secret-chat", json={**HOST, **options})
    assert response.status_code == 201
    return response.json()["token"]


def send(client, token, sender, content):
    response = client.post(f"/api/secret-chat/{token}/messages", json={"sender": sender, "content": content})
    assert response.status_code == 201
    return response.json()


def rewind(token, **columns):
    """Move a room's clock into the past so expiry paths can be tested without waiting."""
    with SessionLocal() as db:
        session = db.get(SecretChatSession, token)
        for column, value in columns.items():
            setattr(session, column, value)
        db.commit()


def test_create_stores_options_and_share_url(client):
    response = client.post("/api/secret-chat", json={
        **HOST,
        "title": "Weekend plan",
        "message_ttl_seconds": 300,
        "link_expiry_minutes": 30,
        "room_expiry_minutes": 120,
    })
    assert response.status_code == 201
    token = response.json()["token"]
    assert response.json()["url"].endswith(f"/j/{token}")

    room = client.get(f"/api/secret-chat/{token}", params=HOST).json()
    assert room["title"] == "Weekend plan"
    assert room["message_ttl_seconds"] == 300
    assert room["link_expires_at"] and room["expires_at"]
    assert room["link_expired"] is False


def test_host_only_actions_reject_guests(client):
    token = create_room(client)
    assert client.get(f"/api/secret-chat/{token}/participants", params={"host_key": "wrong"}).status_code == 403
    assert client.delete(f"/api/secret-chat/{token}/messages", params={"host_key": "wrong"}).status_code == 403
    assert client.delete(f"/api/secret-chat/{token}", params={"host_key": "wrong"}).status_code == 403
    assert client.post(f"/api/secret-chat/{token}/assist", json={"host_key": ""}).status_code == 403
    assert client.patch(f"/api/secret-chat/{token}", json={"host_key": "wrong", "title": "nope"}).status_code == 403


def test_presence_records_device_details_for_the_host_only(client):
    token = create_room(client)
    client.post(f"/api/secret-chat/{token}/presence", json={
        "client_id": "guest-1", "name": "Riya", "typing": True,
        "language": "de-DE", "timezone": "Europe/Berlin", "screen": "390x844", "viewport": "390x700",
    }, headers=DEVICE_HEADERS)

    as_host = client.post(f"/api/secret-chat/{token}/presence", json={
        "client_id": "host-1", "name": "Sharad", "role": "host", **HOST,
    }).json()
    guest = next(item for item in as_host["participants"] if item["client_id"] == "guest-1")
    assert guest["typing"] is True and guest["online"] is True
    assert guest["device"] == "Phone" and guest["os"] == "iOS" and guest["browser"] == "Safari"
    assert guest["language"] == "de-DE" and guest["timezone"] == "Europe/Berlin"
    assert guest["screen"] == "390x844" and guest["ip"]

    # The same call made by a guest carries no device, IP or user-agent detail about anyone.
    as_guest = client.post(f"/api/secret-chat/{token}/presence", json={
        "client_id": "guest-1", "name": "Riya",
    }).json()
    assert all("ip" not in item and "user_agent" not in item for item in as_guest["participants"])


def test_read_cursor_drives_unread_counts(client):
    token = create_room(client, title="Unread room")
    client.post(f"/api/secret-chat/{token}/presence", json={"client_id": "host-1", "name": "Sharad", "role": "host", **HOST})
    send(client, token, "Riya|||guest-1", "you around?")
    send(client, token, "Riya|||guest-1", "hello?")

    rooms = client.get("/api/secret-chat", params={**HOST, "client_id": "host-1"}).json()
    room = next(item for item in rooms if item["token"] == token)
    assert room["unread_count"] == 2
    assert room["last_message_preview"] == "hello?"
    assert room["last_sender"] == "Riya"

    latest = room["last_message_id"]
    client.post(f"/api/secret-chat/{token}/presence", json={
        "client_id": "host-1", "name": "Sharad", "role": "host", "last_read_id": latest, **HOST,
    })
    rooms = client.get("/api/secret-chat", params={**HOST, "client_id": "host-1"}).json()
    assert next(item for item in rooms if item["token"] == token)["unread_count"] == 0

    # My own messages never count as unread for me.
    send(client, token, "Sharad|||host-1", "here now")
    rooms = client.get("/api/secret-chat", params={**HOST, "client_id": "host-1"}).json()
    assert next(item for item in rooms if item["token"] == token)["unread_count"] == 0


def test_disappearing_messages_are_purged_on_access(client):
    token = create_room(client, message_ttl_seconds=60)
    message = send(client, token, "Riya|||guest-1", "this vanishes")
    assert message["expires_at"] is not None

    rewind(token, message_ttl_seconds=1)
    with SessionLocal() as db:
        stored = db.get(SecretChatSession, token).messages[0]
        stored.created_at = datetime.utcnow() - timedelta(seconds=30)
        db.commit()

    assert client.get(f"/api/secret-chat/{token}/messages").json() == []


def test_clear_messages_keeps_the_room_alive(client):
    token = create_room(client)
    send(client, token, "Riya|||guest-1", "one")
    send(client, token, "Riya|||guest-1", "two")
    assert client.delete(f"/api/secret-chat/{token}/messages", params=HOST).status_code == 204
    assert client.get(f"/api/secret-chat/{token}/messages").json() == []
    assert client.get(f"/api/secret-chat/{token}", params=HOST).status_code == 200


def test_expired_link_admits_known_clients_but_not_new_ones(client):
    token = create_room(client, link_expiry_minutes=30)
    client.post(f"/api/secret-chat/{token}/presence", json={"client_id": "guest-1", "name": "Riya"})
    rewind(token, link_expires_at=datetime.utcnow() - timedelta(minutes=1))

    assert client.get(f"/api/secret-chat/{token}", params={"client_id": "newcomer"}).status_code == 403
    assert client.get(f"/api/secret-chat/{token}", params={"client_id": "guest-1"}).status_code == 200
    assert client.get(f"/api/secret-chat/{token}", params=HOST).status_code == 200
    assert client.get(f"/api/secret-chat/{token}", params=HOST).json()["link_expired"] is True


def test_expired_room_is_gone_for_everyone(client):
    token = create_room(client, room_expiry_minutes=60)
    send(client, token, "Riya|||guest-1", "still here")
    rewind(token, expires_at=datetime.utcnow() - timedelta(minutes=1))

    assert client.get(f"/api/secret-chat/{token}", params=HOST).status_code == 410
    # The data is destroyed on that first touch, not merely hidden.
    assert client.get(f"/api/secret-chat/{token}", params=HOST).status_code == 404


def test_delete_room_and_delete_all_rooms(client):
    first = create_room(client, title="One")
    second = create_room(client, title="Two")
    assert client.delete(f"/api/secret-chat/{first}", params=HOST).status_code == 204
    assert client.get(f"/api/secret-chat/{first}", params=HOST).status_code == 404

    other_host = client.post("/api/secret-chat", json={"host_key": "someone-else"}).json()["token"]
    assert client.delete("/api/secret-chat", params=HOST).status_code == 204
    assert client.get("/api/secret-chat", params=HOST).json() == []
    # Another host's rooms are untouched.
    assert client.get(f"/api/secret-chat/{other_host}", params={"host_key": "someone-else"}).status_code == 200
    assert second not in [room["token"] for room in client.get("/api/secret-chat", params=HOST).json()]


def test_rooms_made_before_host_keys_are_visible_claimable_and_deletable(client):
    """Rooms from an older build carry no host key; they must not become unreachable."""
    legacy = client.post("/api/secret-chat", json={}).json()["token"]
    mine = create_room(client, title="Owned")

    listed = {room["token"] for room in client.get("/api/secret-chat", params=HOST).json()}
    assert legacy in listed and mine in listed

    # Managing an unowned room claims it, after which another host key is refused.
    assert client.patch(f"/api/secret-chat/{legacy}", json={**HOST, "title": "Claimed"}).status_code == 200
    assert client.patch(f"/api/secret-chat/{legacy}", json={"host_key": "someone-else", "title": "no"}).status_code == 403

    second_legacy = client.post("/api/secret-chat", json={}).json()["token"]
    assert client.delete("/api/secret-chat", params=HOST).status_code == 204
    # Delete-all clears everything the list showed, including the unclaimed room.
    assert client.get("/api/secret-chat", params=HOST).json() == []
    assert client.get(f"/api/secret-chat/{second_legacy}").status_code == 404


def test_assist_uses_tone_persona_and_my_own_messages_as_style(client, monkeypatch):
    token = create_room(client, title="Copilot room")
    send(client, token, "Riya|||guest-1", "so are we still on for tonight?")
    send(client, token, "Sharad|||host-1", "yeah boss, 8pm works")
    send(client, token, "Sharad|||host-1", "lemme confirm the table")

    captured = {}

    def fake_chat(system, prompt, model, temperature=0.2, max_tokens=None, **kwargs):
        captured["system"] = system
        captured["prompt"] = prompt
        captured["model"] = model
        return '{"replies": ["booked it", "table is sorted", "all set for 8"]}'

    monkeypatch.setattr(secret_chat, "_chat", fake_chat)

    response = client.post(f"/api/secret-chat/{token}/assist", json={
        **HOST,
        "client_id": "host-1",
        "sender": "Sharad",
        "tone": "playful",
        "persona": "lowercase, dry humour",
        "mimic_me": True,
        "instruction": "confirm the booking",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["suggestions"] == ["booked it", "table is sorted", "all set for 8"]
    assert body["style_samples"] == 2

    assert "playful" in captured["system"]
    assert "lowercase, dry humour" in captured["system"]
    # Only my own messages are offered as style samples, never the other person's.
    assert "yeah boss, 8pm works" in captured["system"]
    assert "so are we still on for tonight?" not in captured["system"]
    # The transcript and my instruction go in the user prompt.
    assert "so are we still on for tonight?" in captured["prompt"]
    assert "confirm the booking" in captured["prompt"]


def test_assist_without_mimic_sends_no_style_samples(client, monkeypatch):
    token = create_room(client)
    send(client, token, "Sharad|||host-1", "my very distinctive phrasing")
    captured = {}

    def fake_chat(system, prompt, model, temperature=0.2, max_tokens=None, **kwargs):
        captured["system"] = system
        return "sure thing\nsounds good\nok"

    monkeypatch.setattr(secret_chat, "_chat", fake_chat)
    response = client.post(f"/api/secret-chat/{token}/assist", json={
        **HOST, "client_id": "host-1", "mimic_me": False,
    })
    assert response.status_code == 200
    # A model that ignores the JSON contract still yields usable lines.
    assert response.json()["suggestions"] == ["sure thing", "sounds good", "ok"]
    assert response.json()["style_samples"] == 0
    assert "my very distinctive phrasing" not in captured["system"]


def test_ai_messages_are_flagged_and_never_used_as_style_samples(client, monkeypatch):
    token = create_room(client)
    response = client.post(f"/api/secret-chat/{token}/messages", json={
        "sender": "Sharad|||host-1", "content": "drafted by the copilot", "via_ai": True,
    })
    assert response.status_code == 201 and response.json()["via_ai"] is True

    captured = {}

    def fake_chat(system, prompt, model, **kwargs):
        captured["system"] = system
        return '{"replies": ["ok"]}'

    monkeypatch.setattr(secret_chat, "_chat", fake_chat)
    client.post(f"/api/secret-chat/{token}/assist", json={**HOST, "client_id": "host-1", "mimic_me": True})
    assert "drafted by the copilot" not in captured["system"]


def test_copilot_settings_persist_on_the_room(client):
    token = create_room(client)
    updated = client.patch(f"/api/secret-chat/{token}", json={
        **HOST, "ai_tone": "flirty", "ai_persona": "short, teasing", "ai_autopilot": True, "ai_mimic_me": False,
    })
    assert updated.status_code == 200
    body = updated.json()
    assert body["ai_tone"] == "flirty"
    assert body["ai_persona"] == "short, teasing"
    assert body["ai_autopilot"] is True
    assert body["ai_mimic_me"] is False
    assert client.get(f"/api/secret-chat/{token}", params=HOST).json()["ai_autopilot"] is True

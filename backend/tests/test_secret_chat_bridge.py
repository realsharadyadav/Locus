"""The messenger bridge: talk to a phone number from a private chat room.

Telethon and a real Telegram account are replaced by a fake transport, so these tests
cover the part that is ours — routing, the echo guard, the synthetic participant, host-only
access and what a link guest is allowed to see — rather than the network.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import (
    SecretChatBridge,
    SecretChatMessage,
    SecretChatParticipant,
    SecretChatSession,
)
import backend.app.secret_chat as secret_chat
import backend.app.telegram_bridge as telegram_bridge

HOST = {"host_key": "bridge-host"}
GUEST_PHONE = "+919876543210"


class FakeTransport:
    """Stands in for the host's Telegram account."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.fail_with: str = ""

    def resolve(self, phone):
        if self.fail_with:
            raise telegram_bridge.TelegramBridgeError(self.fail_with)
        return telegram_bridge.ResolvedPeer(peer_id="55501", display_name="Aarav", username="aarav")

    def send(self, peer_id, text):
        if self.fail_with:
            raise telegram_bridge.TelegramBridgeError(self.fail_with)
        self.sent.append((peer_id, text))


@pytest.fixture()
def transport(monkeypatch):
    fake = FakeTransport()
    monkeypatch.setattr(telegram_bridge, "resolve_contact", fake.resolve)
    monkeypatch.setattr(telegram_bridge, "send_text", fake.send)
    return fake


@pytest.fixture(autouse=True)
def clean_rooms():
    yield
    with SessionLocal() as db:
        db.query(SecretChatBridge).delete()
        db.query(SecretChatMessage).delete()
        db.query(SecretChatParticipant).delete()
        db.query(SecretChatSession).delete()
        db.commit()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _room(client):
    token = client.post("/api/secret-chat", json=HOST).json()["token"]
    client.post(f"/api/secret-chat/{token}/presence", json={
        "client_id": "host-client", "name": "Sharad", "role": "host", **HOST,
    })
    return token


def _link(client, token, **extra):
    return client.put(
        f"/api/secret-chat/{token}/bridge",
        json={**HOST, "platform": "telegram", "phone": GUEST_PHONE, **extra},
    )


# ─── Linking ───

def test_link_resolves_the_number_and_names_the_guest(client, transport):
    token = _room(client)
    response = _link(client, token)
    assert response.status_code == 200
    body = response.json()
    assert body["platform"] == "telegram"
    assert body["phone"] == GUEST_PHONE
    assert body["peer_name"] == "Aarav"
    assert body["client_id"]


def test_link_sends_the_optional_greeting(client, transport):
    token = _room(client)
    _link(client, token, greeting="hey, this is Sharad")
    assert transport.sent == [("55501", "hey, this is Sharad")]


def test_linking_adds_the_guest_as_a_participant(client, transport):
    token = _room(client)
    _link(client, token)
    participants = client.get(f"/api/secret-chat/{token}/participants", params=HOST).json()
    bridged = [item for item in participants if item["device"] == "telegram"]
    assert len(bridged) == 1
    assert bridged[0]["name"] == "Aarav"
    assert bridged[0]["role"] == "guest"


def test_a_number_cannot_be_linked_to_two_rooms(client, transport):
    first = _room(client)
    second = _room(client)
    _link(client, first)
    clash = _link(client, second)
    assert clash.status_code == 409


def test_relinking_the_same_room_updates_in_place(client, transport):
    token = _room(client)
    _link(client, token)
    again = _link(client, token)
    assert again.status_code == 200
    with SessionLocal() as db:
        assert db.query(SecretChatBridge).count() == 1


def test_a_bad_number_is_a_400_not_a_500(client, transport):
    token = _room(client)
    response = client.put(
        f"/api/secret-chat/{token}/bridge",
        json={**HOST, "platform": "telegram", "phone": "9876543210"},
    )
    assert response.status_code == 400
    assert "country code" in response.json()["detail"]


def test_a_transport_failure_is_reported_to_the_host(client, transport):
    transport.fail_with = "That number is not on Telegram."
    token = _room(client)
    response = _link(client, token)
    assert response.status_code == 400
    assert "not on Telegram" in response.json()["detail"]


# ─── Message flow ───

def test_a_room_message_goes_out_to_the_guest(client, transport):
    token = _room(client)
    _link(client, token)
    client.post(f"/api/secret-chat/{token}/messages", json={
        "sender": "Sharad|||host-client", "content": "kaisa hai?",
    })
    assert transport.sent == [("55501", "kaisa hai?")]


def test_an_inbound_reply_becomes_a_room_message(client, transport):
    token = _room(client)
    _link(client, token)
    secret_chat._handle_inbound(
        telegram_bridge.InboundMessage(peer_id="55501", sender_name="Aarav", text="badhiya!")
    )
    messages = client.get(f"/api/secret-chat/{token}/messages").json()
    assert [item["content"] for item in messages] == ["badhiya!"]
    assert messages[0]["sender"].startswith("Aarav|||bridge-")


def test_an_inbound_reply_is_not_echoed_back_to_telegram(client, transport):
    token = _room(client)
    _link(client, token)
    secret_chat._handle_inbound(
        telegram_bridge.InboundMessage(peer_id="55501", sender_name="Aarav", text="badhiya!")
    )
    assert transport.sent == []


def test_inbound_from_an_unknown_number_is_ignored(client, transport):
    token = _room(client)
    _link(client, token)
    secret_chat._handle_inbound(
        telegram_bridge.InboundMessage(peer_id="99999", sender_name="Stranger", text="hi")
    )
    assert client.get(f"/api/secret-chat/{token}/messages").json() == []


def test_a_send_failure_does_not_fail_the_post(client, transport):
    token = _room(client)
    _link(client, token)
    transport.fail_with = "Telegram is rate-limiting this account."
    response = client.post(f"/api/secret-chat/{token}/messages", json={
        "sender": "Sharad|||host-client", "content": "still lands in the room",
    })
    assert response.status_code == 201
    bridge = client.get(f"/api/secret-chat/{token}/bridge", params=HOST).json()
    assert "rate-limiting" in bridge["last_error"]


def test_inbound_counts_toward_the_guests_message_count(client, transport):
    token = _room(client)
    _link(client, token)
    secret_chat._handle_inbound(
        telegram_bridge.InboundMessage(peer_id="55501", sender_name="Aarav", text="one")
    )
    participants = client.get(f"/api/secret-chat/{token}/participants", params=HOST).json()
    bridged = next(item for item in participants if item["device"] == "telegram")
    assert bridged["message_count"] == 1


def test_autopilot_answers_a_telegram_message_on_telegram(client, transport, monkeypatch):
    """The payoff: a bridged room on autopilot holds the conversation with nobody watching."""
    monkeypatch.setattr(secret_chat.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(secret_chat, "_chat", lambda system, prompt, model, **kwargs: '{"replies": ["nikal raha hoon"]}')
    token = _room(client)
    _link(client, token)
    client.patch(f"/api/secret-chat/{token}", json={**HOST, "ai_autopilot": True})

    secret_chat._handle_inbound(
        telegram_bridge.InboundMessage(peer_id="55501", sender_name="Aarav", text="kahan ho?")
    )
    for thread in [t for t in threading.enumerate() if t.name.startswith("locus-autopilot")]:
        thread.join(timeout=10)

    assert transport.sent == [("55501", "nikal raha hoon")]
    messages = client.get(f"/api/secret-chat/{token}/messages").json()
    assert [item["content"] for item in messages] == ["kahan ho?", "nikal raha hoon"]


# ─── Unlinking ───

def test_unlink_removes_the_bridge_and_its_participant(client, transport):
    token = _room(client)
    _link(client, token)
    assert client.delete(f"/api/secret-chat/{token}/bridge", params=HOST).status_code == 204
    assert client.get(f"/api/secret-chat/{token}/bridge", params=HOST).json() is None
    participants = client.get(f"/api/secret-chat/{token}/participants", params=HOST).json()
    assert not [item for item in participants if item["device"] == "telegram"]


def test_unlinked_room_stops_sending(client, transport):
    token = _room(client)
    _link(client, token)
    client.delete(f"/api/secret-chat/{token}/bridge", params=HOST)
    client.post(f"/api/secret-chat/{token}/messages", json={
        "sender": "Sharad|||host-client", "content": "should not go out",
    })
    assert transport.sent == []


def test_deleting_the_room_deletes_the_bridge(client, transport):
    token = _room(client)
    _link(client, token)
    client.delete(f"/api/secret-chat/{token}", params=HOST)
    with SessionLocal() as db:
        assert db.query(SecretChatBridge).count() == 0


# ─── Access ───

def test_only_the_host_can_link_a_number(client, transport):
    token = _room(client)
    response = client.put(
        f"/api/secret-chat/{token}/bridge",
        json={"host_key": "not-the-host", "platform": "telegram", "phone": GUEST_PHONE},
    )
    assert response.status_code == 403


def test_only_the_host_can_read_or_unlink_the_bridge(client, transport):
    token = _room(client)
    _link(client, token)
    assert client.get(f"/api/secret-chat/{token}/bridge", params={"host_key": "nope"}).status_code == 403
    assert client.delete(f"/api/secret-chat/{token}/bridge", params={"host_key": "nope"}).status_code == 403


def test_the_public_room_view_does_not_leak_the_number(client, transport):
    """A link guest sharing the room must not learn who else is bridged, or on what number."""
    token = _room(client)
    _link(client, token)
    body = client.get(f"/api/secret-chat/{token}").text
    assert GUEST_PHONE not in body
    assert "peer_id" not in body


def test_the_host_room_list_shows_the_bridge(client, transport):
    token = _room(client)
    _link(client, token)
    rooms = client.get("/api/secret-chat", params={**HOST, "client_id": "host-client"}).json()
    room = next(item for item in rooms if item["token"] == token)
    assert room["bridge_platform"] == "telegram"
    assert room["bridge_name"] == "Aarav"


# ─── Deployment status ───

def test_status_reports_an_unconfigured_deployment(client, monkeypatch):
    monkeypatch.delenv("LOCUS_TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("LOCUS_TELEGRAM_API_HASH", raising=False)
    monkeypatch.delenv("LOCUS_TELEGRAM_SESSION", raising=False)
    body = client.get("/api/secret-chat/bridge/status").json()
    assert body == {"platform": "telegram", "configured": False, "connected": False, "account": "", "error": ""}


def test_linking_without_credentials_explains_itself(client, monkeypatch):
    monkeypatch.delenv("LOCUS_TELEGRAM_API_ID", raising=False)
    token = _room(client)
    response = _link(client, token)
    assert response.status_code == 400
    assert "LOCUS_TELEGRAM_API_ID" in response.json()["detail"]


@pytest.mark.parametrize("raw,expected", [
    ("+91 98765 43210", "+919876543210"),
    ("+1-415-555-0134", "+14155550134"),
    ("0091 98765 43210", "+919876543210"),
])
def test_phone_numbers_are_normalised_to_e164(raw, expected):
    assert telegram_bridge.normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "hello", "12345", "+0123456789", "9876543210"])
def test_unusable_numbers_are_rejected(raw):
    with pytest.raises(telegram_bridge.TelegramBridgeError):
        telegram_bridge.normalize_phone(raw)

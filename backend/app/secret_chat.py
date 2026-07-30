"""Secret Chat — standalone micro-feature for shareable real-time chat rooms.

Three things are worth knowing before editing this module:

* **Host vs guest.** The browser that creates a room generates a `host_key` and keeps it
  locally. Administrative actions (room list, options, deletion, participant details, AI
  assist) are authorised against that key, so a link guest can chat but can never manage
  the room or see anyone's device details. Rooms with no owner — created before host keys
  existed, or by a client that sends none — fall back to the app's own auth gate, and the
  first host key to touch one claims it; see `_require_host`.
* **Rooms expire in two independent ways.** `link_expires_at` only stops *new* people from
  joining; already-known clients keep chatting. `expires_at` (and an explicit close) ends
  the room for everyone, and the data is deleted the first time anyone touches it after that.
* **Auto-disappear** is enforced server-side by `_purge_expired_messages`, which also pushes
  a `purge` event so every open client drops the same messages at the same moment.
"""

import asyncio
import json
import os
import random
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from . import telegram_bridge
from .config import configured_model, llm_provider
from .database import SessionLocal, get_db
from .llm import LLMProviderError, _chat, llm_provider_context
from .models import (
    SecretChatBridge,
    SecretChatMessage,
    SecretChatParticipant,
    SecretChatSession,
    UserPreference,
)
from .schemas import (
    SecretChatAssistRequest,
    SecretChatAssistResponse,
    SecretChatBridgeLink,
    SecretChatBridgeRead,
    SecretChatBridgeStatus,
    SecretChatCreate,
    SecretChatCreateResponse,
    SecretChatMessageRead,
    SecretChatMessageSend,
    SecretChatOptionsUpdate,
    SecretChatParticipantDetail,
    SecretChatParticipantRead,
    SecretChatPresenceUpdate,
    SecretChatRoomSummary,
    SecretChatSessionRead,
)

router = APIRouter(prefix="/api/secret-chat", tags=["secret-chat"])

# A participant counts as online while their heartbeat is this fresh.
ONLINE_WINDOW_SECONDS = 25
# How long a single "typing" ping stays hot without a refresh.
TYPING_WINDOW_SECONDS = 6
ASSIST_HISTORY_MESSAGES = 24
ASSIST_STYLE_SAMPLES = 12

_SECRET_CHAT_EVENTS: dict[str, list[asyncio.Queue]] = {}
_SECRET_CHAT_EVENTS_LOCK = Lock()

# Pushed to every live stream when a room is deleted, so connected guests are cut
# off immediately instead of holding an open connection to a room that is gone.
REVOKED = object()


def _now() -> datetime:
    """Naive UTC, matching what the DateTime columns store."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _secret_chat_queues(token: str) -> list[asyncio.Queue]:
    with _SECRET_CHAT_EVENTS_LOCK:
        return _SECRET_CHAT_EVENTS.setdefault(token, [])


def _broadcast(token: str, payload: dict) -> None:
    for queue in _secret_chat_queues(token):
        queue.put_nowait(payload)


def _revoke_streams(token: str) -> None:
    with _SECRET_CHAT_EVENTS_LOCK:
        queues = _SECRET_CHAT_EVENTS.pop(token, [])
    for queue in queues:
        queue.put_nowait(REVOKED)


def _message_payload(message: SecretChatMessage, ttl_seconds: int) -> dict:
    created = _naive(message.created_at) or _now()
    expires_at = created + timedelta(seconds=ttl_seconds) if ttl_seconds else None
    return {
        "id": message.id,
        "sender": message.sender,
        "content": message.content,
        "created_at": created.isoformat(),
        "via_ai": bool(message.via_ai),
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


# ─── Room lifecycle ───

def _link_expired(session: SecretChatSession) -> bool:
    link_expiry = _naive(session.link_expires_at)
    return bool(link_expiry and link_expiry <= _now())


def _room_finished(session: SecretChatSession) -> bool:
    room_expiry = _naive(session.expires_at)
    return bool(session.closed_at) or bool(room_expiry and room_expiry <= _now())


def _purge_expired_messages(db: Session, session: SecretChatSession) -> list[int]:
    """Delete messages past the room's auto-disappear window and tell open clients."""
    if not session.message_ttl_seconds:
        return []
    cutoff = _now() - timedelta(seconds=session.message_ttl_seconds)
    stale = db.scalars(
        select(SecretChatMessage).where(
            SecretChatMessage.session_token == session.token,
            SecretChatMessage.created_at <= cutoff,
        )
    ).all()
    if not stale:
        return []
    ids = [message.id for message in stale]
    db.execute(delete(SecretChatMessage).where(SecretChatMessage.id.in_(ids)))
    db.commit()
    _broadcast(session.token, {"type": "purge", "ids": ids})
    return ids


def _destroy(db: Session, session: SecretChatSession) -> None:
    """Delete a room and drop everyone still connected to it."""
    token = session.token
    db.delete(session)
    db.commit()
    # Tell open clients why, then cut the streams so nobody reconnects into a 404 loop.
    _broadcast(token, {"type": "room", "state": "ended"})
    _revoke_streams(token)


def _load_room(db: Session, token: str) -> SecretChatSession:
    session = db.get(SecretChatSession, token)
    if not session:
        raise HTTPException(status_code=404, detail="Private chat not found")
    if _room_finished(session):
        # An ended room keeps nothing around: the data goes on first touch after expiry.
        _destroy(db, session)
        raise HTTPException(status_code=410, detail="This private chat has ended")
    _purge_expired_messages(db, session)
    return session


def _is_host(session: SecretChatSession, host_key: str) -> bool:
    return bool(session.host_key) and bool(host_key) and session.host_key == host_key


def _claim_unowned(db: Session, session: SecretChatSession, host_key: str) -> bool:
    """Rooms made before host keys existed have no owner: the first host to touch one adopts it."""
    if session.host_key or not host_key:
        return False
    session.host_key = host_key
    db.commit()
    return True


def _require_host(db: Session, session: SecretChatSession, host_key: str) -> None:
    """
    A room that has an owner can only be managed with its host key. A room with no owner —
    one created before host keys existed, or by a client that does not send one — is managed
    by whoever gets through the app's own auth gate, and the first host key to touch it
    claims it from then on.
    """
    if _is_host(session, host_key):
        return
    if not session.host_key:
        _claim_unowned(db, session, host_key)
        return
    raise HTTPException(status_code=403, detail="Only the chat host can do that")


def _guard_join(db: Session, session: SecretChatSession, client_id: str, host_key: str) -> None:
    """An expired invite link still serves people who were already in the room."""
    if _is_host(session, host_key) or not _link_expired(session):
        return
    if client_id:
        known = db.scalar(
            select(func.count())
            .select_from(SecretChatParticipant)
            .where(
                SecretChatParticipant.session_token == session.token,
                SecretChatParticipant.client_id == client_id,
            )
        )
        if known:
            return
    raise HTTPException(status_code=403, detail="This invite link has expired")


# ─── Participants ───

_BROWSER_PATTERNS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("SamsungBrowser/", "Samsung Internet"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)

_OS_PATTERNS = (
    ("Windows NT 10", "Windows 10/11"),
    ("Windows", "Windows"),
    ("iPhone", "iOS"),
    ("iPad", "iPadOS"),
    ("Android", "Android"),
    ("Mac OS X", "macOS"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)


def _describe_client(user_agent: str) -> tuple[str, str, str]:
    """(browser, os, device) from a user-agent string — best effort, never raises."""
    agent = user_agent or ""
    browser = next((label for token, label in _BROWSER_PATTERNS if token in agent), "Unknown browser")
    if browser in {"Chrome", "Safari"}:
        version = re.search(r"(?:Chrome|Version)/(\d+)", agent)
        if version:
            browser = f"{browser} {version.group(1)}"
    os_label = next((label for token, label in _OS_PATTERNS if token in agent), "Unknown OS")
    device = "Tablet" if ("iPad" in agent or ("Android" in agent and "Mobile" not in agent)) else "Phone" if "Mobile" in agent else "Desktop"
    return browser, os_label, device


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def _is_online(participant: SecretChatParticipant) -> bool:
    last_seen = _naive(participant.last_seen) or datetime.min
    return (_now() - last_seen).total_seconds() <= ONLINE_WINDOW_SECONDS


def _is_typing(participant: SecretChatParticipant) -> bool:
    typing_until = _naive(participant.typing_until)
    return bool(typing_until and typing_until > _now())


def _participants(db: Session, token: str) -> list[SecretChatParticipant]:
    return list(
        db.scalars(
            select(SecretChatParticipant)
            .where(SecretChatParticipant.session_token == token)
            .order_by(SecretChatParticipant.first_seen)
        ).all()
    )


def _public_participant(participant: SecretChatParticipant) -> SecretChatParticipantRead:
    return SecretChatParticipantRead(
        client_id=participant.client_id,
        name=participant.name,
        role=participant.role,
        online=_is_online(participant),
        typing=_is_typing(participant),
        joined_at=_naive(participant.first_seen) or _now(),
        last_seen=_naive(participant.last_seen) or _now(),
        message_count=participant.message_count,
        last_read_id=participant.last_read_id,
    )


def _local_time(timezone_name: str) -> str:
    """The participant's own wall-clock time, so the host sees when *they* are reading."""
    if not timezone_name:
        return ""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(timezone_name)).strftime("%H:%M")
    except Exception:
        return ""


def _detailed_participant(participant: SecretChatParticipant) -> SecretChatParticipantDetail:
    joined = _naive(participant.first_seen) or _now()
    return SecretChatParticipantDetail(
        **_public_participant(participant).model_dump(),
        ip=participant.ip,
        user_agent=participant.user_agent,
        browser=participant.browser,
        os=participant.os,
        device=participant.device,
        language=participant.language,
        timezone=participant.timezone,
        local_time=_local_time(participant.timezone),
        screen=participant.screen,
        viewport=participant.viewport,
        minutes_in_room=max(0, int((_now() - joined).total_seconds() // 60)),
    )


def _touch_participant(
    db: Session,
    session: SecretChatSession,
    request: Request,
    payload: SecretChatPresenceUpdate,
) -> SecretChatParticipant:
    participant = db.scalar(
        select(SecretChatParticipant).where(
            SecretChatParticipant.session_token == session.token,
            SecretChatParticipant.client_id == payload.client_id,
        )
    )
    user_agent = request.headers.get("user-agent", "")[:400]
    browser, os_label, device = _describe_client(user_agent)
    joined = participant is None
    if participant is None:
        participant = SecretChatParticipant(
            session_token=session.token,
            client_id=payload.client_id,
            first_seen=_now(),
            last_read_id=0,
            message_count=0,
        )
        db.add(participant)
    participant.name = payload.name
    # A browser that proves the host key is the host, whatever it claims to be.
    participant.role = "host" if _is_host(session, payload.host_key) else "guest"
    participant.last_seen = _now()
    participant.typing_until = _now() + timedelta(seconds=TYPING_WINDOW_SECONDS) if payload.typing else None
    participant.last_read_id = max(participant.last_read_id or 0, payload.last_read_id)
    participant.ip = _client_ip(request)
    participant.user_agent = user_agent
    participant.browser = browser
    participant.os = os_label
    participant.device = device
    participant.language = payload.language[:40]
    participant.timezone = payload.timezone[:60]
    participant.screen = payload.screen[:40]
    participant.viewport = payload.viewport[:40]
    db.commit()
    db.refresh(participant)
    if joined:
        _broadcast(session.token, {"type": "presence", "event": "joined", "name": participant.name})
    return participant


# ─── Rooms ───

def _share_url(token: str) -> str:
    host = os.getenv("SECRET_CHAT_HOST", "http://127.0.0.1:5173")
    # Guests join on the short neutral path; see src/secret-chat/links.js.
    return f"{host}/j/{token}"


@router.post("", response_model=SecretChatCreateResponse, status_code=status.HTTP_201_CREATED)
def create_secret_chat(payload: SecretChatCreate | None = None, db: Session = Depends(get_db)):
    """Host-only (see auth.GUEST_SECRET_CHAT_ROUTES) — guests join rooms, they never open them."""
    options = payload or SecretChatCreate()
    token = uuid4().hex[:16]
    now = _now()
    session = SecretChatSession(
        token=token,
        title=(options.title or "Private").strip()[:160] or "Private",
        host_key=options.host_key,
        message_ttl_seconds=options.message_ttl_seconds,
        link_expires_at=now + timedelta(minutes=options.link_expiry_minutes) if options.link_expiry_minutes else None,
        expires_at=now + timedelta(minutes=options.room_expiry_minutes) if options.room_expiry_minutes else None,
    )
    db.add(session)
    db.commit()
    return SecretChatCreateResponse(token=token, url=_share_url(token))


@router.get("", response_model=list[SecretChatRoomSummary])
def list_secret_chats(host_key: str = "", client_id: str = "", db: Session = Depends(get_db)):
    """The host's own rooms, newest first, with the unread count for their client."""
    sessions = db.scalars(
        select(SecretChatSession)
        .where(SecretChatSession.host_key.in_([host_key, ""]))
        .order_by(SecretChatSession.last_activity.desc())
    ).all()
    summaries: list[SecretChatRoomSummary] = []
    for session in sessions:
        if _room_finished(session):
            _destroy(db, session)
            continue
        _purge_expired_messages(db, session)
        messages = db.scalars(
            select(SecretChatMessage)
            .where(SecretChatMessage.session_token == session.token)
            .order_by(SecretChatMessage.id)
        ).all()
        participants = _participants(db, session.token)
        bridge = _room_bridge(db, session.token)
        reader = next((item for item in participants if item.client_id == client_id), None)
        last_read = reader.last_read_id if reader else 0
        # Unread means posted by somebody else and newer than this host's read cursor.
        unread = [message for message in messages if message.id > last_read and _sender_client(message.sender) != client_id]
        last = messages[-1] if messages else None
        summaries.append(SecretChatRoomSummary(
            token=session.token,
            url=_share_url(session.token),
            title=session.title,
            created_at=_naive(session.created_at) or _now(),
            last_activity=_naive(session.last_activity) or _now(),
            message_count=len(messages),
            unread_count=len(unread),
            last_message_id=last.id if last else 0,
            last_message_preview=(last.content[:80] if last else ""),
            last_sender=(_sender_name(last.sender) if last else ""),
            participant_count=len(participants),
            online_count=sum(1 for item in participants if _is_online(item)),
            message_ttl_seconds=session.message_ttl_seconds,
            link_expires_at=_naive(session.link_expires_at),
            expires_at=_naive(session.expires_at),
            link_expired=_link_expired(session),
            bridge_platform=(bridge.platform if bridge else ""),
            bridge_name=(_sender_display(bridge) if bridge else ""),
        ))
    return summaries


def _sender_name(sender: str) -> str:
    return (sender or "").split("|||")[0] or "Anonymous"


def _sender_client(sender: str) -> str:
    parts = (sender or "").split("|||")
    return parts[1] if len(parts) > 1 else ""


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_secret_chats(host_key: str = "", db: Session = Depends(get_db)):
    """Delete every room this host owns — messages, participants and links go with them."""
    if not host_key:
        raise HTTPException(status_code=403, detail="Only the chat host can do that")
    # Deletes exactly what list_secret_chats showed this host, unowned rooms included —
    # otherwise "delete all" would leave rows behind in the rail.
    sessions = db.scalars(
        select(SecretChatSession).where(SecretChatSession.host_key.in_([host_key, ""]))
    ).all()
    tokens = [session.token for session in sessions]
    for session in sessions:
        db.delete(session)
    db.commit()
    for token in tokens:
        _broadcast(token, {"type": "room", "state": "ended"})
        _revoke_streams(token)
    return None


@router.get("/{token}", response_model=SecretChatSessionRead)
def get_secret_chat(token: str, client_id: str = "", host_key: str = "", db: Session = Depends(get_db)):
    session = _load_room(db, token)
    _guard_join(db, session, client_id, host_key)
    messages = db.scalars(
        select(SecretChatMessage)
        .where(SecretChatMessage.session_token == token)
        .order_by(SecretChatMessage.id)
    ).all()
    return SecretChatSessionRead(
        token=session.token,
        title=session.title,
        created_at=_naive(session.created_at) or _now(),
        last_activity=_naive(session.last_activity) or _now(),
        message_ttl_seconds=session.message_ttl_seconds,
        link_expires_at=_naive(session.link_expires_at),
        expires_at=_naive(session.expires_at),
        link_expired=_link_expired(session),
        ai_tone=session.ai_tone,
        ai_persona=session.ai_persona,
        ai_autopilot=session.ai_autopilot,
        ai_mimic_me=session.ai_mimic_me,
        messages=[SecretChatMessageRead(**_message_payload(message, session.message_ttl_seconds)) for message in messages],
        participants=[_public_participant(item) for item in _participants(db, token)],
    )


@router.patch("/{token}", response_model=SecretChatSessionRead)
def update_secret_chat(token: str, payload: SecretChatOptionsUpdate, db: Session = Depends(get_db)):
    session = _load_room(db, token)
    _require_host(db, session, payload.host_key)
    now = _now()
    if payload.title is not None:
        session.title = payload.title.strip()[:160] or "Private"
    if payload.message_ttl_seconds is not None:
        session.message_ttl_seconds = payload.message_ttl_seconds
    if payload.link_expiry_minutes is not None:
        session.link_expires_at = now + timedelta(minutes=payload.link_expiry_minutes) if payload.link_expiry_minutes else None
    if payload.room_expiry_minutes is not None:
        session.expires_at = now + timedelta(minutes=payload.room_expiry_minutes) if payload.room_expiry_minutes else None
    if payload.ai_tone is not None:
        session.ai_tone = payload.ai_tone[:40]
    if payload.ai_persona is not None:
        session.ai_persona = payload.ai_persona[:2000]
    if payload.ai_autopilot is not None:
        session.ai_autopilot = payload.ai_autopilot
    if payload.ai_mimic_me is not None:
        session.ai_mimic_me = payload.ai_mimic_me
    db.commit()
    _purge_expired_messages(db, session)
    _broadcast(token, {"type": "room", "state": "updated", "message_ttl_seconds": session.message_ttl_seconds})
    return get_secret_chat(token, host_key=payload.host_key, db=db)


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret_chat(token: str, host_key: str = "", db: Session = Depends(get_db)):
    """End the room: the link dies and every message and participant record is deleted."""
    session = db.get(SecretChatSession, token)
    if not session:
        return None
    _require_host(db, session, host_key)
    _destroy(db, session)
    return None


@router.delete("/{token}/messages", status_code=status.HTTP_204_NO_CONTENT)
def clear_secret_chat_messages(token: str, host_key: str = "", db: Session = Depends(get_db)):
    """Delete every message but keep the room and its link alive."""
    session = _load_room(db, token)
    _require_host(db, session, host_key)
    ids = db.scalars(select(SecretChatMessage.id).where(SecretChatMessage.session_token == token)).all()
    db.execute(delete(SecretChatMessage).where(SecretChatMessage.session_token == token))
    db.execute(
        update(SecretChatParticipant)
        .where(SecretChatParticipant.session_token == token)
        .values(last_read_id=0, message_count=0)
    )
    db.commit()
    _broadcast(token, {"type": "purge", "ids": list(ids), "cleared": True})
    return None


# ─── Messages ───

@router.get("/{token}/messages", response_model=list[SecretChatMessageRead])
def get_secret_chat_messages(token: str, after: int = 0, db: Session = Depends(get_db)):
    session = _load_room(db, token)
    messages = db.scalars(
        select(SecretChatMessage)
        .where(SecretChatMessage.session_token == token, SecretChatMessage.id > after)
        .order_by(SecretChatMessage.id)
    ).all()
    return [SecretChatMessageRead(**_message_payload(message, session.message_ttl_seconds)) for message in messages]


@router.post("/{token}/messages", response_model=SecretChatMessageRead, status_code=status.HTTP_201_CREATED)
def send_secret_chat_message(token: str, payload: SecretChatMessageSend, db: Session = Depends(get_db)):
    session = _load_room(db, token)
    message = SecretChatMessage(
        session_token=token,
        sender=payload.sender,
        content=payload.content,
        via_ai=payload.via_ai,
    )
    db.add(message)
    session.last_activity = _now()
    db.commit()
    db.refresh(message)
    client_id = _sender_client(payload.sender)
    if client_id:
        author = db.scalar(
            select(SecretChatParticipant).where(
                SecretChatParticipant.session_token == token,
                SecretChatParticipant.client_id == client_id,
            )
        )
        if author:
            author.message_count = (author.message_count or 0) + 1
            author.last_read_id = max(author.last_read_id or 0, message.id)
            author.typing_until = None
            db.commit()
    payload_dict = _message_payload(message, session.message_ttl_seconds)
    _broadcast(token, {"type": "message", **payload_dict})
    _deliver_to_bridge(db, session, message)
    _maybe_autopilot(db, session, message)
    return SecretChatMessageRead(**payload_dict)


# ─── Presence ───

@router.post("/{token}/presence")
def update_secret_chat_presence(
    token: str,
    payload: SecretChatPresenceUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Heartbeat: refreshes who is online, who is typing and how far each has read."""
    session = _load_room(db, token)
    _guard_join(db, session, payload.client_id, payload.host_key)
    # Opening a pre-host-key room in the app is what claims it for this browser.
    if payload.role == "host":
        _claim_unowned(db, session, payload.host_key)
    participant = _touch_participant(db, session, request, payload)
    participants = _participants(db, token)
    host = _is_host(session, payload.host_key)
    _broadcast(token, {
        "type": "presence",
        "participants": [item.model_dump(mode="json") for item in (_public_participant(entry) for entry in participants)],
    })
    return {
        "you": _public_participant(participant).model_dump(mode="json"),
        "participants": [
            (_detailed_participant(entry) if host else _public_participant(entry)).model_dump(mode="json")
            for entry in participants
        ],
        "room": {
            "title": session.title,
            "message_ttl_seconds": session.message_ttl_seconds,
            "link_expires_at": (_naive(session.link_expires_at).isoformat() if session.link_expires_at else None),
            "expires_at": (_naive(session.expires_at).isoformat() if session.expires_at else None),
            "link_expired": _link_expired(session),
        },
    }


@router.get("/{token}/participants", response_model=list[SecretChatParticipantDetail])
def get_secret_chat_participants(token: str, host_key: str = "", db: Session = Depends(get_db)):
    session = _load_room(db, token)
    _require_host(db, session, host_key)
    return [_detailed_participant(item) for item in _participants(db, token)]


# ─── Messenger bridge ───
#
# A bridged room swaps the share link for a phone number: the host types a number, Locus
# resolves it on the host's own Telegram account, and from then on every message posted in
# the room is delivered as a normal Telegram DM while every reply lands back in the room.
# The guest is represented by one synthetic participant so the rest of the feature —
# presence, unread counts, the copilot, autopilot — needs no special case.

def _bridge_client_id(token: str) -> str:
    """Stable per room, so a relink keeps the same participant row and its history."""
    return f"bridge-{token[:12]}"


def _bridge_read(bridge: SecretChatBridge) -> SecretChatBridgeRead:
    return SecretChatBridgeRead(
        platform=bridge.platform,
        phone=bridge.phone,
        peer_name=bridge.peer_name,
        peer_username=bridge.peer_username,
        client_id=bridge.client_id,
        created_at=_naive(bridge.created_at),
        last_outbound_at=_naive(bridge.last_outbound_at),
        last_inbound_at=_naive(bridge.last_inbound_at),
        last_error=bridge.last_error,
    )


def _bridge_participant(db: Session, bridge: SecretChatBridge) -> SecretChatParticipant:
    """The bridged guest as a room participant, created on link and refreshed on contact."""
    participant = db.scalar(
        select(SecretChatParticipant).where(
            SecretChatParticipant.session_token == bridge.session_token,
            SecretChatParticipant.client_id == bridge.client_id,
        )
    )
    if participant is None:
        participant = SecretChatParticipant(
            session_token=bridge.session_token,
            client_id=bridge.client_id,
            first_seen=_now(),
            last_read_id=0,
            message_count=0,
        )
        db.add(participant)
    participant.name = bridge.peer_name or bridge.phone
    participant.role = "guest"
    # There is no browser behind this one; the host panel shows the platform instead.
    participant.device = bridge.platform
    participant.browser = bridge.platform.title()
    participant.os = bridge.platform.title()
    participant.user_agent = f"{bridge.platform}:{bridge.phone}"
    return participant


def _room_bridge(db: Session, token: str) -> SecretChatBridge | None:
    return db.get(SecretChatBridge, token)


def _deliver_to_bridge(db: Session, session: SecretChatSession, message: SecretChatMessage) -> None:
    """Push a room message out to the bridged messenger, unless it came from there.

    Called *after* `_broadcast`, deliberately: the delivery is a network round trip to
    Telegram, and every open client has already rendered the message off the stream by the
    time it finishes. Failures are recorded on the bridge and swallowed for the same reason
    — a Telegram outage must not fail a post that is already in the room.
    """
    bridge = _room_bridge(db, session.token)
    if bridge is None:
        return
    if _sender_client(message.sender) == bridge.client_id:
        return  # Echo guard: this message *arrived* from the bridge.
    try:
        telegram_bridge.send_text(bridge.peer_id, message.content)
    except Exception as exc:  # noqa: BLE001 - the room keeps working without the bridge
        bridge.last_error = str(exc)[:300]
        db.commit()
        _broadcast(session.token, {"type": "bridge", "state": "error", "error": bridge.last_error})
        return
    bridge.last_outbound_at = _now()
    bridge.last_error = ""
    db.commit()


def _handle_inbound(inbound: telegram_bridge.InboundMessage) -> None:
    """A Telegram DM arrived: file it as a room message and wake everyone watching.

    Runs on the bridge's own thread with its own session — never inside a request.
    """
    with SessionLocal() as db:
        bridge = db.scalar(
            select(SecretChatBridge)
            .where(SecretChatBridge.peer_id == inbound.peer_id)
            .order_by(SecretChatBridge.created_at.desc())
        )
        if bridge is None:
            return
        session = db.get(SecretChatSession, bridge.session_token)
        if session is None or _room_finished(session):
            return
        if inbound.sender_name and inbound.sender_name != bridge.peer_name:
            bridge.peer_name = inbound.sender_name[:80]
        message = SecretChatMessage(
            session_token=session.token,
            sender=f"{_sender_display(bridge)}|||{bridge.client_id}",
            content=inbound.text[:2000],
        )
        db.add(message)
        session.last_activity = _now()
        bridge.last_inbound_at = _now()
        bridge.last_error = ""
        participant = _bridge_participant(db, bridge)
        participant.last_seen = _now()
        participant.typing_until = None
        db.commit()
        db.refresh(message)
        participant.message_count = (participant.message_count or 0) + 1
        participant.last_read_id = max(participant.last_read_id or 0, message.id)
        db.commit()
        _broadcast(session.token, {"type": "message", **_message_payload(message, session.message_ttl_seconds)})
        _broadcast(session.token, {
            "type": "presence",
            "participants": [
                item.model_dump(mode="json")
                for item in (_public_participant(entry) for entry in _participants(db, session.token))
            ],
        })
        _maybe_autopilot(db, session, message)


def _sender_display(bridge: SecretChatBridge) -> str:
    return (bridge.peer_name or bridge.phone or "Telegram")[:60]


telegram_bridge.set_inbound_handler(_handle_inbound)


@router.get("/bridge/status", response_model=SecretChatBridgeStatus)
def secret_chat_bridge_status():
    """Whether this deployment can bridge at all — the UI asks before offering it.

    Two path segments on purpose: a one-segment route would be swallowed by `/{token}`.
    """
    return SecretChatBridgeStatus(platform="telegram", **telegram_bridge.status())


@router.get("/{token}/bridge", response_model=SecretChatBridgeRead | None)
def get_secret_chat_bridge(token: str, host_key: str = "", db: Session = Depends(get_db)):
    session = _load_room(db, token)
    _require_host(db, session, host_key)
    bridge = _room_bridge(db, token)
    return _bridge_read(bridge) if bridge else None


@router.put("/{token}/bridge", response_model=SecretChatBridgeRead)
def link_secret_chat_bridge(token: str, payload: SecretChatBridgeLink, db: Session = Depends(get_db)):
    """Point this room at a phone number. Host-only: it messages from the host's account."""
    session = _load_room(db, token)
    _require_host(db, session, payload.host_key)
    try:
        phone = telegram_bridge.normalize_phone(payload.phone)
        peer = telegram_bridge.resolve_contact(phone)
    except telegram_bridge.TelegramBridgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Two rooms bridged to one person would make inbound routing a coin toss.
    clash = db.scalar(
        select(SecretChatBridge).where(
            SecretChatBridge.peer_id == peer.peer_id,
            SecretChatBridge.session_token != token,
        )
    )
    if clash is not None:
        raise HTTPException(status_code=409, detail="That number is already connected to another private chat")

    bridge = _room_bridge(db, token)
    if bridge is None:
        bridge = SecretChatBridge(session_token=token, client_id=_bridge_client_id(token))
        db.add(bridge)
    bridge.platform = "telegram"
    bridge.phone = phone
    bridge.peer_id = peer.peer_id
    bridge.peer_name = peer.display_name[:80]
    bridge.peer_username = peer.username[:64]
    bridge.last_error = ""
    _bridge_participant(db, bridge)
    db.commit()
    db.refresh(bridge)

    greeting = payload.greeting.strip()
    if greeting:
        try:
            telegram_bridge.send_text(bridge.peer_id, greeting[:2000])
            bridge.last_outbound_at = _now()
        except telegram_bridge.TelegramBridgeError as exc:
            bridge.last_error = str(exc)[:300]
        db.commit()

    _broadcast(token, {"type": "bridge", "state": "linked", "platform": "telegram", "name": bridge.peer_name})
    return _bridge_read(bridge)


@router.delete("/{token}/bridge", status_code=status.HTTP_204_NO_CONTENT)
def unlink_secret_chat_bridge(token: str, host_key: str = "", db: Session = Depends(get_db)):
    """Disconnect the number. Messages already delivered stay on the guest's phone."""
    session = _load_room(db, token)
    _require_host(db, session, host_key)
    bridge = _room_bridge(db, token)
    if bridge is not None:
        db.execute(
            delete(SecretChatParticipant).where(
                SecretChatParticipant.session_token == token,
                SecretChatParticipant.client_id == bridge.client_id,
            )
        )
        db.delete(bridge)
        db.commit()
        _broadcast(token, {"type": "bridge", "state": "unlinked"})
    return None


# ─── AI copilot ───

TONE_GUIDANCE = {
    "friendly": "warm, easy-going and human",
    "playful": "playful and teasing, quick with a joke",
    "flirty": "flirty and charming, but never crude",
    "formal": "polite, precise and professional",
    "blunt": "direct and blunt, no padding",
    "funny": "funny, a little absurd, land a punchline",
    "short": "extremely brief — a few words per reply",
    "supportive": "supportive and reassuring",
}


@contextmanager
def _no_provider_override():
    yield


def _assist_prompt(
    transcript: list[tuple[str, str]],
    style_samples: list[str],
    payload: SecretChatAssistRequest,
) -> tuple[str, str]:
    tone = TONE_GUIDANCE.get(payload.tone, payload.tone or "natural")
    system_parts = [
        f"You are drafting chat replies on behalf of {payload.sender or 'the user'} in a private one-to-one or small group chat.",
        f"Write in a {tone} tone.",
        "Reply the way a real person texts: short lines, no greetings unless the chat just started, no sign-offs, no emoji spam.",
        "Never mention that you are an AI, never explain your reasoning, never add quotation marks around the reply.",
        "Match the language the other person is using, including mixed languages such as Hinglish.",
    ]
    if payload.persona.strip():
        system_parts.append(f"Extra instructions about how this person sounds: {payload.persona.strip()}")
    if payload.mimic_me and style_samples:
        joined = "\n".join(f"- {sample}" for sample in style_samples)
        system_parts.append(
            "Copy this person's own writing style — their vocabulary, message length, punctuation habits, "
            f"capitalisation and slang. Real examples of their past messages:\n{joined}"
        )
    system_parts.append(
        'Return only JSON in the form {"replies": ["...", "...", "..."]} with three distinct options, '
        "ordered best first. No prose outside the JSON."
    )

    lines = [f"{name}: {content}" for name, content in transcript] or ["(no messages yet)"]
    prompt_parts = ["Conversation so far (oldest first):", "\n".join(lines)]
    if payload.instruction.strip():
        prompt_parts.append(f"What I want to get across in this reply: {payload.instruction.strip()}")
    prompt_parts.append(f"Write the next message from {payload.sender or 'me'}.")
    return "\n\n".join(system_parts), "\n\n".join(prompt_parts)


def _parse_replies(content: str) -> list[str]:
    text = (content or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            replies = parsed.get("replies") or parsed.get("suggestions") or []
            cleaned = [str(item).strip().strip('"') for item in replies if str(item).strip()]
            if cleaned:
                return cleaned[:3]
        except json.JSONDecodeError:
            pass
    # A model that ignored the JSON contract still gives usable lines.
    lines = [re.sub(r"^\s*(?:[-*\d.]+\s*)", "", line).strip().strip('"') for line in text.splitlines()]
    return [line for line in lines if line][:3]


def _preferred_ai(db: Session) -> tuple[str, str | None]:
    """The provider and model chosen in Settings, falling back to the .env defaults.

    Settings saves them under the `explore_ai` preference, so a reply drafted here uses the
    same model the rest of the app answers with instead of whatever the environment defaults to.
    """
    preference = db.get(UserPreference, "explore_ai")
    saved = preference.value if preference and isinstance(preference.value, dict) else {}
    model = (saved.get("model") or "").strip() or configured_model()
    provider = (saved.get("provider") or "").strip() or None
    return model, provider


def _draft_reply(
    db: Session,
    token: str,
    payload: SecretChatAssistRequest,
    model: str,
    provider: str | None,
) -> tuple[list[str], int]:
    messages = db.scalars(
        select(SecretChatMessage)
        .where(SecretChatMessage.session_token == token)
        .order_by(SecretChatMessage.id.desc())
        .limit(ASSIST_HISTORY_MESSAGES)
    ).all()
    transcript = [(_sender_name(message.sender), message.content) for message in reversed(messages)]
    style_samples: list[str] = []
    if payload.mimic_me and payload.client_id:
        mine = db.scalars(
            select(SecretChatMessage.content)
            .where(
                SecretChatMessage.session_token == token,
                SecretChatMessage.sender.like(f"%|||{payload.client_id}"),
                SecretChatMessage.via_ai.is_(False),
            )
            .order_by(SecretChatMessage.id.desc())
            .limit(ASSIST_STYLE_SAMPLES)
        ).all()
        style_samples = [content for content in mine if content.strip()]

    system, prompt = _assist_prompt(transcript, style_samples, payload)
    with llm_provider_context(provider) if provider else _no_provider_override():
        content = _chat(system, prompt, model=model, temperature=0.8, max_tokens=400)
    return _parse_replies(content), len(style_samples)


@router.post("/{token}/assist", response_model=SecretChatAssistResponse)
def assist_secret_chat(token: str, payload: SecretChatAssistRequest, db: Session = Depends(get_db)):
    """Draft replies for the host to review in the composer."""
    session = _load_room(db, token)
    _require_host(db, session, payload.host_key)

    preferred_model, preferred_provider = _preferred_ai(db)
    model = payload.model or preferred_model
    provider = payload.provider or preferred_provider
    try:
        suggestions, style_samples = _draft_reply(db, token, payload, model, provider)
    except LLMProviderError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001 - surfaced to the composer as a toast
        raise HTTPException(status_code=502, detail=f"The AI could not draft a reply: {error}") from error

    if not suggestions:
        raise HTTPException(status_code=502, detail="The AI returned an empty reply")
    return SecretChatAssistResponse(
        suggestions=suggestions,
        tone=payload.tone,
        model=model,
        style_samples=style_samples,
    )


# ─── Autopilot ───
#
# Autopilot runs here, not in the host's browser. The host can close the tab — or never open
# it — and the room still answers. It also means the reply is not gated on a page being
# awake, which is what made the old client-driven version feel late.

# A reply lands like a person wrote it: a beat to notice the message, then time on the
# keyboard roughly proportional to what gets typed.
AUTOPILOT_NOTICE_SECONDS = (1.5, 4.0)
AUTOPILOT_SECONDS_PER_CHARACTER = 0.045
AUTOPILOT_MAX_TYPING_SECONDS = 9.0


def _autopilot_typing_seconds(reply: str) -> float:
    return min(AUTOPILOT_MAX_TYPING_SECONDS, 0.9 + len(reply) * AUTOPILOT_SECONDS_PER_CHARACTER)


def _set_typing(db: Session, token: str, participant: SecretChatParticipant, typing: bool) -> None:
    participant.typing_until = _now() + timedelta(seconds=TYPING_WINDOW_SECONDS) if typing else None
    db.commit()
    _broadcast(token, {
        "type": "presence",
        "participants": [_public_participant(item).model_dump(mode="json") for item in _participants(db, token)],
    })


def _run_autopilot(token: str, trigger_message_id: int) -> None:
    """Answer as the host, with the pauses a person would take."""
    try:
        with SessionLocal() as db:
            session = db.get(SecretChatSession, token)
            if not session or not session.ai_autopilot or _room_finished(session):
                return
            host = db.scalar(
                select(SecretChatParticipant).where(
                    SecretChatParticipant.session_token == token,
                    SecretChatParticipant.role == "host",
                ).order_by(SecretChatParticipant.last_seen.desc())
            )
            if host is None:
                # Nobody has ever opened this room as the host, so there is no name or client
                # id to answer as. Replying as a stranger would be worse than staying quiet.
                return
            newest = db.scalar(
                select(func.max(SecretChatMessage.id)).where(SecretChatMessage.session_token == token)
            )
            if newest != trigger_message_id:
                # Someone else has spoken since; that later message gets its own reply.
                return
            request = SecretChatAssistRequest(
                host_key=session.host_key,
                client_id=host.client_id,
                sender=host.name,
                mode="autopilot",
                tone=session.ai_tone,
                persona=session.ai_persona,
                mimic_me=session.ai_mimic_me,
            )
            model, provider = _preferred_ai(db)

        # Read the message like a person would before starting to type.
        time.sleep(random.uniform(*AUTOPILOT_NOTICE_SECONDS))

        with SessionLocal() as db:
            session = db.get(SecretChatSession, token)
            if not session or not session.ai_autopilot:
                return
            replies, _ = _draft_reply(db, token, request, model, provider)
        reply = (replies[0] if replies else "").strip()
        if not reply:
            return

        with SessionLocal() as db:
            session = db.get(SecretChatSession, token)
            host_row = db.scalar(
                select(SecretChatParticipant).where(
                    SecretChatParticipant.session_token == token,
                    SecretChatParticipant.client_id == request.client_id,
                )
            )
            if not session or not session.ai_autopilot or host_row is None:
                return
            _set_typing(db, token, host_row, True)

        time.sleep(_autopilot_typing_seconds(reply))

        with SessionLocal() as db:
            session = db.get(SecretChatSession, token)
            if not session or not session.ai_autopilot or _room_finished(session):
                return
            message = SecretChatMessage(
                session_token=token,
                sender=f"{request.sender or 'Anonymous'}|||{request.client_id}",
                content=reply[:2000],
                via_ai=True,
            )
            db.add(message)
            session.last_activity = _now()
            db.commit()
            db.refresh(message)
            host_row = db.scalar(
                select(SecretChatParticipant).where(
                    SecretChatParticipant.session_token == token,
                    SecretChatParticipant.client_id == request.client_id,
                )
            )
            if host_row is not None:
                host_row.message_count = (host_row.message_count or 0) + 1
                host_row.last_read_id = max(host_row.last_read_id or 0, message.id)
                _set_typing(db, token, host_row, False)
            _broadcast(token, {"type": "message", **_message_payload(message, session.message_ttl_seconds)})
            # Autopilot writes straight to the table rather than through the post
            # endpoint, so the bridge has to be fed here too — this is what lets it
            # answer a Telegram DM while nobody is looking at Locus.
            _deliver_to_bridge(db, session, message)
    except Exception:  # noqa: BLE001 - a failed autopilot reply must not take the process down
        return


def _maybe_autopilot(db: Session, session: SecretChatSession, message: SecretChatMessage) -> None:
    """Kick off a reply when someone other than the host writes into an autopilot room."""
    if not session.ai_autopilot or message.via_ai:
        return
    author_client = _sender_client(message.sender)
    host = db.scalar(
        select(SecretChatParticipant).where(
            SecretChatParticipant.session_token == session.token,
            SecretChatParticipant.role == "host",
        )
    )
    if host is None or (author_client and author_client == host.client_id):
        return
    Thread(
        target=_run_autopilot,
        args=(session.token, message.id),
        name=f"locus-autopilot-{session.token}",
        daemon=True,
    ).start()


# ─── Stream ───

@router.get("/{token}/stream")
async def stream_secret_chat(token: str, after: int = 0, db: Session = Depends(get_db)):
    session = _load_room(db, token)
    ttl_seconds = session.message_ttl_seconds

    existing = db.scalars(
        select(SecretChatMessage)
        .where(SecretChatMessage.session_token == token, SecretChatMessage.id > after)
        .order_by(SecretChatMessage.id)
    ).all()
    existing_payload = [{"type": "message", **_message_payload(message, ttl_seconds)} for message in existing]

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        _secret_chat_queues(token).append(queue)
        try:
            for payload in existing_payload:
                yield f"data: {json.dumps(payload)}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25)
                    if payload is REVOKED:
                        # The room is gone. Say so before closing, so the client shows
                        # "chat ended" instead of reconnecting forever against a 404.
                        yield f"event: revoked\ndata: {json.dumps({'reason': 'deleted'})}\n\n"
                        return
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            with _SECRET_CHAT_EVENTS_LOCK:
                queues = _SECRET_CHAT_EVENTS.get(token, [])
                if queue in queues:
                    queues.remove(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

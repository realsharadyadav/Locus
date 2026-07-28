"""Secret Chat — standalone micro-feature for shareable real-time chat rooms."""

import asyncio
import json
import os
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import SecretChatMessage, SecretChatSession
from .schemas import (
    SecretChatCreateResponse,
    SecretChatMessageRead,
    SecretChatMessageSend,
    SecretChatSessionRead,
    SecretChatSessionSummary,
    SecretChatTitleUpdate,
)

router = APIRouter(prefix="/api/secret-chat", tags=["secret-chat"])

_SECRET_CHAT_EVENTS: dict[str, list[asyncio.Queue]] = {}
_SECRET_CHAT_EVENTS_LOCK = Lock()

# Pushed to every live stream when a room is deleted, so connected guests are cut
# off immediately instead of holding an open connection to a room that is gone.
REVOKED = object()


def _secret_chat_queues(token: str) -> list[asyncio.Queue]:
    with _SECRET_CHAT_EVENTS_LOCK:
        return _SECRET_CHAT_EVENTS.setdefault(token, [])


def _revoke_streams(token: str) -> None:
    with _SECRET_CHAT_EVENTS_LOCK:
        queues = _SECRET_CHAT_EVENTS.pop(token, [])
    for queue in queues:
        queue.put_nowait(REVOKED)


@router.post("", response_model=SecretChatCreateResponse, status_code=status.HTTP_201_CREATED)
def create_secret_chat(db: Session = Depends(get_db)):
    """Host-only (see auth.GUEST_SECRET_CHAT_ROUTES) — guests join rooms, they never open them."""
    token = uuid4().hex[:16]
    session = SecretChatSession(token=token)
    db.add(session)
    db.commit()
    host = os.getenv("SECRET_CHAT_HOST", "http://127.0.0.1:5173")
    # Guests join on the short neutral path; see src/secret-chat/links.js.
    return SecretChatCreateResponse(token=token, url=f"{host}/j/{token}")


@router.get("", response_model=list[SecretChatSessionSummary])
def list_secret_chats(db: Session = Depends(get_db)):
    """Host-only room list, newest activity first."""
    counts = dict(
        db.execute(
            select(SecretChatMessage.session_token, func.count(SecretChatMessage.id))
            .group_by(SecretChatMessage.session_token)
        ).all()
    )
    sessions = db.scalars(
        select(SecretChatSession).order_by(SecretChatSession.last_activity.desc())
    ).all()
    return [
        SecretChatSessionSummary(
            token=session.token,
            title=session.title,
            created_at=session.created_at,
            last_activity=session.last_activity,
            message_count=counts.get(session.token, 0),
        )
        for session in sessions
    ]


@router.patch("/{token}", response_model=SecretChatSessionRead)
def rename_secret_chat(token: str, payload: SecretChatTitleUpdate, db: Session = Depends(get_db)):
    """Host-only rename, so a list of rooms is tellable apart."""
    session = db.get(SecretChatSession, token)
    if not session:
        raise HTTPException(status_code=404, detail="Private chat not found")
    session.title = payload.title.strip() or "Private"
    db.commit()
    db.refresh(session)
    return session


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret_chat(token: str, db: Session = Depends(get_db)):
    """Host-only delete — this is what revokes a shared link.

    Messages go with the session via the cascade on the relationship, and live
    streams are cut so anyone currently in the room is dropped rather than left
    watching a room that no longer exists.
    """
    session = db.get(SecretChatSession, token)
    if not session:
        raise HTTPException(status_code=404, detail="Private chat not found")
    db.delete(session)
    db.commit()
    _revoke_streams(token)
    return None


@router.get("/{token}", response_model=SecretChatSessionRead)
def get_secret_chat(token: str, db: Session = Depends(get_db)):
    session = db.get(SecretChatSession, token)
    if not session:
        raise HTTPException(status_code=404, detail="Private chat not found")
    return session


@router.get("/{token}/messages", response_model=list[SecretChatMessageRead])
def get_secret_chat_messages(token: str, after: int = 0, db: Session = Depends(get_db)):
    session = db.get(SecretChatSession, token)
    if not session:
        raise HTTPException(status_code=404, detail="Private chat not found")
    messages = db.scalars(
        select(SecretChatMessage)
        .where(SecretChatMessage.session_token == token, SecretChatMessage.id > after)
        .order_by(SecretChatMessage.id)
    ).all()
    return messages


@router.post("/{token}/messages", response_model=SecretChatMessageRead, status_code=status.HTTP_201_CREATED)
def send_secret_chat_message(token: str, payload: SecretChatMessageSend, db: Session = Depends(get_db)):
    session = db.get(SecretChatSession, token)
    if not session:
        raise HTTPException(status_code=404, detail="Private chat not found")
    message = SecretChatMessage(session_token=token, sender=payload.sender, content=payload.content)
    db.add(message)
    session.last_activity = datetime.now(timezone.utc)
    db.commit()
    db.refresh(message)
    for queue in _secret_chat_queues(token):
        queue.put_nowait(message)
    return message


@router.get("/{token}/stream")
async def stream_secret_chat(token: str, after: int = 0, db: Session = Depends(get_db)):
    session = db.get(SecretChatSession, token)
    if not session:
        raise HTTPException(status_code=404, detail="Private chat not found")

    existing = db.scalars(
        select(SecretChatMessage)
        .where(SecretChatMessage.session_token == token, SecretChatMessage.id > after)
        .order_by(SecretChatMessage.id)
    ).all()
    existing_payload = [{'id': m.id, 'sender': m.sender, 'content': m.content, 'created_at': m.created_at.isoformat()} for m in existing]

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        _secret_chat_queues(token).append(queue)
        try:
            for payload in existing_payload:
                yield f"data: {json.dumps(payload)}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    if msg is REVOKED:
                        # The host deleted the room. Tell the client why before
                        # closing, so it can show "chat ended" instead of
                        # reconnecting forever against a 404.
                        yield f"event: revoked\ndata: {json.dumps({'reason': 'deleted'})}\n\n"
                        return
                    payload = {'id': msg.id, 'sender': msg.sender, 'content': msg.content, 'created_at': msg.created_at.isoformat()}
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

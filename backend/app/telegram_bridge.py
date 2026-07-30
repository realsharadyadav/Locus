"""Telegram transport for Private chats — your own account, over MTProto.

This is deliberately *not* a bot. A Telegram bot cannot open a conversation with
someone by phone number; the person has to find the bot and press start first. The
whole point of this bridge is that the host types a mobile number in Locus and the
guest gets a normal Telegram message from the host's own account, so the account
itself has to be the transport. That is what MTProto (Telethon) gives us.

Three things are worth knowing before editing this module:

* **Nothing here imports at module scope that isn't stdlib.** Telethon is an optional
  dependency and the env vars are usually unset, so `configured()` is false and the app
  boots exactly as before. `secret_chat.py` calls into this module unconditionally and
  gets a no-op.
* **One background loop, owned here.** Telethon is asyncio and long-lived; FastAPI's
  handlers are sync. A single daemon thread runs a private event loop with the client
  attached to it, and every public function in this module is a *sync* wrapper that
  hands work to that loop and waits. Never await these from a request handler.
* **Inbound is a callback, not an import.** `secret_chat.py` registers a handler with
  `set_inbound_handler()` at import time. Going the other way — this module importing
  `secret_chat` — would be a cycle, and it would also make the transport untestable
  without a real Telegram session.

Setup is one-time and interactive (Telegram sends a login code):

    python scripts/telegram_login.py

which prints a session string for `LOCUS_TELEGRAM_SESSION`. See docs/RUNBOOK.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

# The bridge only ever talks to numbers the host typed in themselves, but Telegram
# rate-limits contact imports hard, so a resolve failure has to stay a normal error.
RESOLVE_TIMEOUT_SECONDS = 30
SEND_TIMEOUT_SECONDS = 30
START_TIMEOUT_SECONDS = 45

_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class TelegramBridgeError(RuntimeError):
    """Anything the host should see as a message rather than a 500."""


@dataclass(frozen=True)
class ResolvedPeer:
    peer_id: str
    display_name: str
    username: str = ""


@dataclass(frozen=True)
class InboundMessage:
    peer_id: str
    sender_name: str
    text: str


InboundHandler = Callable[[InboundMessage], None]

_inbound_handler: InboundHandler | None = None


def set_inbound_handler(handler: InboundHandler) -> None:
    """Register who receives messages arriving from Telegram. Called by `secret_chat`."""
    global _inbound_handler
    _inbound_handler = handler


def normalize_phone(raw: str) -> str:
    """E.164 or nothing — Telegram will not resolve a number without a country code.

    A bare local number is rejected rather than prefixed: guessing a country code would
    silently message a stranger in another country who happens to hold that number.
    """
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("00"):
        digits = f"+{digits[2:]}"
    if not _PHONE_RE.match(digits):
        raise TelegramBridgeError(
            "Enter the number in international format, including the country code — e.g. +919876543210"
        )
    return digits


# ─── Configuration ───

def api_id() -> int:
    raw = (os.getenv("LOCUS_TELEGRAM_API_ID") or "").strip()
    try:
        return int(raw)
    except ValueError:
        return 0


def api_hash() -> str:
    return (os.getenv("LOCUS_TELEGRAM_API_HASH") or "").strip()


def session_string() -> str:
    return (os.getenv("LOCUS_TELEGRAM_SESSION") or "").strip()


def configured() -> bool:
    """True when this deployment has credentials for a Telegram account."""
    return bool(api_id() and api_hash() and session_string())


def telethon_available() -> bool:
    try:
        import telethon  # noqa: F401
    except ImportError:
        return False
    return True


# ─── The client thread ───

class _Runtime:
    """Owns the event loop, the Telethon client and the thread the two live on."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client = None
        self._ready = threading.Event()
        self._error: str = ""
        self._me: str = ""

    # -- lifecycle --

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._ready.clear()
            self._error = ""
            self._thread = threading.Thread(target=self._run, name="locus-telegram", daemon=True)
            self._thread.start()
        # Waiting here means the first host action gets a real answer instead of
        # "not connected yet" on a cold process.
        self._ready.wait(timeout=START_TIMEOUT_SECONDS)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._connect())
            if self._client is not None:
                loop.run_forever()
        except Exception as exc:  # noqa: BLE001 - a dead bridge must not kill the app
            self._error = str(exc)
            logger.warning("Telegram bridge failed to start: %s", exc)
        finally:
            self._ready.set()
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass
            self._loop = None
            self._client = None

    async def _connect(self) -> None:
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession

        client = TelegramClient(StringSession(session_string()), api_id(), api_hash())
        await client.connect()
        if not await client.is_user_authorized():
            self._error = "Telegram session is not authorised — re-run scripts/telegram_login.py"
            await client.disconnect()
            return

        me = await client.get_me()
        self._me = _peer_name(me)

        @client.on(events.NewMessage(incoming=True))
        async def _on_message(event):  # pragma: no cover - needs a live account
            if not event.is_private:
                return
            handler = _inbound_handler
            if handler is None:
                return
            sender = await event.get_sender()
            inbound = InboundMessage(
                peer_id=str(event.chat_id),
                sender_name=_peer_name(sender),
                text=(event.raw_text or "").strip(),
            )
            if not inbound.text:
                return
            # Hand off to a plain thread: the handler does blocking SQLAlchemy work and
            # would otherwise stall every other Telegram update behind it.
            threading.Thread(
                target=_safe_inbound,
                args=(handler, inbound),
                name="locus-telegram-inbound",
                daemon=True,
            ).start()

        self._client = client
        self._error = ""
        self._ready.set()

    # -- calls from request handlers --

    def _submit(self, coro, timeout: float):
        loop = self._loop
        client = self._client
        if loop is None or client is None:
            raise TelegramBridgeError(self._error or "Telegram is not connected")
        future = asyncio.run_coroutine_threadsafe(coro(client), loop)
        try:
            return future.result(timeout=timeout)
        except TelegramBridgeError:
            raise
        except Exception as exc:  # noqa: BLE001 - Telethon raises a wide family
            raise TelegramBridgeError(_readable(exc)) from exc

    def resolve(self, phone: str) -> ResolvedPeer:
        async def _work(client):
            from telethon.tl.functions.contacts import ImportContactsRequest
            from telethon.tl.types import InputPhoneContact

            try:
                entity = await client.get_entity(phone)
            except Exception:  # noqa: BLE001 - unknown numbers need the contact import path
                entity = None
            if entity is None:
                result = await client(ImportContactsRequest([
                    InputPhoneContact(client_id=0, phone=phone, first_name=phone, last_name="")
                ]))
                if not result.users:
                    raise TelegramBridgeError(
                        "That number is not on Telegram, or its privacy settings hide it from new contacts."
                    )
                entity = result.users[0]
            return ResolvedPeer(
                peer_id=str(entity.id),
                display_name=_peer_name(entity),
                username=getattr(entity, "username", "") or "",
            )

        return self._submit(_work, RESOLVE_TIMEOUT_SECONDS)

    def send(self, peer_id: str, text: str) -> None:
        async def _work(client):
            await client.send_message(int(peer_id), text)
            return None

        self._submit(_work, SEND_TIMEOUT_SECONDS)

    def status(self) -> dict:
        return {
            "connected": self._client is not None,
            "account": self._me,
            "error": self._error,
        }


_runtime = _Runtime()


def _safe_inbound(handler: InboundHandler, message: InboundMessage) -> None:
    try:
        handler(message)
    except Exception:  # noqa: BLE001 - one bad inbound message must not kill the bridge
        logger.exception("Telegram inbound handler failed")


def _peer_name(entity) -> str:
    if entity is None:
        return "Telegram"
    first = (getattr(entity, "first_name", "") or "").strip()
    last = (getattr(entity, "last_name", "") or "").strip()
    name = " ".join(part for part in (first, last) if part)
    return name or (getattr(entity, "username", "") or "").strip() or "Telegram"


def _readable(exc: Exception) -> str:
    text = str(exc).strip()
    lowered = text.lower()
    if "wait of" in lowered and "seconds" in lowered:
        return "Telegram is rate-limiting this account. Wait a few minutes and try again."
    if "privacy" in lowered:
        return "That person's Telegram privacy settings do not allow messages from you."
    return text or exc.__class__.__name__


# ─── Public API (all sync, safe to call from a request handler) ───

def start() -> None:
    """Connect the account if this deployment has one. Safe to call repeatedly."""
    if not configured():
        return
    if not telethon_available():
        logger.warning("LOCUS_TELEGRAM_* is set but telethon is not installed — bridge stays off")
        return
    _runtime.start()


def status() -> dict:
    if not configured():
        return {"configured": False, "connected": False, "account": "", "error": ""}
    if not telethon_available():
        return {
            "configured": True,
            "connected": False,
            "account": "",
            "error": "telethon is not installed on this deployment",
        }
    start()
    return {"configured": True, **_runtime.status()}


def resolve_contact(phone: str) -> ResolvedPeer:
    _require_ready()
    return _runtime.resolve(normalize_phone(phone))


def send_text(peer_id: str, text: str) -> None:
    _require_ready()
    _runtime.send(peer_id, text)


def _require_ready() -> None:
    if not configured():
        raise TelegramBridgeError(
            "Telegram is not set up on this deployment. Add LOCUS_TELEGRAM_API_ID, "
            "LOCUS_TELEGRAM_API_HASH and LOCUS_TELEGRAM_SESSION — see docs/RUNBOOK.md."
        )
    if not telethon_available():
        raise TelegramBridgeError("telethon is not installed on this deployment")
    start()

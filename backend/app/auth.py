"""Phase 1 authentication — a single shared password gate.

This is deliberately *not* user accounts. Everyone who knows the password sees
the same workspace: the same libraries, files and chat history. The point is to
keep a deployed Locus off the open internet without touching the data model, so
there is no new table and nothing to migrate. Real per-user isolation needs an
owner column on every table plus scoped vector retrieval — see AGENTS.md.

Auth is off unless ``LOCUS_AUTH_PASSWORD`` is set, which keeps local dev and the
test suite working untouched.

Tokens are stateless: a signed ``{"exp": ...}`` payload, verified with an HMAC
derived from the password. That means logout is purely client-side (drop the
token) and changing the password invalidates every token already issued.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from .schemas import AuthLoginRequest, AuthLoginResponse, AuthStatusRead


router = APIRouter(prefix="/api/auth", tags=["auth"])

# Paths reachable without a token.
PUBLIC_PATHS = {"/api/health", "/api/auth/status", "/api/auth/login"}

# Secret Chat is split rather than blanket-public. A guest holding a share link
# needs exactly these five calls — read the room, read and post messages, stream
# (EventSource cannot send an Authorization header, so the stream has to be
# reachable on the token alone), and check in so the room can show them as online,
# typing and up to date. Everything else under the prefix — listing rooms, creating,
# changing options, participant details, the AI copilot, clearing and deleting — is
# the host's and stays guarded, and is separately checked against their host key.
GUEST_SECRET_CHAT_ROUTES = (
    ("GET", re.compile(r"^/api/secret-chat/[a-f0-9]+$")),
    ("GET", re.compile(r"^/api/secret-chat/[a-f0-9]+/messages$")),
    ("POST", re.compile(r"^/api/secret-chat/[a-f0-9]+/messages$")),
    ("GET", re.compile(r"^/api/secret-chat/[a-f0-9]+/stream$")),
    ("POST", re.compile(r"^/api/secret-chat/[a-f0-9]+/presence$")),
)

LOGIN_MAX_FAILURES = 10
LOGIN_FAILURE_WINDOW_SECONDS = 900

_login_failures: dict[str, list[float]] = {}
_login_failures_lock = Lock()


def auth_password() -> str:
    return os.getenv("LOCUS_AUTH_PASSWORD", "").strip()


def auth_enabled() -> bool:
    """Auth is opt-in: no password configured means the gate is not installed."""
    return bool(auth_password())


def _signing_key() -> bytes:
    secret = os.getenv("LOCUS_AUTH_SECRET", "").strip()
    # Deriving from the password by default is intentional — rotating the
    # password should log everyone out, and it saves operators one env var.
    return hashlib.sha256((secret or f"locus-auth:{auth_password()}").encode()).digest()


def _session_seconds() -> int:
    return max(1, int(os.getenv("LOCUS_AUTH_SESSION_DAYS", "30"))) * 86400


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_token() -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_session_seconds())
    payload = _b64encode(json.dumps({"exp": int(expires_at.timestamp())}).encode())
    signature = _b64encode(hmac.new(_signing_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}", expires_at


def token_expiry(token: str) -> datetime | None:
    """Return the token's expiry, or None when it is malformed, forged or expired."""
    payload, _, signature = (token or "").partition(".")
    if not payload or not signature:
        return None
    expected = _b64encode(hmac.new(_signing_key(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        claims = json.loads(_b64decode(payload))
        expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return expires_at if expires_at > datetime.now(timezone.utc) else None


def verify_token(token: str) -> bool:
    return token_expiry(token) is not None


def bearer_token(authorization: str | None) -> str:
    scheme, _, value = (authorization or "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def is_public(method: str, path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return any(method == verb and pattern.match(path) for verb, pattern in GUEST_SECRET_CHAT_ROUTES)


def _login_blocked(client: str) -> bool:
    """Coarse brute-force brake — one shared password is the whole secret."""
    cutoff = time.monotonic() - LOGIN_FAILURE_WINDOW_SECONDS
    with _login_failures_lock:
        recent = [stamp for stamp in _login_failures.get(client, []) if stamp > cutoff]
        _login_failures[client] = recent
        return len(recent) >= LOGIN_MAX_FAILURES


def _record_login_failure(client: str) -> None:
    with _login_failures_lock:
        _login_failures.setdefault(client, []).append(time.monotonic())


def _clear_login_failures(client: str) -> None:
    with _login_failures_lock:
        _login_failures.pop(client, None)


async def require_auth(request: Request, call_next):
    """Guard every route except the public allowlist.

    Registered before the CORS middleware so CORS stays the outer layer and a
    401 still carries the headers the browser needs to read it.
    """
    if request.method == "OPTIONS" or not auth_enabled() or is_public(request.method, request.url.path):
        return await call_next(request)
    if verify_token(bearer_token(request.headers.get("authorization"))):
        return await call_next(request)
    return JSONResponse({"detail": "Sign in to continue"}, status_code=status.HTTP_401_UNAUTHORIZED)


@router.get("/status", response_model=AuthStatusRead)
def auth_status():
    """Public so the login screen knows whether to render at all."""
    return AuthStatusRead(auth_required=auth_enabled())


@router.post("/login", response_model=AuthLoginResponse)
def login(payload: AuthLoginRequest, request: Request):
    if not auth_enabled():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password sign-in is not enabled on this deployment")
    client = request.client.host if request.client else "unknown"
    if _login_blocked(client):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed attempts. Try again later.")
    if not hmac.compare_digest(payload.password, auth_password()):
        _record_login_failure(client)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")
    _clear_login_failures(client)
    token, expires_at = issue_token()
    return AuthLoginResponse(token=token, expires_at=expires_at)


@router.get("/me", response_model=AuthStatusRead)
def auth_me(authorization: str | None = Header(default=None)):
    """Guarded by the middleware — reaching here means the token is good."""
    if not auth_enabled():
        return AuthStatusRead(auth_required=False, authenticated=True)
    return AuthStatusRead(auth_required=True, authenticated=True, expires_at=token_expiry(bearer_token(authorization)))

"""Opt-in native manager notifications. Disabled until explicitly configured.
Apply only after the release security patches and verify the live DB adapter.
Never send restaurant names, notice text, financial data or access links to FCM.
"""
import hashlib
import hmac
import json
import logging
import os
import re
import time
from contextlib import closing
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/push")
log = logging.getLogger(__name__)
OPAQUE = re.compile(r"^[A-Za-z0-9_-]{43}$")
LEASE_SECONDS = 30 * 24 * 60 * 60


def db():
    from database import get_db
    return get_db()


def scope(token):
    from mountain_routes import scope_of_token
    return scope_of_token(token)


def owner(org):
    from mountain_routes import _owner_of
    return _owner_of(org)


def cipher():
    # Unlike the legacy password helper, never fall back to plaintext.
    return Fernet(os.environ["ENCRYPTION_KEY"].encode())


def configured():
    try:
        cipher()
        return (os.getenv("PUSH_ENABLED") == "1" and
                os.getenv("FIREBASE_PROJECT_ID") == "findirector" and
                Path(os.environ["FIREBASE_SERVICE_ACCOUNT_FILE"]).is_file())
    except (KeyError, ValueError):
        return False


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def manager(token):
    if not token or len(token) > 4096:
        raise HTTPException(401, "Authentication required")
    sc = scope(token)
    if not sc.get("valid") or sc.get("role") != "manager" or sc.get("demo"):
        raise HTTPException(403, "Manager access required")
    branches = sc.get("branches", [])
    if len(branches) != 1:
        raise HTTPException(403, "Single branch required")
    org = branches[0]["organization_id"]
    uid = int(owner(org) or 0)
    if not uid or org.startswith("demo-"):
        raise HTTPException(403, "Live branch required")
    return org, uid


def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS native_push_devices (
        installation TEXT PRIMARY KEY, secret_hash TEXT NOT NULL,
        binding TEXT NOT NULL, principal TEXT NOT NULL, org TEXT NOT NULL,
        owner INTEGER NOT NULL, access_cipher TEXT NOT NULL,
        token_cipher TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
        platform TEXT NOT NULL, expires INTEGER NOT NULL
    )""")
    conn.execute("DELETE FROM native_push_devices WHERE expires < ?", (int(time.time()),))


class Revoke(BaseModel):
    installation: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")
    secret: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


class Registration(Revoke):
    binding: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")
    token: str = Field(min_length=20, max_length=4096, pattern=r"^[A-Za-z0-9_:\-]+$")
    platform: str = Field(pattern=r"^(android|ios)$")


@router.get("/status")
def status(x_site_token: str = Header(default="")):
    manager(x_site_token)
    return {"enabled": configured()}


@router.post("/devices")
def register(payload: Registration, x_site_token: str = Header(default="")):
    org, uid = manager(x_site_token)
    if not configured():
        raise HTTPException(503, "Push delivery unavailable")
    secret_hash = digest(payload.secret)
    principal = digest(x_site_token)
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure(conn)
        existing = conn.execute("SELECT secret_hash FROM native_push_devices WHERE installation=?", (payload.installation,)).fetchone()
        if existing and not hmac.compare_digest(existing[0], secret_hash):
            raise HTTPException(403, "Binding not owned")
        occupied = conn.execute("SELECT installation FROM native_push_devices WHERE token_hash=?", (digest(payload.token),)).fetchone()
        if occupied and occupied[0] != payload.installation:
            raise HTTPException(409, "Device address already bound")
        count = conn.execute("SELECT COUNT(*) FROM native_push_devices WHERE principal=?", (principal,)).fetchone()[0]
        if not existing and count >= 20:
            raise HTTPException(429, "Device limit reached")
        c = cipher()
        conn.execute("INSERT OR REPLACE INTO native_push_devices VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            payload.installation, secret_hash, payload.binding, principal, org, uid,
            c.encrypt(x_site_token.encode()).decode(), c.encrypt(payload.token.encode()).decode(),
            digest(payload.token), payload.platform, int(time.time()) + LEASE_SECONDS,
        ))
        conn.commit()
    return {"ok": True}


@router.post("/devices/revoke")
def revoke(payload: Revoke):
    # Revocation capability is 256 random bits, stored only in device secure storage.
    # It can only delete its own binding and cannot read data or send messages.
    with closing(db()) as conn:
        ensure(conn)
        conn.execute("DELETE FROM native_push_devices WHERE installation=? AND secret_hash=?", (payload.installation, digest(payload.secret)))
        conn.commit()
    return {"ok": True}


def fcm_send(token, binding):
    import requests
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    credentials = service_account.Credentials.from_service_account_file(
        os.environ["FIREBASE_SERVICE_ACCOUNT_FILE"], scopes=["https://www.googleapis.com/auth/firebase.messaging"])
    if credentials.project_id != os.environ["FIREBASE_PROJECT_ID"]:
        raise ValueError("Unexpected Firebase project")
    request = Request()
    credentials.refresh(lambda *args, **kwargs: request(*args, **{**kwargs, "timeout": 10}))
    response = requests.post(
        "https://fcm.googleapis.com/v1/projects/findirector/messages:send",
        headers={"Authorization": "Bearer " + credentials.token}, timeout=10,
        json={"message": {
            "token": token,
            "notification": {"title": "Финдиректор", "body": "Новое сообщение. Откройте приложение."},
            "data": {"kind": "notice", "binding": binding},
            "android": {"priority": "high", "ttl": "60s", "notification": {"visibility": "PRIVATE"}},
            "apns": {"headers": {"apns-expiration": str(int(time.time()) + 60)}, "payload": {"aps": {"sound": "default"}}},
        }})
    if response.status_code == 200:
        return "sent"
    # Do not log provider response bodies, credentials, recipient tokens or payloads.
    if response.status_code == 404:
        try:
            details = response.json().get("error", {}).get("details", [])
            if any(d.get("errorCode") == "UNREGISTERED" for d in details):
                return "unregistered"
        except (ValueError, AttributeError):
            pass
    return "failed"


def send_notice(author, orgs):
    """Best effort background signal. The persisted inbox remains authoritative."""
    if not configured() or not orgs:
        return
    with closing(db()) as conn:
        ensure(conn)
        rows = conn.execute("SELECT * FROM native_push_devices WHERE owner=?", (int(author),)).fetchall()
        conn.commit()
    allowed = set(orgs)
    for row in rows:
        row = dict(row)
        if row["org"] not in allowed:
            continue
        try:
            c = cipher()
            org, uid = manager(c.decrypt(row["access_cipher"].encode()).decode())
            if org != row["org"] or uid != int(author):
                raise HTTPException(403, "Access changed")
            # Avoid delivering an old registration after logout/rebind.
            with closing(db()) as conn:
                current = conn.execute("SELECT binding, token_hash FROM native_push_devices WHERE installation=?", (row["installation"],)).fetchone()
            if not current or tuple(current) != (row["binding"], row["token_hash"]):
                continue
            result = fcm_send(c.decrypt(row["token_cipher"].encode()).decode(), row["binding"])
            if result == "unregistered":
                with closing(db()) as conn:
                    conn.execute("DELETE FROM native_push_devices WHERE installation=? AND binding=? AND token_hash=?", (row["installation"], row["binding"], row["token_hash"]))
                    conn.commit()
        except (HTTPException, InvalidToken):
            with closing(db()) as conn:
                conn.execute("DELETE FROM native_push_devices WHERE installation=? AND binding=? AND token_hash=?", (row["installation"], row["binding"], row["token_hash"]))
                conn.commit()
        except Exception:
            log.warning("Native push delivery failed; inbox message remains available")

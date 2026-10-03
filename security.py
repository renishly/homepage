"""Login and secret checks used by the routes in main.py.

- require_user protects the dashboard (your browser shows a login popup).
- require_csrf protects every dashboard button and form from other websites
  (see the explanation above csrf_token below).
- require_agent protects the API: each agent sends its own key in a header,
  and the key tells us which agent is calling.
- edit_password_matches guards deleting an agent and viewing/replacing its key.
- encrypt_api_key / decrypt_api_key let "View key" show a key again.

Secrets are read from environment variables on every request, so changing
them only needs a restart, never a code change.
"""

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPBasic, HTTPBasicCredentials
from sqlmodel import Session, select

from db import Agent, get_session, utc_now

basic_auth = HTTPBasic()
# auto_error=False lets us return our own 401 message when the header is missing.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def secret_matches(given: str | None, expected: str | None) -> bool:
    """Safely compare a value someone sent with the real secret.

    Returns False if the real secret is missing or empty, so an unset
    environment variable can never be "matched" by an empty value.
    """
    if not expected or given is None:
        return False
    # compare_digest takes the same time whether the first or last character
    # differs, so attackers can't guess the secret one character at a time.
    return secrets.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


# ---------------------------------------------------------------------------
# Dashboard login
# ---------------------------------------------------------------------------


def require_user(credentials: HTTPBasicCredentials = Depends(basic_auth)) -> str:
    """Allow the request only if the browser sent the right username and password."""
    username_ok = secret_matches(credentials.username, os.getenv("DASHBOARD_USER"))
    password_ok = secret_matches(credentials.password, os.getenv("DASHBOARD_PASSWORD"))
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            # This header tells the browser to show its login popup.
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ---------------------------------------------------------------------------
# CSRF protection
#
# CSRF ("cross-site request forgery") is when another website you visit makes
# your browser send a request to this dashboard. The browser would helpfully
# attach your saved login, so without protection that request would work.
#
# The fix: every dashboard page contains a secret token, and every button or
# form must send it back. Another website can make your browser send a
# request, but it can't read our pages, so it can't know the token.
#
# The token is an HMAC of your username, keyed with your dashboard password.
# Only someone who knows the password can work it out, and it changes
# whenever the password changes. It is only put in pages behind the login.
# ---------------------------------------------------------------------------


def csrf_token() -> str:
    """The token every dashboard button and form must send back."""
    password = os.getenv("DASHBOARD_PASSWORD", "")
    username = os.getenv("DASHBOARD_USER", "")
    return hmac.new(password.encode(), f"csrf:{username}".encode(), hashlib.sha256).hexdigest()


async def require_csrf(request: Request, user: str = Depends(require_user)) -> None:
    """Refuse a dashboard action unless it carries the right CSRF token.

    HTMX buttons send the token in an X-CSRF-Token header (set once on the
    page's <body>); plain HTML forms send it in a hidden csrf_token field.
    Depending on require_user means a missing login is still reported as 401.
    """
    token = request.headers.get("X-CSRF-Token")
    if token is None:
        form = await request.form()  # FastAPI reuses this for the route's Form(...) fields
        token = form.get("csrf_token")
    if not secret_matches(str(token) if token is not None else None, csrf_token()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or invalid CSRF token. Reload the page and try again.",
        )


# ---------------------------------------------------------------------------
# Agent API keys
# ---------------------------------------------------------------------------


def generate_api_key() -> str:
    """A new random API key (64 hex characters)."""
    return secrets.token_hex(32)


def hash_api_key(api_key: str) -> str:
    """The fingerprint of an API key, used to look agents up by their key.

    SHA-256 is fine here (rather than a slow password hash) because API keys
    are long and random, so they can't be guessed from the fingerprint.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class KeyEncryptionNotConfigured(Exception):
    """Raised when KEY_ENCRYPTION_SECRET is missing, so keys can't be stored or shown."""


def _fernet() -> Fernet:
    """The encrypter/decrypter for API keys, built from KEY_ENCRYPTION_SECRET.

    Fernet needs exactly 32 bytes in a special format, so we turn whatever
    secret you chose into that with SHA-256. Any long random string works.
    """
    secret = os.getenv("KEY_ENCRYPTION_SECRET", "")
    if not secret:
        raise KeyEncryptionNotConfigured("KEY_ENCRYPTION_SECRET is not set.")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_api_key(api_key: str) -> str:
    """Scramble a key so it can be stored in the database."""
    return _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted: str) -> str | None:
    """Unscramble a stored key. None if it can't be (e.g. the secret changed)."""
    try:
        return _fernet().decrypt(encrypted.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


def require_agent(
    api_key: str | None = Depends(api_key_header),
    session: Session = Depends(get_session),
) -> Agent:
    """Find the agent that owns this X-API-Key, or refuse the request.

    Also records that the agent was just seen, which keeps it "online".
    """
    agent = None
    if api_key:  # an empty or missing key never matches anything
        # Looking up the key's fingerprint means the database compares hashes,
        # not the secret key itself.
        statement = select(Agent).where(Agent.api_key_hash == hash_api_key(api_key))
        agent = session.exec(statement).first()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )
    agent.last_seen = utc_now()
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


# ---------------------------------------------------------------------------
# Agent editing password
# ---------------------------------------------------------------------------


def edit_password_matches(given: str | None) -> bool:
    """True if `given` is the AGENT_EDIT_PASSWORD. Always False if none is set.

    Needed to delete an agent and to view or replace its API key.
    """
    return secret_matches(given, os.getenv("AGENT_EDIT_PASSWORD"))

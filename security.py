"""Login and secret checks used by the routes in main.py.

- require_user protects the dashboard: only browsers signed in on the login
  page (/login) get in. Each signed-in device has its own session, which ends
  after a day, when it logs out, or when the dashboard password changes.
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
from datetime import timedelta, timezone
from urllib.parse import quote, urlparse

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlmodel import Session, delete, select

from db import Agent, LoginSession, TechSetting, get_session, utc_now

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


# How it works:
#   1. You sign in on /login with DASHBOARD_USER and DASHBOARD_PASSWORD.
#   2. The site makes a long random token, stores its fingerprint in the
#      LoginSession table, and gives the token to that browser in a cookie.
#   3. Every dashboard request must bring that cookie. Other devices don't
#      have it, so they have to sign in themselves.
# A sign-in lasts SESSION_LIFETIME, and ends early when that device logs out,
# when you choose "Sign out all devices", or when DASHBOARD_PASSWORD changes.
# The cookie can't be read by page scripts (HttpOnly), isn't sent by other
# websites' requests (SameSite=Lax), and only travels over https on a
# deployed site (Secure).

SESSION_COOKIE = "dashboard_session"
GUEST_NAME = "guest"  # the name guests are signed in under ("as guest?")
# A device can be signed into several accounts at once (for now: you and
# Guest), one sign-in each; SESSION_COOKIE then holds their tokens, separated
# by dots. Which one is in use: the highest-ranked (you, then Guest), unless
# ACTIVE_COOKIE says "guest" because "as guest?" was chosen. It only picks
# among sign-ins the device really holds, so it can't grant anything.
ACTIVE_COOKIE = "dashboard_active"
SESSION_LIFETIME = timedelta(days=1)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def login_details_match(username: str | None, password: str | None) -> bool:
    """True if these are DASHBOARD_USER and DASHBOARD_PASSWORD (never if either is unset)."""
    username_ok = secret_matches(username, os.getenv("DASHBOARD_USER"))
    password_ok = secret_matches(password, os.getenv("DASHBOARD_PASSWORD"))
    return username_ok and password_ok


def _login_check() -> str:
    """A fingerprint of the current login details, stored with each sign-in.

    When DASHBOARD_USER or DASHBOARD_PASSWORD changes, this changes too, and
    every existing sign-in stops working.
    """
    password = os.getenv("DASHBOARD_PASSWORD", "")
    username = os.getenv("DASHBOARD_USER", "")
    return hmac.new(password.encode(), f"login:{username}".encode(), hashlib.sha256).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(moment):
    """SQLite forgets time zones; every time we store is UTC."""
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def start_login(db: Session, username: str, user_agent: str | None) -> str:
    """Sign a device in: store a new session and return the token for its cookie.

    Also tidies away sessions that have already expired.
    """
    now = utc_now()
    db.exec(delete(LoginSession).where(LoginSession.expires_at < now))
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(
        token_hash=_token_hash(token),
        username=username,
        login_check=_login_check(),
        user_agent=(user_agent or "")[:200] or None,
        created_at=now,
        expires_at=now + SESSION_LIFETIME,
    ))
    db.commit()
    return token


def find_login(db: Session, token: str | None) -> LoginSession | None:
    """The still-valid sign-in this cookie token belongs to, or None."""
    if not token:
        return None
    login = db.exec(select(LoginSession).where(LoginSession.token_hash == _token_hash(token))).first()
    if login is None:
        return None
    if _as_utc(login.expires_at) <= utc_now() or not secret_matches(login.login_check, _login_check()):
        return None
    return login


def end_login(db: Session, token: str | None, everywhere: bool = False) -> None:
    """Sign out this device (or, with everywhere=True, every device)."""
    if everywhere:
        db.exec(delete(LoginSession))
    elif token:
        db.exec(delete(LoginSession).where(LoginSession.token_hash == _token_hash(token)))
    db.commit()


def account_rank(username: str) -> int:
    """Higher means more permissions: you (signed in with the password) over Guest."""
    return 0 if username == GUEST_NAME else 1


def device_logins(db: Session, request: Request) -> list[tuple[str, LoginSession]]:
    """Every still-valid sign-in this device holds: (token, sign-in) pairs."""
    tokens = [token for token in (request.cookies.get(SESSION_COOKIE) or "").split(".") if token]
    pairs = []
    for token in tokens:
        login = find_login(db, token)
        if login is not None:
            pairs.append((token, login))
    return pairs


def current_login(db: Session, request: Request) -> LoginSession | None:
    """The sign-in in use on this device: Guest if "as guest?" chose it,
    otherwise the highest-ranked account the device is signed into."""
    logins = [login for _, login in device_logins(db, request)]
    if not logins:
        return None
    if request.cookies.get(ACTIVE_COOKIE) == GUEST_NAME:
        for login in logins:
            if login.username == GUEST_NAME:
                return login
    return max(logins, key=lambda login: account_rank(login.username))


def end_device_logins(db: Session, request: Request) -> None:
    """Sign this device out of every account it's signed into."""
    for token in (request.cookies.get(SESSION_COOKIE) or "").split("."):
        if token:
            end_login(db, token)


def cookie_is_secure(request: Request) -> bool:
    """Send the cookie over https only, except on this computer (http://localhost)."""
    return request.url.hostname not in LOCAL_HOSTS


def _not_signed_in(request: Request) -> HTTPException:
    """The reply for a dashboard request without a valid sign-in.

    - A page opened in the browser: go to the login page, then come back.
    - An HTMX request (a button, or a part of the page refreshing itself):
      tell HTMX to load the login page (HX-Redirect).
    - Anything else (e.g. a script): a plain 401.
    """
    if request.headers.get("HX-Request"):
        page = urlparse(request.headers.get("HX-Current-URL", "")).path
        target = "/login" + (f"?next={quote(page, safe='')}" if page.startswith("/dashboard") else "")
        return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"HX-Redirect": target})
    if "text/html" in request.headers.get("accept", ""):
        page = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if request.method != "GET":
            page = "/dashboard"
        return HTTPException(status.HTTP_303_SEE_OTHER, "Not signed in",
                             headers={"Location": f"/login?next={quote(page, safe='')}"})
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")


def tech_visibility(db: Session, slug: str) -> str:
    """"open", "private" or "hidden": who may open this tech (set in developer mode)."""
    setting = db.get(TechSetting, slug)
    return setting.visibility if setting else "open"


def _guest_not_allowed(request: Request) -> HTTPException:
    """A guest opening a page that's set to Private or Hidden: back to the tree."""
    if request.headers.get("HX-Request"):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Not open to guests", headers={"HX-Redirect": "/tree"})
    if "text/html" in request.headers.get("accept", ""):
        return HTTPException(status.HTTP_303_SEE_OTHER, "Not open to guests", headers={"Location": "/tree"})
    return HTTPException(status.HTTP_403_FORBIDDEN, "Not open to guests")


def require_user(request: Request, db: Session = Depends(get_session)) -> str:
    """Allow the request only from a browser that's signed in (see above).

    Guests are also kept out of the dashboard while its tech is set to Private
    or Hidden in developer mode.
    """
    login = current_login(db, request)
    if login is None:
        raise _not_signed_in(request)
    if (
        login.username == GUEST_NAME
        and request.url.path.startswith("/dashboard")
        and tech_visibility(db, "dashboard") != "open"
    ):
        raise _guest_not_allowed(request)
    return login.username


def require_owner(user: str = Depends(require_user)) -> str:
    """Only you (signed in with the password), never a guest: for developer mode."""
    if user == GUEST_NAME:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can change this")
    return user


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

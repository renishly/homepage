"""The website: public pages, the dashboard, and the agent API.

Run locally with:   fastapi dev main.py
Then open:          http://127.0.0.1:8000
"""

import hashlib
import html
import json
import math
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlmodel import Session, delete, func, select

# Importing db also loads your .env file (see the top of db.py).
from db import (
    Agent,
    AgentFolderLink,
    CategoryNotification,
    Command,
    Event,
    Folder,
    InboxChunk,
    InboxItem,
    Output,
    OutputFile,
    TechSetting,
    create_db_and_tables,
    get_session,
    utc_now,
)
from security import (
    ACTIVE_COOKIE,
    GUEST_NAME,
    SESSION_COOKIE,
    SESSION_LIFETIME,
    KeyEncryptionNotConfigured,
    cookie_is_secure,
    csrf_token,
    current_login,
    device_logins,
    end_device_logins,
    decrypt_api_key,
    edit_password_matches,
    encrypt_api_key,
    end_login,
    find_login,
    generate_api_key,
    hash_api_key,
    login_details_match,
    require_agent,
    require_csrf,
    require_owner,
    require_user,
    start_login,
)

# Build paths from this file's location so the app works no matter which
# folder you start it from.
BASE_DIR = Path(__file__).resolve().parent

CELLS_PER_PAGE = 9  # a 3 x 3 grid (agent cards plus the "Add Agent" card)
# "Online" follows each agent's own rhythm: an agent says how often it checks
# in (check_in_every, from MIN_CHECK_IN to MAX_CHECK_IN seconds), and counts as
# online until that time has passed, plus some slack: half the interval, and at
# least CHECK_IN_SLACK, so one slow check-in doesn't flip it to offline.
# Agents that never say assume DEFAULT_CHECK_IN.
DEFAULT_CHECK_IN = 60
MIN_CHECK_IN = 1
MAX_CHECK_IN = 7 * 24 * 60 * 60  # a week
CHECK_IN_SLACK = 30
MAX_AGENT_NAME = 50
MAX_DESCRIPTION = 1000  # characters
MAX_FOLDER_NAME = 40
MIN_API_KEY_LENGTH = 20

# Outputs (sent by agents with output(content, category))
MAX_CATEGORY = 50
MAX_OUTPUT_TEXT = 20_000  # characters, for text and lists/dicts
MAX_OUTPUT_FILE_BYTES = 5 * 1024 * 1024  # 5 MB; files are stored in the database
MAX_URL = 2000

# The Inbox (files you upload for one agent, waiting until it takes them)
MAX_INBOX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per file
# All waiting inbox files together, on every agent. The free dashboard
# database is small, and waiting files are stored in it until picked up.
MAX_INBOX_TOTAL_BYTES = 200 * 1024 * 1024
INBOX_CHUNK_BYTES = 1024 * 1024  # files are stored and sent in 1 MB pieces
MAX_INBOX_NOTE = 1000
OUTPUTS_SHOWN = 50
# Only these file types are shown inside the page. Anything else (including
# SVG and HTML, which could run scripts) is only offered as a download.
INLINE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
LINK_PATTERN = re.compile(r"^https?://\S+$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Code that runs once when the server starts."""
    create_db_and_tables()
    yield


app = FastAPI(title="Homepage", lifespan=lifespan)


@app.middleware("http")
async def never_store_private_pages(request: Request, call_next):
    """Tell browsers (and anything in between) never to keep a copy of a
    dashboard page or an API reply. Otherwise a restored tab or the Back
    button could show a private page without asking the server, and so
    without the login. Replies that set their own caching keep it (agents'
    files never change, so those may stay in your own browser's cache).
    The opposite for the site's own files with fingerprinted or versioned
    addresses: browsers may keep those for good (see below)."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith(("/dashboard", "/api", "/login", "/logout")):
        response.headers.setdefault("Cache-Control", "no-store")
    elif path.startswith("/static/") and response.status_code in (200, 304) and (
        "v" in request.query_params or path.startswith(("/static/fonts/", "/static/vendor/"))
    ):
        # Fingerprinted addresses (?v=...) and versioned files never change:
        # a new version gets a new address. So browsers may keep them for a
        # year without asking again, which saves a round trip per file per page.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
# Lets dashboard templates write {{ csrf_token() }} (see security.py).
templates.env.globals["csrf_token"] = csrf_token
# Lets templates write {{ static_url("theme.css") }}: the file's address plus a
# fingerprint of its contents, so browsers fetch it again whenever it changes
# (instead of using an old copy they kept) but never otherwise.
_fingerprints: dict[tuple[str, int], str] = {}


def static_url(name: str) -> str:
    """A static file's address with a fingerprint of its contents, worked out
    once per version of the file (not on every page)."""
    path = BASE_DIR / "static" / name
    key = (name, path.stat().st_mtime_ns)
    if key not in _fingerprints:
        _fingerprints[key] = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    return f"/static/{name}?v={_fingerprints[key]}"


templates.env.globals["static_url"] = static_url
# Lets templates write {{ agent | check_in_text }}, e.g. "every 5 min".
templates.env.filters["check_in_text"] = lambda agent: "every " + human_interval(check_in_interval(agent))


# ---------------------------------------------------------------------------
# Helpers: looking things up
# ---------------------------------------------------------------------------


def check_in_interval(agent: Agent) -> int:
    """How often (seconds) the agent says it checks in, or the default."""
    return agent.check_in_seconds or DEFAULT_CHECK_IN


def is_online(agent: Agent) -> bool:
    """True if the agent has checked in as often as it said it would.

    E.g. an agent that checks in every 5 seconds is online if it was seen in
    the last 35 seconds; an hourly one, if it was seen in the last 90 minutes.
    """
    if agent.last_seen is None:  # never connected
        return False
    last_seen = agent.last_seen
    # SQLite forgets the time zone when it saves a date; we always store UTC.
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    interval = check_in_interval(agent)
    allowed = timedelta(seconds=interval + max(CHECK_IN_SLACK, interval / 2))
    return utc_now() - last_seen <= allowed


def human_interval(seconds: int | None) -> str:
    """A check-in interval in words: "3 s", "5 min", "1 h 30 min", "1 day"."""
    seconds = int(seconds or DEFAULT_CHECK_IN)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{days} day{'s' if days != 1 else ''}" if days else "",
             f"{hours} h" if hours else "", f"{minutes} min" if minutes else "", f"{secs} s" if secs else ""]
    return " ".join(part for part in parts if part)


def latest_event(session: Session, agent_id: int) -> Event | None:
    """The newest event an agent has sent, or None if it hasn't sent any."""
    statement = (
        select(Event)
        .where(Event.agent_id == agent_id)
        .order_by(Event.created_at.desc(), Event.id.desc())
    )
    return session.exec(statement).first()


def get_agent_or_404(session: Session, agent_id: int) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def get_folder_or_404(session: Session, folder_id: int) -> Folder:
    folder = session.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


def folders_of(session: Session, agent_id: int) -> list[Folder]:
    """The folders an agent is tagged with, sorted by name."""
    statement = (
        select(Folder)
        .join(AgentFolderLink, AgentFolderLink.folder_id == Folder.id)
        .where(AgentFolderLink.agent_id == agent_id)
        .order_by(Folder.name)
    )
    return list(session.exec(statement).all())


def all_folders(session: Session) -> list[Folder]:
    return list(session.exec(select(Folder).order_by(Folder.name)).all())


def agents_query(folder_id: int | None):
    """A query for all agents, or only the agents in one folder."""
    statement = select(Agent)
    if folder_id is not None:
        statement = statement.join(
            AgentFolderLink, AgentFolderLink.agent_id == Agent.id
        ).where(AgentFolderLink.folder_id == folder_id)
    return statement


def count_agents(session: Session, folder_id: int | None) -> int:
    subquery = agents_query(folder_id).subquery()
    return session.exec(select(func.count()).select_from(subquery)).one()


def page_of(session: Session, agent: Agent, folder_id: int | None = None) -> int:
    """Which grid page an agent appears on (agents are sorted A-Z, ignoring case)."""
    before = agents_query(folder_id).where(func.lower(Agent.name) < agent.name.lower()).subquery()
    agents_before = session.exec(select(func.count()).select_from(before)).one()
    return agents_before // CELLS_PER_PAGE + 1


def clean_name(raw: str, max_length: int) -> tuple[str, str | None]:
    """Trim a name and check its length. Returns (name, error message or None)."""
    name = " ".join(raw.split())  # trim and collapse repeated spaces
    if not name:
        return name, "Name can't be empty."
    if len(name) > max_length:
        return name, f"Name can be at most {max_length} characters."
    return name, None


def name_taken(session: Session, model, name: str, except_id: int | None = None) -> bool:
    """True if another Agent/Folder (not the one with except_id) already uses this name."""
    existing = session.exec(select(model).where(model.name == name)).first()
    return existing is not None and existing.id != except_id


# ---------------------------------------------------------------------------
# Helpers: building page data
# ---------------------------------------------------------------------------


def sidebar_context(session: Session, current_folder: Folder | None) -> dict:
    """Data for the folder sidebar: every folder with how many agents it holds."""
    folders = [
        {"folder": folder, "count": count_agents(session, folder.id)}
        for folder in all_folders(session)
    ]
    return {
        "folders": folders,
        "all_count": count_agents(session, None),
        "current_folder": current_folder,
    }


def grid_context(session: Session, page: int, folder: Folder | None) -> dict:
    """Everything the grid template needs for one page.

    The grid holds the agent cards followed by one "Add Agent" card, so with
    N agents there are N + 1 cells, 9 per page.
    """
    folder_id = folder.id if folder else None
    total_agents = count_agents(session, folder_id)
    total_pages = math.ceil((total_agents + 1) / CELLS_PER_PAGE)
    page = min(max(page, 1), total_pages)  # keep the page number in range
    first_index = (page - 1) * CELLS_PER_PAGE

    statement = (
        agents_query(folder_id)
        .order_by(func.lower(Agent.name), Agent.name)  # A-Z, ignoring upper/lower case
        .offset(first_index)
        .limit(CELLS_PER_PAGE)
    )
    cells = [
        {
            "agent": agent,
            "online": is_online(agent),
            "latest": latest_event(session, agent.id),
            "folders": folders_of(session, agent.id),
            # The newest output in the agent's pinned category (if one is pinned).
            "pinned": latest_output(session, agent.id, agent.pinned_category)
            if agent.pinned_category
            else None,
        }
        for agent in session.exec(statement).all()
    ]
    # The "Add Agent" card sits right after the last agent.
    show_add_card = first_index <= total_agents < first_index + CELLS_PER_PAGE
    return {
        "cells": cells,
        "show_add_card": show_add_card,
        "page": page,
        "total_pages": total_pages,
        "total_agents": total_agents,
        "folder": folder,
    }


# ---------------------------------------------------------------------------
# Helpers: outputs and monitors
# ---------------------------------------------------------------------------


def clean_category(raw: str) -> str:
    """Trim an output category and check it, or raise a 422 error."""
    category = " ".join(str(raw).split())
    if not category or len(category) > MAX_CATEGORY:
        raise HTTPException(422, f"category must be 1 to {MAX_CATEGORY} characters")
    return category


def clean_link(raw: str | None) -> str | None:
    """A web address, if it's a safe http(s) one. None for empty or anything else.

    Only http:// and https:// are allowed, so a link can never be a
    "javascript:" trick that runs code when clicked.
    """
    url = (raw or "").strip()
    if url and len(url) <= MAX_URL and LINK_PATTERN.match(url):
        return url
    return None


def describe_content(content: Any) -> tuple[str, str]:
    """Decide how to store and show an output: returns (kind, value as text).

    numbers -> "number", web addresses -> "link", lists/dicts -> "json",
    everything else -> "text". (Files arrive through their own endpoint.)
    """
    if isinstance(content, bool):  # True/False are technically numbers in Python
        kind, value = "text", "true" if content else "false"
    elif isinstance(content, (int, float)):
        kind, value = "number", repr(content)
    elif isinstance(content, (list, dict)):
        kind, value = "json", json.dumps(content, indent=2, ensure_ascii=False)
    elif isinstance(content, str) and clean_link(content):
        kind, value = "link", content.strip()
    else:
        kind, value = "text", str(content)
    if len(value) > MAX_OUTPUT_TEXT:
        raise HTTPException(422, f"content is too long (max {MAX_OUTPUT_TEXT} characters)")
    return kind, value


def latest_output(session: Session, agent_id: int, category: str) -> Output | None:
    statement = (
        select(Output)
        .where(Output.agent_id == agent_id, Output.category == category)
        .order_by(Output.created_at.desc(), Output.id.desc())
    )
    return session.exec(statement).first()


# The Outputs filter's "Sort by" choices.
OUTPUT_SORTS = {"date": "Date", "category": "Category name", "content": "Content"}


def outputs_context(
    session: Session,
    agent: Agent,
    selected: list[str] | None = None,
    show_all: bool = False,
    sort: str = "date",
    order: str = "desc",
) -> dict:
    """Data for an agent's Outputs section and its Filter panel.

    selected: the categories ticked in the Filter. None means "first visit":
              nothing is ticked, except a pinned category, which starts ticked.
              Nothing ticked (and not All) means nothing is shown.
    show_all: the Filter's "All" box: every category.
    sort:     "date", "category" (category name) or "content"; order: "asc" or "desc".
    """
    names = sorted(
        session.exec(select(Output.category).where(Output.agent_id == agent.id).distinct()).all(),
        key=str.lower,
    )
    notifying = set(
        session.exec(
            select(CategoryNotification.category).where(CategoryNotification.agent_id == agent.id)
        ).all()
    )
    categories = [
        {"name": name, "notify": name in notifying, "pinned": name == agent.pinned_category}
        for name in names
    ]
    if selected is None:  # first visit: only a pinned category starts ticked
        selected = [agent.pinned_category] if agent.pinned_category else []
    selected = [name for name in dict.fromkeys(selected) if name in names]  # drop unknown/duplicates
    sort = sort if sort in OUTPUT_SORTS else "date"
    order = "asc" if order == "asc" else "desc"

    outputs = []
    if show_all or selected:
        statement = select(Output).where(Output.agent_id == agent.id)
        if not show_all:
            statement = statement.where(Output.category.in_(selected))
        sort_columns = {
            "date": [Output.created_at, Output.id],
            "category": [func.lower(Output.category), Output.category],
            "content": [func.lower(Output.value), Output.value],
        }[sort]
        ordering = [column.asc() if order == "asc" else column.desc() for column in sort_columns]
        if sort != "date":  # ties (same category/content): newest first
            ordering += [Output.created_at.desc(), Output.id.desc()]
        outputs = session.exec(statement.order_by(*ordering).limit(OUTPUTS_SHOWN)).all()

    files = {}
    file_ids = [o.file_id for o in outputs if o.file_id]
    if file_ids:
        # Only fetch each file's type and size, not its bytes.
        rows = session.exec(
            select(OutputFile.id, OutputFile.content_type, OutputFile.size).where(OutputFile.id.in_(file_ids))
        ).all()
        files = {row[0]: {"content_type": row[1], "size": row[2]} for row in rows}

    if show_all:
        summary = "All"
    elif selected:
        summary = selected[0] if len(selected) == 1 else f"{len(selected)} categories"
    else:
        summary = "Choose..."
    total = session.exec(select(func.count()).select_from(Output).where(Output.agent_id == agent.id)).one()
    return {
        "agent": agent,
        "categories": categories,
        "selected": selected,
        "show_all": show_all,
        "sort": sort,
        "order": order,
        "sorts": OUTPUT_SORTS,
        "summary": summary,
        "outputs": outputs,
        "files": files,
        "inline_types": INLINE_IMAGE_TYPES,
        "total": total,
    }


def poll_reply(content: str, seen: str | None, seen_id: str) -> Response:
    """The reply to a section that refreshes itself every few seconds.

    If the section's content is exactly what the page already shows, answer
    "204 No Content": HTMX then leaves the page alone, so nothing is rebuilt
    (which kept the browser busy). Otherwise send the new content, plus a
    hidden field holding its fingerprint, which the page sends back as `seen`
    next time.
    """
    fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    if seen == fingerprint:
        return Response(status_code=204)
    return HTMLResponse(content + f'<input type="hidden" id="{seen_id}" name="seen" value="{fingerprint}">')


def render_partial(name: str, context: dict, oob: bool = False) -> str:
    """Render one template piece to HTML text (oob=True to send it "out of band")."""
    return templates.get_template(name).render(**context, oob=oob)


# Something the agent made more than this long before it arrived was sent
# late, typically from the connector's offline buffer after an outage.
LATE_AFTER = timedelta(minutes=1)
LATE_NOTE = " (delivered late)"  # e.g. held while paused, or waiting out an outage


def as_utc(moment: datetime) -> datetime:
    """The same moment in UTC. Times without a time zone are taken to be UTC already."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def when_made(made_at: datetime | str | None) -> tuple[datetime, bool]:
    """When the agent says something happened, and whether it arrived late.

    Agents send `created_at` for things that waited in the offline buffer, so
    they land at their real time in Outputs and Activity. A missing time means
    "now", and a time in the future (a computer clock that's off) becomes "now".
    """
    now = utc_now()
    if made_at is None or made_at == "":
        return now, False
    if isinstance(made_at, str):
        try:
            made_at = datetime.fromisoformat(made_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "created_at must be an ISO date and time, e.g. 2026-10-03T08:00:00Z")
    made_at = as_utc(made_at)
    if made_at > now:
        return now, False
    return made_at, now - made_at > LATE_AFTER


def log_activity(
    session: Session,
    agent_id: int,
    kind: str,
    message: str,
    data: dict | None = None,
    created_at: datetime | None = None,
) -> None:
    """Add a timestamped line to the agent's Activity log. The caller commits."""
    session.add(
        Event(agent_id=agent_id, type=kind, message=message, data=data, created_at=created_at or utc_now())
    )


def preview(text: str, limit: int = 80) -> str:
    """The first line of some text, shortened for the Activity log."""
    lines = text.strip().splitlines()
    first = lines[0] if lines else ""
    return first if len(first) <= limit else first[: limit - 1] + "\u2026"


def log_new_output(session: Session, output: Output, late: bool = False) -> None:
    """Note a new output in the Activity log, e.g. 'New output in "news": ...'.

    The line gets the output's own time, so a buffered output lands where it happened.
    """
    if output.kind == "file":
        what = f"file {output.value}"
    elif output.kind == "json":
        what = "a list/dict"
    else:
        what = preview(output.value)
    log_activity(
        session,
        output.agent_id,
        "output",
        f'New output in "{output.category}": {what}' + (LATE_NOTE if late else ""),
        {"category": output.category, "output_id": output.id},
        created_at=output.created_at,
    )


def monitor_version(agent: Agent) -> str:
    """Changes whenever the monitor changes; the page uses it to spot updates."""
    updated = agent.monitor_updated_at
    return updated.strftime("%Y%m%d%H%M%S%f") if updated else "none"


def replace_monitor(
    session: Session,
    agent: Agent,
    *,
    url: str | None = None,
    file: OutputFile | None = None,
    filename: str | None = None,
    label: str | None = None,
    by: str = "agent",
    made_at: datetime | str | None = None,
) -> bool:
    """Make a link, a PDF, or nothing the agent's monitor, and log it. Commits.

    Only the latest monitor is kept: a previous PDF is deleted from the database.
    made_at: when the agent set it (for updates from the offline buffer). An
    update older than the current monitor is skipped, so a late arrival never
    replaces something newer. Returns False if skipped.
    """
    when, late = when_made(made_at)
    if agent.monitor_updated_at and when < as_utc(agent.monitor_updated_at):
        if file is not None:
            session.delete(file)  # the skipped PDF isn't needed
        log_activity(session, agent.id, "monitor", "Older monitor update skipped" + LATE_NOTE, created_at=when)
        session.commit()
        session.refresh(agent)
        return False
    old_file_id = agent.monitor_file_id
    agent.monitor_url = url
    agent.monitor_file_id = file.id if file else None
    agent.monitor_filename = filename if file else None
    agent.monitor_label = " ".join((label or "").split())[:MAX_AGENT_NAME] or None
    agent.monitor_updated_at = when
    session.add(agent)
    if old_file_id and old_file_id != agent.monitor_file_id:
        old_file = session.get(OutputFile, old_file_id)
        if old_file is not None:
            session.delete(old_file)

    source = " (from the dashboard)" if by == "user" else ""
    if file is not None:
        message = f"Monitor updated: PDF {filename}"
    elif url is not None:
        message = f"Monitor link set: {url}"
    else:
        message = "Monitor removed"
    log_activity(session, agent.id, "monitor", message + source + (LATE_NOTE if late else ""), created_at=when)
    session.commit()
    session.refresh(agent)
    return True


def render_monitor(agent: Agent, oob: bool = False) -> str:
    """The Monitor section's HTML (oob=True to send it alongside another reply)."""
    return templates.get_template("partials/monitor.html").render(
        agent=agent, oob=oob, version=monitor_version(agent)
    )


def render_monitor_pin(agent: Agent, oob: bool = False) -> str:
    """Just the Monitor's pin button, so pinning doesn't reload a PDF being read."""
    return templates.get_template("partials/monitor_pin.html").render(agent=agent, oob=oob)


def clean_description(raw: str | None) -> tuple[str | None, str | None]:
    """Tidy a description: returns (description or None if empty, error or None).

    Line breaks are kept (a description can have a few short paragraphs), but
    spaces at the ends and runs of blank lines are trimmed.
    """
    lines = [line.rstrip() for line in (raw or "").replace("\r\n", "\n").strip().split("\n")]
    description = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    if len(description) > MAX_DESCRIPTION:
        return description, f"The description can be at most {MAX_DESCRIPTION} characters."
    return description or None, None


def check_new_api_key(session: Session, api_key: str) -> str | None:
    """Return an error message if this key can't be used, or None if it's fine."""
    if len(api_key) < MIN_API_KEY_LENGTH or any(c.isspace() for c in api_key):
        return f"The API key must be at least {MIN_API_KEY_LENGTH} characters with no spaces."
    if session.exec(select(Agent).where(Agent.api_key_hash == hash_api_key(api_key))).first():
        return "That API key is already used by another agent."
    return None


def store_api_key(agent: Agent, api_key: str) -> None:
    """Save a key on an agent: its fingerprint (for logins) and an encrypted copy (for "View key").

    Raises KeyEncryptionNotConfigured if KEY_ENCRYPTION_SECRET isn't set.
    """
    agent.api_key_encrypted = encrypt_api_key(api_key)
    agent.api_key_hash = hash_api_key(api_key)


# The two downloads offered by "Implement connector" in the sidebar.
# They are written to work with a dashboard anywhere (local, Render, any other
# host): the address and key are placeholders the user fills in (code) or that
# the AI assistant asks the user for (prompt). The only thing filled in here is
# {{DOWNLOADED_FROM}}, a hint showing which address the file came from.
CONNECTOR_FILES = {
    "code": {
        "source": BASE_DIR / "connector" / "dashboard_connector.py",
        "filename": "dashboard_connector.py",
        "media_type": "text/x-python",
    },
    "prompt": {
        "source": BASE_DIR / "connector" / "connector_prompt.md",
        "filename": "dashboard_connector_prompt.md",
        "media_type": "text/markdown",
    },
}


def site_url(request: Request) -> str:
    """This website's address as the browser sees it.

    For example http://127.0.0.1:8000, https://you.onrender.com, or your own
    domain. Hosts like Render handle HTTPS in front of the app and say so in
    the X-Forwarded-Proto header (sometimes as a list, e.g. "https,http"), so
    we prefer its first value over the request's own scheme.
    """
    forwarded = request.headers.get("x-forwarded-proto", "")
    scheme = forwarded.split(",")[0].strip() or request.url.scheme
    return f"{scheme}://{request.url.netloc}"


def connector_text(request: Request, file_format: str) -> str:
    """The connector code or prompt, with the "downloaded from" hint filled in."""
    source = CONNECTOR_FILES[file_format]["source"]
    return source.read_text(encoding="utf-8").replace("{{DOWNLOADED_FROM}}", site_url(request))


def page_url(folder: Folder | None, page: int = 1) -> str:
    """The dashboard address for a folder (or All Agents) and page."""
    if folder is None:
        return f"/dashboard?page={page}"
    return f"/dashboard?folder={folder.id}&page={page}"


def redirect_with_error(url: str, error: str) -> RedirectResponse:
    """Go back to a dashboard page and show an error message there.

    Plain HTML forms (not HTMX) can't show errors in place, so the message
    travels in the address instead, e.g. /dashboard?error=Name+taken.
    """
    separator = "&" if "?" in url else "?"
    return RedirectResponse(f"{url}{separator}error={quote(error)}", status_code=303)


def error_html(text: str) -> HTMLResponse:
    """A short red message, shown inside a pop-up window."""
    return HTMLResponse(f'<p class="text-error text-sm">{html.escape(text)}</p>')


def alert_html(kind: str, text: str) -> str:
    """A small daisyUI alert that removes itself after 3 seconds (using Alpine.js).

    `kind` is a daisyUI alert style such as "success" or "warning".
    The text is escaped so any HTML typed by the user is shown as plain text.
    """
    return (
        f'<div role="alert" class="alert alert-{kind}" '
        'x-data x-init="setTimeout(() => $el.remove(), 3000)">'
        f"<span>{html.escape(text)}</span>"
        "</div>"
    )


def agent_header_context(
    session: Session,
    agent: Agent,
    error: str | None = None,
    settings_open: bool = False,
    monitor_error: str | None = None,
    description_error: str | None = None,
) -> dict:
    """Data for the top of an agent's page: its name, tags, and the settings pop-up.

    settings_open=True keeps the settings pop-up open after a change (rename, tags).
    """
    tagged = folders_of(session, agent.id)
    tagged_ids = {folder.id for folder in tagged}
    untagged = [folder for folder in all_folders(session) if folder.id not in tagged_ids]
    return {
        "agent": agent,
        "online": is_online(agent),
        "tagged": tagged,
        "untagged": untagged,
        "error": error,  # shown under the name in settings
        "monitor_error": monitor_error,  # shown under the monitor link in settings
        "description_error": description_error,  # shown under the description in settings
        "settings_open": settings_open,
    }


def render_agent_header(
    request: Request,
    session: Session,
    agent: Agent,
    error: str | None = None,
    monitor_error: str | None = None,
    description_error: str | None = None,
):
    """Just the header part, sent back after changing something in settings.

    The settings pop-up stays open, because that's where those changes are made.
    """
    context = agent_header_context(
        session, agent, error, settings_open=True,
        monitor_error=monitor_error, description_error=description_error,
    )
    return templates.TemplateResponse(request, "partials/agent_header.html", context)


# ---------------------------------------------------------------------------
# Helpers: the Inbox (files you upload for one agent; it takes them, then
# they're deleted). Files are stored in 1 MB pieces (InboxChunk), so even a
# 50 MB file never has to fit in the server's memory at once.
# ---------------------------------------------------------------------------


class InboxRefused(Exception):
    """An upload that can't be accepted (too big, or the inbox is full)."""


def human_size(size: int) -> str:
    """Bytes in words: "820 B", "14.2 KB", "3.5 MB"."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB".replace(".0 ", " ")
    return f"{size / (1024 * 1024):.1f} MB".replace(".0 ", " ")


def inbox_items(session: Session, agent_id: int) -> list[InboxItem]:
    """An agent's waiting inbox files, oldest first."""
    statement = (
        select(InboxItem).where(InboxItem.agent_id == agent_id).order_by(InboxItem.uploaded_at, InboxItem.id)
    )
    return list(session.exec(statement).all())


def inbox_context(session: Session, agent: Agent, error: str | None = None, notice: str | None = None) -> dict:
    """Data for the Inbox window on an agent's page."""
    items = inbox_items(session, agent.id)
    return {"agent": agent, "inbox": items, "inbox_error": error, "inbox_notice": notice,
            "inbox_max": human_size(MAX_INBOX_FILE_BYTES)}


async def store_inbox_file(session: Session, agent: Agent, upload: UploadFile, note: str | None) -> InboxItem:
    """Save one uploaded file in the agent's Inbox, piece by piece. The caller commits.

    Raises InboxRefused (with nothing saved) if the file is over the limit, or
    if it would take all waiting inbox files over MAX_INBOX_TOTAL_BYTES.
    """
    already_waiting = session.exec(select(func.coalesce(func.sum(InboxItem.size), 0))).one()
    filename = Path(upload.filename or "upload").name[:200] or "upload"
    item = InboxItem(
        agent_id=agent.id,
        filename=filename,
        content_type=(upload.content_type or "application/octet-stream")[:100],
        size=0,
        note=note,
    )
    session.add(item)
    session.flush()  # gives the item its id, for its pieces
    size, position = 0, 0
    while piece := await upload.read(INBOX_CHUNK_BYTES):
        size += len(piece)
        if size > MAX_INBOX_FILE_BYTES:
            session.rollback()
            raise InboxRefused(f"{filename} is over {human_size(MAX_INBOX_FILE_BYTES)}.")
        if already_waiting + size > MAX_INBOX_TOTAL_BYTES:
            session.rollback()
            raise InboxRefused(
                f"The inbox is full: waiting files can take up to {human_size(MAX_INBOX_TOTAL_BYTES)} in all. "
                "Wait for agents to take theirs, or remove some."
            )
        chunk = InboxChunk(item_id=item.id, position=position, data=piece)
        session.add(chunk)
        session.flush()
        session.expunge(chunk)  # let each piece's bytes go once they're in the database
        position += 1
    item.size = size
    session.add(item)
    return item


def inbox_file_pieces(session: Session, item: InboxItem):
    """The file's bytes, one stored piece at a time (for streaming it out)."""
    piece_ids = session.exec(
        select(InboxChunk.id).where(InboxChunk.item_id == item.id).order_by(InboxChunk.position)
    ).all()
    for piece_id in piece_ids:
        piece = session.get(InboxChunk, piece_id)
        data = piece.data
        session.expunge(piece)  # don't keep every piece in memory
        yield data


def inbox_file_response(session: Session, item: InboxItem) -> StreamingResponse:
    """Send an inbox file as a download, streamed piece by piece."""
    return StreamingResponse(
        inbox_file_pieces(session, item),
        media_type=item.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(item.filename)}",
            "Content-Length": str(item.size),
            "X-Content-Type-Options": "nosniff",
        },
    )


def delete_inbox_item(session: Session, item: InboxItem) -> None:
    """Delete a waiting inbox file and its pieces. The caller commits."""
    session.exec(delete(InboxChunk).where(InboxChunk.item_id == item.id))
    session.delete(item)


def render_inbox_list(session: Session, agent: Agent, error: str | None = None, notice: str | None = None) -> str:
    return render_partial("partials/inbox_list.html", inbox_context(session, agent, error, notice))


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------


# After signing in (or "as guest?"), the tree is opened with ?entered, which
# plays the Login button's move into the tree (see static/home.js).
HOME_AFTER_SIGN_IN = "/tree?entered"

# The "techs": the cards in the tree, after the "tech tree" it's styled on.
# href is None for pages that aren't built yet. page_key: the page has one
# API key for the whole page (set in developer mode), unlike the dashboard,
# where each agent has its own.
TECHS = [
    {"slug": "dashboard", "title": "Dashboard", "href": "/dashboard", "icon": "grid",
     "text": "Your agents, their outputs and controls.", "page_key": False},
    {"slug": "portfolio", "title": "Portfolio", "href": None, "icon": "briefcase",
     "text": "Projects and write-ups. Coming soon.", "page_key": False},
    {"slug": "data-tracking", "title": "Data tracking", "href": None, "icon": "chart",
     "text": "Charts of what your agents collect. Coming soon.", "page_key": True},
]
TECHS_BY_SLUG = {tech["slug"]: tech for tech in TECHS}
VISIBILITIES = ["open", "private", "hidden"]  # the three stops of the developer-mode slider
MAX_TECH_DESCRIPTION = 120  # characters: keeps the techs tidy


def tech_view(session: Session, tech: dict, user: str) -> dict | None:
    """How one tech looks to this viewer, or None if they don't get to see it.

    You see every tech, with its setting in the corner (or "soon" if its page
    isn't built yet). Guests don't see hidden techs, and see private ones
    greyed out, unable to open them.
    """
    setting = session.get(TechSetting, tech["slug"])
    visibility = setting.visibility if setting else "open"
    text = (setting.description if setting else None) or tech["text"]
    guest = user == GUEST_NAME
    if guest and visibility == "hidden":
        return None
    can_open = tech["href"] is not None and not (guest and visibility == "private")
    if tech["href"] is None:
        status = "soon"
    elif guest:
        status = "private" if visibility == "private" else "open"
    else:
        status = visibility
    return {**tech, "text": text, "visibility": visibility, "can_open": can_open, "status": status}


def ordered_techs(session: Session) -> list[dict]:
    """The techs in the order you've dragged them into (developer mode);
    ones never moved keep their place from TECHS."""
    positions = {setting.slug: setting.position for setting in session.exec(select(TechSetting))}

    def place(item):
        index, tech = item
        position = positions.get(tech["slug"])
        return (position if position is not None else index, index)

    return [tech for _, tech in sorted(enumerate(TECHS), key=place)]


def signed_in_user(request: Request, session: Session) -> str | None:
    """Who's using this device right now (see current_login in security.py), or None."""
    login = current_login(session, request)
    return login.username if login else None


@app.api_route("/health", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def health():
    """For uptime monitors (e.g. UptimeRobot): answers "ok" to GET and HEAD,
    without touching the database, so frequent checks stay cheap and keep the
    free Render site awake."""
    return PlainTextResponse("ok", headers={"Cache-Control": "no-store"})


# HEAD too, for monitors and link checkers that only ask for the headers.
@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def home(request: Request):
    """The front page: the name, the Login button and "as guest?". (Signed in
    or not: clicking Login when you're already signed in goes straight into
    the tree.)"""
    return templates.TemplateResponse(request, "home.html", {"mode": "front"})


@app.get("/tree", response_class=HTMLResponse)
def tree(request: Request, entered: str | None = None, session: Session = Depends(get_session)):
    """The tree of techs, with Ren (or Guest) as its root. ?entered plays the
    Login button's move into it, right after signing in."""
    user = signed_in_user(request, session)
    if user is None:
        return RedirectResponse("/", status_code=303)
    views = [view for tech in ordered_techs(session) if (view := tech_view(session, tech, user))]
    response = templates.TemplateResponse(request, "home.html", {
        "mode": "tree",
        "owner": user != GUEST_NAME,
        "root_label": "Guest" if user == GUEST_NAME else "Ren",
        "techs": views,
        "entered": entered is not None,
    })
    # This page is personal (and carries the forms' security token).
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Developer mode: each tech's settings (you only, never guests)
# ---------------------------------------------------------------------------


def get_tech_or_404(slug: str) -> dict:
    tech = TECHS_BY_SLUG.get(slug)
    if tech is None:
        raise HTTPException(status_code=404, detail="No such tech")
    return tech


def tech_settings_html(
    session: Session,
    tech: dict,
    shown_key: str | None = None,
    error: str | None = None,
    notice: str | None = None,
    with_leaf: bool = False,
) -> HTMLResponse:
    """The settings window's contents for one tech. with_leaf: also send its
    card in the tree (out of band), so a new setting shows there straight away."""
    setting = session.get(TechSetting, tech["slug"])
    visibility = setting.visibility if setting else "open"
    html_text = render_partial("partials/tech_settings.html", {
        "tech": tech,
        "level": VISIBILITIES.index(visibility),
        "visibility": visibility,
        "has_key": bool(setting and setting.api_key_encrypted),
        "shown_key": shown_key,
        "error": error,
        "notice": notice,
        "min_key": MIN_API_KEY_LENGTH,
        "description": (setting.description if setting else None) or tech["text"],
        "max_description": MAX_TECH_DESCRIPTION,
    })
    if with_leaf:
        view = tech_view(session, tech, user="owner")
        html_text += templates.get_template("partials/tech_leaf.html").render(tech=view, oob=True)
    return HTMLResponse(html_text)


def tech_setting(session: Session, slug: str) -> TechSetting:
    return session.get(TechSetting, slug) or TechSetting(slug=slug)


@app.post("/tree/techs/order", dependencies=[Depends(require_csrf)])
def set_tech_order(
    order: list[str] = Form(...),
    session: Session = Depends(get_session),
    owner: str = Depends(require_owner),
):
    """Save the leaf techs' order after one is dragged in developer mode.

    `order` lists every tech's slug, top first (hidden ones included).
    """
    if sorted(order) != sorted(TECHS_BY_SLUG):
        raise HTTPException(422, "order must list every tech exactly once")
    for position, slug in enumerate(order):
        setting = tech_setting(session, slug)
        setting.position = position
        session.add(setting)
    session.commit()
    return Response(status_code=204)


@app.get("/tree/techs/{slug}/settings", response_class=HTMLResponse)
def tech_settings(slug: str, session: Session = Depends(get_session), owner: str = Depends(require_owner)):
    return tech_settings_html(session, get_tech_or_404(slug))


@app.post("/tree/techs/{slug}/visibility", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
def set_tech_visibility(
    slug: str,
    level: int = Form(...),
    session: Session = Depends(get_session),
    owner: str = Depends(require_owner),
):
    """The slider: 0 = Open, 1 = Private, 2 = Hidden."""
    tech = get_tech_or_404(slug)
    if level not in range(len(VISIBILITIES)):
        raise HTTPException(422, "level must be 0 (open), 1 (private) or 2 (hidden)")
    setting = tech_setting(session, slug)
    setting.visibility = VISIBILITIES[level]
    session.add(setting)
    session.commit()
    return tech_settings_html(session, tech, with_leaf=True)


@app.post("/tree/techs/{slug}/description", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
def set_tech_description(
    slug: str,
    description: str = Form(""),
    session: Session = Depends(get_session),
    owner: str = Depends(require_owner),
):
    """Your own description for a tech (blank: back to the one it came with)."""
    tech = get_tech_or_404(slug)
    text = " ".join(description.split())  # one tidy line; the card wraps it
    if len(text) > MAX_TECH_DESCRIPTION:
        return tech_settings_html(
            session, tech, error=f"The description can be at most {MAX_TECH_DESCRIPTION} characters."
        )
    setting = tech_setting(session, slug)
    setting.description = text or None
    session.add(setting)
    session.commit()
    notice = "Description saved." if text else "Back to the original description."
    return tech_settings_html(session, tech, notice=notice, with_leaf=True)


def page_key_tech(slug: str) -> dict:
    tech = get_tech_or_404(slug)
    if not tech["page_key"]:
        raise HTTPException(status_code=404, detail="This page has no page-wide API key")
    return tech


@app.post("/tree/techs/{slug}/key/show", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
def show_tech_key(slug: str, session: Session = Depends(get_session), owner: str = Depends(require_owner)):
    """Show the page's API key (until the window is closed)."""
    tech = page_key_tech(slug)
    setting = session.get(TechSetting, slug)
    try:
        key = decrypt_api_key(setting.api_key_encrypted) if setting and setting.api_key_encrypted else None
    except KeyEncryptionNotConfigured:
        return tech_settings_html(session, tech, error="KEY_ENCRYPTION_SECRET isn't set on the server.")
    if key is None:
        return tech_settings_html(session, tech, error="This key can't be shown (the encryption secret changed). Set a new one.")
    response = tech_settings_html(session, tech, shown_key=key)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/tree/techs/{slug}/key", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
def set_tech_key(
    slug: str,
    new_key: str = Form(""),
    session: Session = Depends(get_session),
    owner: str = Depends(require_owner),
):
    """Set the page's API key: the one typed in, or a new random one if left blank."""
    tech = page_key_tech(slug)
    key = new_key.strip() or generate_api_key()
    if len(key) < MIN_API_KEY_LENGTH or any(c.isspace() for c in key):
        return tech_settings_html(
            session, tech, error=f"The key must be at least {MIN_API_KEY_LENGTH} characters with no spaces."
        )
    setting = tech_setting(session, slug)
    try:
        setting.api_key_encrypted = encrypt_api_key(key)
    except KeyEncryptionNotConfigured:
        return tech_settings_html(session, tech, error="KEY_ENCRYPTION_SECRET isn't set on the server.")
    session.add(setting)
    session.commit()
    response = tech_settings_html(session, tech, shown_key=key,
                                  notice="New random key saved." if not new_key.strip() else "Key saved.")
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Signing in and out (see "Dashboard login" in security.py)
# ---------------------------------------------------------------------------


def safe_next(next_page: str | None) -> str:
    """Where to go after signing in: a dashboard page, or the tree."""
    if next_page in (HOME_AFTER_SIGN_IN, "/tree"):
        return next_page
    if next_page and next_page.startswith("/dashboard") and "//" not in next_page and "\\" not in next_page:
        return next_page
    return "/dashboard"


@app.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str | None = None,
    signed_out: bool = False,
    session: Session = Depends(get_session),
):
    """The login form. Already signed in on this device? Straight on, as the
    highest-ranked account it's signed into (you, rather than Guest)."""
    if current_login(session, request):
        response = RedirectResponse(safe_next(next), status_code=303)
        response.delete_cookie(ACTIVE_COOKIE, path="/")  # no longer "as guest": the highest account
        return response
    return templates.TemplateResponse(
        request, "login.html", {"next": safe_next(next), "signed_out": signed_out, "error": None}
    )


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/dashboard"),
    session: Session = Depends(get_session),
):
    """Check the username and password, then sign this device in for a day."""
    if not login_details_match(username, password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": safe_next(next), "signed_out": False, "username": username,
             "error": "Wrong username or password."},
            status_code=401,
        )
    response = RedirectResponse(safe_next(next), status_code=303)
    sign_in_device(request, response, session, username, as_guest=False)
    return response


def sign_in_device(request: Request, response: Response, session: Session, username: str, as_guest: bool) -> None:
    """Add a sign-in for this account to the device, keeping its other accounts.

    Signing in with the password always starts a fresh sign-in (replacing any
    older one for the same account); "as guest?" reuses the device's guest
    sign-in if it still has one. as_guest: use Guest from now on (otherwise
    the device uses its highest-ranked account).
    """
    kept = []
    token = None
    for old_token, login in device_logins(session, request):
        if login.username != username:
            kept.append(old_token)
        elif as_guest and token is None:
            token = old_token  # the guest sign-in this device already has
        else:
            end_login(session, old_token)  # replaced by the new sign-in below
    if token is None:
        token = start_login(session, username, request.headers.get("user-agent"))
    response.set_cookie(
        SESSION_COOKIE,
        ".".join(kept + [token]),
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,  # page scripts can't read it
        samesite="lax",  # other websites' requests don't carry it
        secure=cookie_is_secure(request),  # https only, except on this computer
        path="/",
    )
    if as_guest:
        response.set_cookie(ACTIVE_COOKIE, GUEST_NAME, max_age=int(SESSION_LIFETIME.total_seconds()),
                            httponly=True, samesite="lax", secure=cookie_is_secure(request), path="/")
    else:
        response.delete_cookie(ACTIVE_COOKIE, path="/")



@app.post("/login/guest")
def login_as_guest(request: Request, session: Session = Depends(get_session)):
    """"login as guest?" on the home page: sign this device in without a password.

    For now guests can do everything you can, except what needs the agent
    editing password (viewing or replacing keys, deleting agents). Like any
    sign-in, it lasts a day and ends on Log out or when DASHBOARD_PASSWORD changes.
    """
    response = RedirectResponse(HOME_AFTER_SIGN_IN, status_code=303)  # the tree, as for Login
    # The device keeps any other account it's signed into (e.g. yours), so a
    # later Login uses that one again.
    sign_in_device(request, response, session, GUEST_NAME, as_guest=True)
    return response


@app.post("/logout", dependencies=[Depends(require_csrf)])
def logout(
    request: Request,
    everywhere: bool = Form(False),
    session: Session = Depends(get_session),
):
    """Sign this device out of all its accounts (or every device, with
    "Sign out all devices")."""
    if everywhere:
        end_login(session, None, everywhere=True)
    else:
        end_device_logins(session, request)
    response = RedirectResponse("/", status_code=303)  # back to the front page
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax",
                           secure=cookie_is_secure(request))
    response.delete_cookie(ACTIVE_COOKIE, path="/")
    return response


# ---------------------------------------------------------------------------
# Dashboard: the grid and folders (needs a signed-in browser)
# ---------------------------------------------------------------------------


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    page: int = 1,
    folder: int | None = None,
    error: str | None = None,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """The agent grid: all agents, or one folder's agents, 9 cells per page."""
    current_folder = get_folder_or_404(session, folder) if folder is not None else None
    context = (
        grid_context(session, page, current_folder)
        | sidebar_context(session, current_folder)
        | {
            "user": user,
            "error": error,
            # Previews for the sidebar's "Implement connector" window.
            "site_url": site_url(request),
            "connector_code": connector_text(request, "code"),
            "connector_prompt": connector_text(request, "prompt"),
        }
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@app.get("/dashboard/grid", response_class=HTMLResponse)
def dashboard_grid(
    request: Request,
    page: int = 1,
    folder: int | None = None,
    seen: str | None = None,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """HTML fragment with one page of the grid. HTMX asks for it every 3 seconds
    (204 if nothing changed; see poll_reply)."""
    current_folder = get_folder_or_404(session, folder) if folder is not None else None
    content = render_partial("partials/agent_grid.html", grid_context(session, page, current_folder))
    return poll_reply(content, seen, "grid-seen")


@app.get("/dashboard/connector/{file_format}")
def download_connector(
    request: Request,
    file_format: str,
    user: str = Depends(require_user),
):
    """Download the connector as Python code ("code") or as an AI prompt ("prompt")."""
    if file_format not in CONNECTOR_FILES:
        raise HTTPException(status_code=404, detail="Unknown connector format")
    info = CONNECTOR_FILES[file_format]
    return Response(
        connector_text(request, file_format),
        media_type=info["media_type"],
        # "attachment" makes the browser save the file instead of showing it.
        headers={"Content-Disposition": f'attachment; filename="{info["filename"]}"'},
    )


@app.post(
    "/dashboard/folders",
    dependencies=[Depends(require_csrf)],
)
def create_folder(
    name: str = Form(""),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Create a folder from the sidebar's "Add folder" form, then open it."""
    name, error = clean_name(name, MAX_FOLDER_NAME)
    if error is None and name_taken(session, Folder, name):
        error = "A folder with that name already exists."
    if error:
        return redirect_with_error("/dashboard", error)
    folder = Folder(name=name)
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return RedirectResponse(page_url(folder), status_code=303)


@app.post(
    "/dashboard/folders/{folder_id}/rename",
    dependencies=[Depends(require_csrf)],
)
def rename_folder(
    folder_id: int,
    name: str = Form(""),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    folder = get_folder_or_404(session, folder_id)
    name, error = clean_name(name, MAX_FOLDER_NAME)
    if error is None and name_taken(session, Folder, name, except_id=folder.id):
        error = "A folder with that name already exists."
    if error:
        return redirect_with_error(page_url(folder), error)
    folder.name = name
    session.add(folder)
    session.commit()
    return RedirectResponse(page_url(folder), status_code=303)


@app.post(
    "/dashboard/folders/{folder_id}/delete",
    dependencies=[Depends(require_csrf)],
)
def delete_folder(
    folder_id: int,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Delete a folder. The agents in it are kept; they just lose this tag."""
    folder = get_folder_or_404(session, folder_id)
    for link in session.exec(select(AgentFolderLink).where(AgentFolderLink.folder_id == folder.id)):
        session.delete(link)
    session.delete(folder)
    session.commit()
    return RedirectResponse("/dashboard", status_code=303)


# ---------------------------------------------------------------------------
# Dashboard: adding agents
# ---------------------------------------------------------------------------


@app.post(
    "/dashboard/agents",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def create_agent(
    request: Request,
    name: str = Form(""),
    api_key: str = Form(""),
    description: str = Form(""),
    folder_id: int | None = Form(None),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Add an agent from the "Add Agent" card.

    If no API key is typed in, one is generated. The key is stored as a
    fingerprint plus an encrypted copy, so it can be viewed again later with
    the agent editing password.
    """
    name, error = clean_name(name, MAX_AGENT_NAME)
    api_key = api_key.strip()
    key_was_generated = not api_key
    if key_was_generated:
        api_key = generate_api_key()

    if error is None and name_taken(session, Agent, name):
        error = "An agent with that name already exists."
    description, description_error = clean_description(description)
    if error is None:
        error = description_error
    if error is None:
        error = check_new_api_key(session, api_key)

    agent = Agent(name=name, description=description)
    if error is None:
        try:
            store_api_key(agent, api_key)
        except KeyEncryptionNotConfigured:
            error = "KEY_ENCRYPTION_SECRET isn't set on the server, so keys can't be stored."

    if error:
        # Show the form again with the error, keeping what was typed
        # (except the key, which we never send back).
        return templates.TemplateResponse(
            request,
            "partials/add_agent_form.html",
            {"error": error, "name": name, "description": description, "folder_id": folder_id},
        )

    session.add(agent)
    session.commit()
    session.refresh(agent)

    # Adding an agent while looking at a folder puts it in that folder.
    folder = session.get(Folder, folder_id) if folder_id is not None else None
    if folder is not None:
        session.add(AgentFolderLink(agent_id=agent.id, folder_id=folder.id))
        session.commit()

    return templates.TemplateResponse(
        request,
        "partials/agent_created.html",
        {
            "agent": agent,
            "api_key": api_key if key_was_generated else None,
            "site_url": site_url(request),
            # "Done" goes to the grid page where the new agent now appears.
            "done_url": page_url(folder, page_of(session, agent, folder_id if folder else None)),
        },
    )


# ---------------------------------------------------------------------------
# Dashboard: one agent's page
# ---------------------------------------------------------------------------


@app.get("/dashboard/agents/{agent_id}", response_class=HTMLResponse)
def agent_detail(
    request: Request,
    agent_id: int,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """One agent's page: controls, outputs, monitor, and activity log."""
    agent = get_agent_or_404(session, agent_id)
    context = (
        agent_header_context(session, agent)
        | outputs_context(session, agent)  # first visit: nothing chosen, unless pinned
        # "Back" returns to the All Agents page this agent is on.
        | inbox_context(session, agent)
        | {"back_page": page_of(session, agent), "version": monitor_version(agent)}
    )
    return templates.TemplateResponse(request, "agent.html", context)


@app.get("/dashboard/agents/{agent_id}/outputs", response_class=HTMLResponse)
def agent_outputs(
    agent_id: int,
    c: list[str] = Query([]),
    show_all: bool = Query(False, alias="all"),
    sort: str = "date",
    order: str = "desc",
    known: list[str] = Query([]),
    seen: str | None = None,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """HTML fragment: the output list for the Filter's current choices.

    c = the ticked categories, all = the "All" box, sort/order = the sort.
    The page asks again every 3 seconds with the Filter's current values. Only
    the list is replaced, so an open Filter panel isn't disturbed. The panel's
    category rows are only re-sent (out of band) when categories were added or
    removed: `known` lists the categories the panel currently shows.
    """
    agent = get_agent_or_404(session, agent_id)
    context = outputs_context(session, agent, c, show_all, sort, order)
    html_parts = [
        render_partial("partials/outputs_list.html", context),
        render_partial("partials/outputs_summary.html", context, oob=True),
    ]
    if sorted(known) != sorted(c["name"] for c in context["categories"]):
        html_parts.append(render_partial("partials/outputs_options.html", context, oob=True))
    return poll_reply("".join(html_parts), seen, "outputs-seen")


@app.post(
    "/dashboard/agents/{agent_id}/outputs/pin",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def toggle_pin(
    agent_id: int,
    category: str = Form(...),
    c: list[str] = Form([]),
    show_all: bool = Form(False, alias="all"),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Pin a category to the agent's grid card, or unpin it.

    Only one thing can be pinned, so this unpins the Monitor if it was pinned
    (its pin button is updated alongside, "out of band"). Replies with the
    Filter panel's category rows, keeping what's ticked (c, all).
    """
    agent = get_agent_or_404(session, agent_id)
    agent.pinned_category = None if agent.pinned_category == category else category
    if agent.pinned_category:
        agent.pinned_monitor = False
    session.add(agent)
    session.commit()
    context = outputs_context(session, agent, c, show_all)
    return HTMLResponse(render_partial("partials/outputs_options.html", context) + render_monitor_pin(agent, oob=True))


@app.post(
    "/dashboard/agents/{agent_id}/outputs/notify",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def toggle_notify(
    agent_id: int,
    category: str = Form(...),
    c: list[str] = Form([]),
    show_all: bool = Form(False, alias="all"),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Turn "notify me" on or off for a category. Replies with the Filter panel's rows.

    Only the setting is saved for now; a future Discord bot will send the notifications.
    """
    agent = get_agent_or_404(session, agent_id)
    existing = session.get(CategoryNotification, (agent.id, category))
    if existing:
        session.delete(existing)
    else:
        session.add(CategoryNotification(agent_id=agent.id, category=category))
    session.commit()
    context = outputs_context(session, agent, c, show_all)
    return HTMLResponse(render_partial("partials/outputs_options.html", context))


@app.get("/dashboard/outputs/{output_id}/file")
def output_file(
    output_id: int,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Download (or, for safe image types, display) a file an agent sent."""
    output = session.get(Output, output_id)
    file = session.get(OutputFile, output.file_id) if output and output.file_id else None
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    show_inline = file.content_type in INLINE_IMAGE_TYPES
    disposition = "inline" if show_inline else "attachment"
    return Response(
        file.data,
        media_type=file.content_type if show_inline else "application/octet-stream",
        headers={
            # filename*= safely carries any file name, including spaces and accents.
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(output.value)}",
            # Never let the browser guess a different (riskier) file type.
            "X-Content-Type-Options": "nosniff",
            # Files never change once sent, so the browser may keep them.
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )


@app.post(
    "/dashboard/agents/{agent_id}/monitor",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def set_monitor_from_settings(
    request: Request,
    agent_id: int,
    url: str = Form(""),
    label: str = Form(""),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Set or clear the agent's monitor link from Agent settings.

    Replies with the refreshed header (settings stay open) plus the Monitor
    section, which HTMX swaps in separately ("out of band").
    """
    agent = get_agent_or_404(session, agent_id)
    error = None
    if not url.strip():
        replace_monitor(session, agent, by="user")
    elif clean_link(url) is None:
        error = "The monitor link must start with http:// or https://."
    else:
        replace_monitor(session, agent, url=clean_link(url), label=label, by="user")
    header = render_agent_header(request, session, agent, monitor_error=error).body.decode()
    return HTMLResponse(header + render_monitor(agent, oob=True))


@app.get("/dashboard/agents/{agent_id}/monitor", response_class=HTMLResponse)
def agent_monitor(
    agent_id: int,
    version: str | None = None,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """The Monitor section, but only if it changed since `version`.

    The page asks every 10 seconds. "204 No Content" means "nothing new", and
    HTMX then leaves the section alone, so a PDF you're reading isn't reloaded.
    """
    agent = get_agent_or_404(session, agent_id)
    if version == monitor_version(agent):
        return Response(status_code=204)
    return HTMLResponse(render_monitor(agent))


@app.get("/dashboard/agents/{agent_id}/monitor.pdf")
def agent_monitor_pdf(
    agent_id: int,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """The agent's monitor PDF, shown inside the page by the browser's own PDF viewer."""
    agent = get_agent_or_404(session, agent_id)
    file = session.get(OutputFile, agent.monitor_file_id) if agent.monitor_file_id else None
    if file is None:
        raise HTTPException(status_code=404, detail="No monitor PDF")
    return Response(
        file.data,
        media_type="application/pdf",  # only real PDFs are accepted (see /api/monitor/file)
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(agent.monitor_filename or 'monitor.pdf')}",
            "X-Content-Type-Options": "nosniff",
            # The address stays the same when the PDF is replaced, so always check for a newer one.
            "Cache-Control": "private, no-cache",
        },
    )


@app.post(
    "/dashboard/agents/{agent_id}/monitor/pin",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def toggle_monitor_pin(
    agent_id: int,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Pin the Monitor to the agent's grid card (unpinning any category), or unpin it."""
    agent = get_agent_or_404(session, agent_id)
    agent.pinned_monitor = not agent.pinned_monitor
    if agent.pinned_monitor:
        agent.pinned_category = None  # only one thing can be pinned
    session.add(agent)
    session.commit()
    return HTMLResponse(render_monitor_pin(agent))


@app.get("/dashboard/agents/{agent_id}/events", response_class=HTMLResponse)
def agent_events(
    request: Request,
    agent_id: int,
    seen: str | None = None,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """HTML fragment with an agent's 50 newest events. HTMX asks for it every
    3 seconds (204 if nothing changed; see poll_reply)."""
    get_agent_or_404(session, agent_id)
    statement = (
        select(Event)
        .where(Event.agent_id == agent_id)
        .order_by(Event.created_at.desc(), Event.id.desc())
        .limit(50)
    )
    events = session.exec(statement).all()
    return poll_reply(render_partial("partials/events.html", {"events": events}), seen, "events-seen")


@app.post(
    "/dashboard/agents/{agent_id}/command",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def agent_command(
    agent_id: int,
    command: str = Form(...),
    text: str | None = Form(None),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Save a command for one agent to pick up, and reply with an alert.

    Start and Pause also switch the agent's paused state, which the connector
    checks every few seconds (see /api/state). A message is only accepted if
    the agent has said it accepts messages.
    """
    agent = get_agent_or_404(session, agent_id)
    command = command.strip()
    if not command:
        return alert_html("warning", "Command can't be empty.")

    payload = None
    if command == "message":
        if not agent.accepts_messages:
            return alert_html("warning", f"{agent.name} doesn't accept messages.")
        if not text or not text.strip():
            return alert_html("warning", "Type a message first.")
        payload = {"text": text.strip()}

    session.add(Command(agent_id=agent.id, command=command, payload=payload))
    if command in ("start", "pause"):
        agent.paused = command == "pause"
        session.add(agent)
    session.commit()
    session.refresh(agent)
    reply = alert_html("success", f'Sent "{command}" to {agent.name}.')
    # Also update the running/paused badge at the top of the agent's page.
    return reply + render_partial("partials/run_state.html", {"agent": agent}, oob=True)


@app.get("/dashboard/agents/{agent_id}/messages-ready", response_class=HTMLResponse)
def messages_ready(
    agent_id: int,
    ready: bool,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Has the agent started or stopped accepting messages since the page loaded?

    The page asks every 5 seconds, passing what it showed (ready). If nothing
    changed: "204 No Content". If it changed, HX-Refresh reloads the page so the
    message box switches on or off.
    """
    agent = get_agent_or_404(session, agent_id)
    if agent.accepts_messages == ready:
        return Response(status_code=204)
    return HTMLResponse("", headers={"HX-Refresh": "true"})


@app.get("/dashboard/agents/{agent_id}/inbox", response_class=HTMLResponse)
def agent_inbox(
    agent_id: int,
    seen: str | None = None,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """The Inbox window's list of waiting files. Checked every 5 seconds while
    the window is open, so files disappear as the agent takes them."""
    agent = get_agent_or_404(session, agent_id)
    return poll_reply(render_inbox_list(session, agent), seen, "inbox-seen")


@app.post(
    "/dashboard/agents/{agent_id}/inbox",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
async def upload_to_inbox(
    agent_id: int,
    files: list[UploadFile] = File(...),
    note: str = Form(""),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Put one or more files in an agent's Inbox (up to 50 MB each)."""
    agent = get_agent_or_404(session, agent_id)
    note = note.strip()[:MAX_INBOX_NOTE] or None
    stored = []
    for upload in files:
        if not upload.filename:
            continue  # the form was sent with no file chosen
        try:
            item = await store_inbox_file(session, agent, upload, note)
        except InboxRefused as refusal:
            done = f"Uploaded {', '.join(stored)}. " if stored else ""
            return HTMLResponse(render_inbox_list(session, agent, error=done + f"Not uploaded: {refusal}"))
        log_activity(session, agent.id, "inbox", f"Inbox: you uploaded {item.filename} ({human_size(item.size)})")
        session.commit()
        stored.append(item.filename)
    if not stored:
        return HTMLResponse(render_inbox_list(session, agent, error="Choose a file to upload."))
    return HTMLResponse(render_inbox_list(session, agent, notice=f"Uploaded {', '.join(stored)}."))


def get_inbox_item_or_404(session: Session, item_id: int) -> InboxItem:
    item = session.get(InboxItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inbox file not found (the agent may have taken it already)")
    return item


@app.get("/dashboard/inbox/{item_id}/file")
def inbox_file(
    item_id: int,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Download a waiting inbox file (to check what you uploaded)."""
    return inbox_file_response(session, get_inbox_item_or_404(session, item_id))


@app.post(
    "/dashboard/inbox/{item_id}/delete",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def remove_from_inbox(
    item_id: int,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Take a waiting file back out of an agent's Inbox."""
    item = session.get(InboxItem, item_id)
    if item is None:  # already taken by the agent: just show the current list
        raise HTTPException(status_code=404, detail="Inbox file not found (the agent may have taken it already)")
    agent = get_agent_or_404(session, item.agent_id)
    filename = item.filename
    log_activity(session, agent.id, "inbox", f"Inbox: you removed {filename} before the agent took it")
    delete_inbox_item(session, item)
    session.commit()
    return HTMLResponse(render_inbox_list(session, agent, notice=f"Removed {filename}."))


@app.post(
    "/dashboard/agents/{agent_id}/rename",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def rename_agent(
    request: Request,
    agent_id: int,
    name: str = Form(""),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Change an agent's display name. Its API key stays the same."""
    agent = get_agent_or_404(session, agent_id)
    name, error = clean_name(name, MAX_AGENT_NAME)
    if error is None and name_taken(session, Agent, name, except_id=agent.id):
        error = "An agent with that name already exists."
    if error is None:
        agent.name = name
        session.add(agent)
        session.commit()
        session.refresh(agent)
    return render_agent_header(request, session, agent, error)


@app.post(
    "/dashboard/agents/{agent_id}/description",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def set_description(
    request: Request,
    agent_id: int,
    description: str = Form(""),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Change what the agent's description says (empty removes it)."""
    agent = get_agent_or_404(session, agent_id)
    cleaned, error = clean_description(description)
    if error is None:
        agent.description = cleaned
        session.add(agent)
        session.commit()
        session.refresh(agent)
    return render_agent_header(request, session, agent, description_error=error)


@app.post(
    "/dashboard/agents/{agent_id}/tags",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def add_tag(
    request: Request,
    agent_id: int,
    folder_id: int = Form(...),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Put an agent in a folder."""
    agent = get_agent_or_404(session, agent_id)
    get_folder_or_404(session, folder_id)
    if session.get(AgentFolderLink, (agent.id, folder_id)) is None:
        session.add(AgentFolderLink(agent_id=agent.id, folder_id=folder_id))
        session.commit()
    return render_agent_header(request, session, agent)


@app.post(
    "/dashboard/agents/{agent_id}/tags/{folder_id}/remove",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def remove_tag(
    request: Request,
    agent_id: int,
    folder_id: int,
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Take an agent out of a folder."""
    agent = get_agent_or_404(session, agent_id)
    link = session.get(AgentFolderLink, (agent.id, folder_id))
    if link is not None:
        session.delete(link)
        session.commit()
    return render_agent_header(request, session, agent)


@app.post(
    "/dashboard/agents/{agent_id}/delete",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def delete_agent(
    agent_id: int,
    password: str = Form(""),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Delete an agent and everything it sent or was sent. Needs AGENT_EDIT_PASSWORD."""
    agent = get_agent_or_404(session, agent_id)
    if not edit_password_matches(password):
        return error_html("Wrong agent editing password. Nothing was deleted.")

    # Delete the rows that point at the agent first, then the agent itself.
    for output in session.exec(select(Output).where(Output.agent_id == agent.id)).all():
        file = session.get(OutputFile, output.file_id) if output.file_id else None
        session.delete(output)
        if file is not None:
            session.delete(file)
    for model in (Event, Command, AgentFolderLink, CategoryNotification):
        for row in session.exec(select(model).where(model.agent_id == agent.id)):
            session.delete(row)
    for item in session.exec(select(InboxItem).where(InboxItem.agent_id == agent.id)).all():
        delete_inbox_item(session, item)
    monitor_file = session.get(OutputFile, agent.monitor_file_id) if agent.monitor_file_id else None
    session.delete(agent)
    if monitor_file is not None:
        session.delete(monitor_file)
    session.commit()
    # This header tells HTMX to load the dashboard instead of swapping content.
    return HTMLResponse("", headers={"HX-Redirect": "/dashboard"})


@app.post(
    "/dashboard/agents/{agent_id}/key/view",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def view_api_key(
    request: Request,
    agent_id: int,
    password: str = Form(""),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Show an agent's current API key. Needs AGENT_EDIT_PASSWORD."""
    agent = get_agent_or_404(session, agent_id)
    if not edit_password_matches(password):
        return error_html("Wrong agent editing password.")
    if agent.api_key_encrypted is None:
        return error_html(
            "This agent's key was added before keys could be viewed. "
            "Use Replace key to get a new one you can view."
        )
    try:
        api_key = decrypt_api_key(agent.api_key_encrypted)
    except KeyEncryptionNotConfigured:
        return error_html("KEY_ENCRYPTION_SECRET isn't set on the server.")
    if api_key is None:
        return error_html(
            "This key can't be decrypted. KEY_ENCRYPTION_SECRET has probably changed. "
            "Use Replace key to make a new one."
        )
    response = templates.TemplateResponse(
        request,
        "partials/api_key.html",
        {"agent": agent, "api_key": api_key, "replaced": False, "site_url": site_url(request)},
    )
    response.headers["Cache-Control"] = "no-store"  # don't keep the key in the browser's cache
    return response


@app.post(
    "/dashboard/agents/{agent_id}/key/replace",
    response_class=HTMLResponse,
    dependencies=[Depends(require_csrf)],
)
def replace_api_key(
    request: Request,
    agent_id: int,
    password: str = Form(""),
    new_key: str = Form(""),
    session: Session = Depends(get_session),
    user: str = Depends(require_user),
):
    """Give an agent a new API key. The old key stops working straight away.

    Leave new_key blank to generate one. Needs AGENT_EDIT_PASSWORD.
    """
    agent = get_agent_or_404(session, agent_id)
    if not edit_password_matches(password):
        return error_html("Wrong agent editing password. The key was not changed.")

    new_key = new_key.strip() or generate_api_key()
    error = check_new_api_key(session, new_key)
    if error:
        return error_html(error)
    try:
        store_api_key(agent, new_key)
    except KeyEncryptionNotConfigured:
        return error_html("KEY_ENCRYPTION_SECRET isn't set on the server, so keys can't be stored.")
    session.add(agent)
    session.commit()

    response = templates.TemplateResponse(
        request,
        "partials/api_key.html",
        {"agent": agent, "api_key": new_key, "replaced": True, "site_url": site_url(request)},
    )
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Agent API (needs the agent's own X-API-Key header; returns JSON)
# ---------------------------------------------------------------------------


class EventIn(BaseModel):
    """What an agent sends when it reports something."""

    message: str
    type: str = "log"
    data: dict[str, Any] | None = None
    created_at: datetime | None = None  # when it happened, if sent late (offline buffer)


class CommandUpdate(BaseModel):
    """What an agent sends after handling a command."""

    status: str = "done"


class OutputIn(BaseModel):
    """What output(content, category) sends (files use /api/outputs/file instead)."""

    category: str
    content: Any  # text, a number, a link, or a list/dict
    created_at: datetime | None = None  # when it was made, if sent late (offline buffer)


class MonitorIn(BaseModel):
    """What set_monitor(url, label) sends. A null url clears the monitor."""

    url: str | None
    label: str | None = None
    created_at: datetime | None = None  # when it was set, if sent late (offline buffer)

@app.post("/api/events", status_code=201)
def create_event(
    event_in: EventIn,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> Event:
    when, _ = when_made(event_in.created_at)
    event = Event(
        agent_id=agent.id, message=event_in.message, type=event_in.type, data=event_in.data, created_at=when
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


class StateIn(BaseModel):
    """What the connector sends when it checks in. Leave a field out to keep it as it is."""

    accepts_messages: bool | None = None
    accepts_inbox: bool | None = None
    # How often this agent checks in, in seconds (1 second to 1 week).
    check_in_every: int | None = Field(default=None, ge=MIN_CHECK_IN, le=MAX_CHECK_IN)


@app.post("/api/state")
def agent_state(
    state_in: StateIn,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """An agent's check-in, as often as the agent itself decides.

    The agent can say how often it checks in (so the dashboard knows when to
    show it as offline) and whether it accepts messages and reads its Inbox,
    and it learns whether it's paused and how many Inbox files are waiting. Any API call marks the agent as seen; this is the one meant
    for checking in.
    """
    changed = False
    if state_in.accepts_messages is not None and agent.accepts_messages != state_in.accepts_messages:
        agent.accepts_messages = state_in.accepts_messages
        changed = True
    if state_in.accepts_inbox is not None and agent.accepts_inbox != state_in.accepts_inbox:
        agent.accepts_inbox = state_in.accepts_inbox
        changed = True
    if state_in.check_in_every is not None and agent.check_in_seconds != state_in.check_in_every:
        agent.check_in_seconds = state_in.check_in_every
        changed = True
    if changed:
        session.add(agent)
        session.commit()
        session.refresh(agent)
    waiting = session.exec(select(func.count(InboxItem.id)).where(InboxItem.agent_id == agent.id)).one()
    return {
        "paused": agent.paused,
        "accepts_messages": agent.accepts_messages,
        "accepts_inbox": agent.accepts_inbox,
        "inbox_waiting": waiting,  # files waiting in this agent's Inbox
        "check_in_every": check_in_interval(agent),
    }


def inbox_item_info(item: InboxItem) -> dict:
    return {"id": item.id, "filename": item.filename, "content_type": item.content_type, "size": item.size,
            "note": item.note, "uploaded_at": iso(item.uploaded_at), "file_url": f"/api/inbox/{item.id}/file"}


def own_inbox_item(session: Session, agent: Agent, item_id: int) -> InboxItem:
    """One of the calling agent's own inbox files. Another agent's looks "not found"."""
    item = session.get(InboxItem, item_id)
    if item is None or item.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Inbox file not found")
    return item


@app.get("/api/inbox")
def api_inbox(
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> list[dict]:
    """The files waiting in the calling agent's Inbox, oldest first."""
    return [inbox_item_info(item) for item in inbox_items(session, agent.id)]


@app.get("/api/inbox/{item_id}/file")
def api_inbox_file(
    item_id: int,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """Download one of the calling agent's inbox files (streamed in pieces)."""
    return inbox_file_response(session, own_inbox_item(session, agent, item_id))


@app.delete("/api/inbox/{item_id}")
def api_inbox_received(
    item_id: int,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """The agent confirms it has stored an inbox file: it's deleted from the dashboard."""
    item = own_inbox_item(session, agent, item_id)
    log_activity(session, agent.id, "inbox", f"Inbox: agent received {item.filename} ({human_size(item.size)})")
    delete_inbox_item(session, item)
    session.commit()
    return {"deleted": 1}


@app.get("/api/commands")
def list_pending_commands(
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> list[Command]:
    """The calling agent's commands it hasn't handled yet, oldest first."""
    statement = (
        select(Command)
        .where(Command.agent_id == agent.id, Command.status == "pending")
        .order_by(Command.created_at, Command.id)
    )
    return list(session.exec(statement).all())


@app.patch("/api/commands/{command_id}")
def update_command(
    command_id: int,
    update: CommandUpdate,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> Command:
    command = session.get(Command, command_id)
    # An agent may only update its own commands; others look "not found".
    if command is None or command.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Command not found")
    command.status = update.status
    session.add(command)
    session.commit()
    session.refresh(command)
    return command


@app.post("/api/outputs", status_code=201)
def create_output(
    output_in: OutputIn,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> Output:
    """Save one output: text, a number, a link, or a list/dict."""
    if output_in.content is None:
        raise HTTPException(422, "content can't be empty")
    kind, value = describe_content(output_in.content)
    when, late = when_made(output_in.created_at)
    output = Output(
        agent_id=agent.id, category=clean_category(output_in.category), kind=kind, value=value, created_at=when
    )
    session.add(output)
    session.flush()  # gives the output its id, for the Activity log line
    log_new_output(session, output, late)
    session.commit()
    session.refresh(output)
    return output


@app.post("/api/outputs/file", status_code=201)
async def create_file_output(
    category: str = Form(...),
    file: UploadFile = File(...),
    created_at: str | None = Form(None),
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> Output:
    """Save one file output (up to 5 MB). The file itself goes into the database."""
    category = clean_category(category)
    when, late = when_made(created_at)
    data = await file.read(MAX_OUTPUT_FILE_BYTES + 1)  # read one byte extra to spot oversize files
    if len(data) > MAX_OUTPUT_FILE_BYTES:
        raise HTTPException(413, f"file is too big (max {MAX_OUTPUT_FILE_BYTES // (1024 * 1024)} MB)")
    filename = Path(file.filename or "file").name[:200] or "file"
    stored = OutputFile(
        content_type=(file.content_type or "application/octet-stream")[:100], size=len(data), data=data
    )
    session.add(stored)
    session.commit()
    session.refresh(stored)
    output = Output(
        agent_id=agent.id, category=category, kind="file", value=filename, file_id=stored.id, created_at=when
    )
    session.add(output)
    session.flush()
    log_new_output(session, output, late)
    session.commit()
    session.refresh(output)
    return output


@app.put("/api/monitor")
def set_monitor(
    monitor_in: MonitorIn,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """Make a link the agent's monitor (or, with url null, remove the monitor)."""
    if monitor_in.url is None or not monitor_in.url.strip():
        applied = replace_monitor(session, agent, made_at=monitor_in.created_at)
    else:
        url = clean_link(monitor_in.url)
        if url is None:
            raise HTTPException(422, "url must start with http:// or https://")
        applied = replace_monitor(session, agent, url=url, label=monitor_in.label, made_at=monitor_in.created_at)
    return {"url": agent.monitor_url, "label": agent.monitor_label, "applied": applied}


@app.post("/api/monitor/file")
async def set_monitor_pdf(
    file: UploadFile = File(...),
    label: str | None = Form(None),
    created_at: str | None = Form(None),
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """Make a PDF the agent's monitor (up to 5 MB). It replaces the previous monitor.

    Useful for something regenerated on a schedule, like a daily summary or a report.
    """
    data = await file.read(MAX_OUTPUT_FILE_BYTES + 1)
    if len(data) > MAX_OUTPUT_FILE_BYTES:
        raise HTTPException(413, f"file is too big (max {MAX_OUTPUT_FILE_BYTES // (1024 * 1024)} MB)")
    # Check the file really is a PDF (every PDF starts with "%PDF-"), so nothing
    # else can ever be shown inside the page pretending to be one.
    if not data.startswith(b"%PDF-"):
        raise HTTPException(422, "monitor files must be PDFs")
    filename = Path(file.filename or "monitor.pdf").name[:200] or "monitor.pdf"
    stored = OutputFile(content_type="application/pdf", size=len(data), data=data)
    session.add(stored)
    session.commit()
    session.refresh(stored)
    applied = replace_monitor(session, agent, file=stored, filename=filename, label=label, made_at=created_at)
    return {"filename": filename, "label": agent.monitor_label, "applied": applied}


# ---------------------------------------------------------------------------
# Agent API: reading and deleting
#
# Any agent may READ every agent's data (to build on each other's work), but
# may only DELETE its own. Reads never include API keys or the commands you
# sent an agent (Start/Pause/messages stay between you and that agent).
# Deletes are noted in the agent's Activity log, so you can see what went.
# ---------------------------------------------------------------------------

DEFAULT_READ_LIMIT = 50
MAX_READ_LIMIT = 500


def find_agent(session: Session, caller: Agent, ref: str) -> Agent:
    """The agent a read is about: "me", its id, or its exact name. 404 if none."""
    if ref == "me":
        return caller
    agent = session.get(Agent, int(ref)) if ref.isdigit() else None
    if agent is None:
        agent = session.exec(select(Agent).where(Agent.name == ref)).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def iso(moment: datetime | None) -> str | None:
    """A time as ISO 8601 text in UTC, e.g. 2026-10-03T08:00:00+00:00."""
    return as_utc(moment).isoformat() if moment else None


def monitor_info(agent: Agent) -> dict | None:
    """What an agent's Monitor shows, or None if it has none."""
    common = {"label": agent.monitor_label, "updated_at": iso(agent.monitor_updated_at)}
    if agent.monitor_file_id:
        return {"kind": "pdf", "filename": agent.monitor_filename,
                "file_url": f"/api/agents/{agent.id}/monitor.pdf", **common}
    if agent.monitor_url:
        return {"kind": "link", "url": agent.monitor_url, **common}
    return None


def agent_info(session: Session, agent: Agent, caller: Agent) -> dict:
    """Everything one agent may know about another (never its key)."""
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "you": agent.id == caller.id,
        "folders": [folder.name for folder in folders_of(session, agent.id)],
        "online": is_online(agent),
        "paused": agent.paused,
        "accepts_messages": agent.accepts_messages,
        "check_in_every": check_in_interval(agent),
        "created_at": iso(agent.created_at),
        "last_seen": iso(agent.last_seen),
        "monitor": monitor_info(agent),
    }


def output_content(output: Output) -> Any:
    """An output's content as the agent sent it: a number, a list/dict, or text."""
    if output.kind in ("number", "json"):
        return json.loads(output.value)
    return output.value


def outputs_info(session: Session, outputs: list[Output]) -> list[dict]:
    """Outputs as JSON. Files are described (name, type, size, address), not included."""
    file_ids = [output.file_id for output in outputs if output.file_id]
    files = {}
    if file_ids:
        # Only the small columns: never load every file's bytes for a listing.
        rows = session.exec(
            select(OutputFile.id, OutputFile.content_type, OutputFile.size).where(OutputFile.id.in_(file_ids))
        )
        files = {file_id: (content_type, size) for file_id, content_type, size in rows}
    result = []
    for output in outputs:
        item = {
            "id": output.id,
            "agent_id": output.agent_id,
            "category": output.category,
            "kind": output.kind,
            "content": output_content(output),
            "created_at": iso(output.created_at),
        }
        if output.file_id in files:
            content_type, size = files[output.file_id]
            item["file"] = {"filename": output.value, "content_type": content_type, "size": size,
                            "url": f"/api/outputs/{output.id}/file"}
        result.append(item)
    return result


def event_info(event: Event) -> dict:
    return {"id": event.id, "agent_id": event.agent_id, "type": event.type, "message": event.message,
            "data": event.data, "created_at": iso(event.created_at)}


def parse_time(raw: str | None, name: str) -> datetime | None:
    """A ?since= / ?before= time from the address, or a 422 error."""
    if not raw:
        return None
    try:
        return as_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        raise HTTPException(422, f"{name} must be an ISO date and time, e.g. 2026-10-03T08:00:00Z")


def file_response(file: OutputFile, filename: str) -> Response:
    """A stored file as a download (never shown as a page)."""
    return Response(
        file.data,
        media_type=file.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/agents")
def api_list_agents(
    caller: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Every agent on the dashboard, A to Z. "you": true marks the caller."""
    agents = session.exec(select(Agent).order_by(func.lower(Agent.name))).all()
    return [agent_info(session, agent, caller) for agent in agents]


@app.get("/api/agents/{ref}")
def api_get_agent(
    ref: str,
    caller: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """One agent ("me", an id, or a name), with its output categories."""
    agent = find_agent(session, caller, ref)
    rows = session.exec(
        select(Output.category, func.count(Output.id), func.max(Output.created_at))
        .where(Output.agent_id == agent.id)
        .group_by(Output.category)
        .order_by(func.lower(Output.category))
    )
    info = agent_info(session, agent, caller)
    info["categories"] = [
        {"name": name, "count": count, "latest_at": iso(latest)} for name, count, latest in rows
    ]
    return info


@app.get("/api/agents/{ref}/outputs")
def api_read_outputs(
    ref: str,
    category: list[str] | None = Query(None),
    since: str | None = None,
    limit: int = Query(DEFAULT_READ_LIMIT, ge=1, le=MAX_READ_LIMIT),
    offset: int = Query(0, ge=0),
    caller: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> list[dict]:
    """An agent's outputs, newest first. Optional: only some categories
    (repeat ?category=), only those made at or after ?since=, and paging."""
    agent = find_agent(session, caller, ref)
    statement = select(Output).where(Output.agent_id == agent.id)
    if category:
        statement = statement.where(Output.category.in_(category))
    if (since_time := parse_time(since, "since")) is not None:
        statement = statement.where(Output.created_at >= since_time)
    statement = statement.order_by(Output.created_at.desc(), Output.id.desc()).offset(offset).limit(limit)
    return outputs_info(session, list(session.exec(statement).all()))


@app.get("/api/outputs/{output_id}/file")
def api_output_file(
    output_id: int,
    caller: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> Response:
    """The file of any agent's file output."""
    output = session.get(Output, output_id)
    file = session.get(OutputFile, output.file_id) if output and output.file_id else None
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return file_response(file, output.value)


@app.get("/api/agents/{ref}/events")
def api_read_events(
    ref: str,
    type: str | None = None,
    since: str | None = None,
    limit: int = Query(DEFAULT_READ_LIMIT, ge=1, le=MAX_READ_LIMIT),
    offset: int = Query(0, ge=0),
    caller: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> list[dict]:
    """An agent's Activity log, newest first. Optional: one ?type=, ?since=, paging."""
    agent = find_agent(session, caller, ref)
    statement = select(Event).where(Event.agent_id == agent.id)
    if type:
        statement = statement.where(Event.type == type)
    if (since_time := parse_time(since, "since")) is not None:
        statement = statement.where(Event.created_at >= since_time)
    statement = statement.order_by(Event.created_at.desc(), Event.id.desc()).offset(offset).limit(limit)
    return [event_info(event) for event in session.exec(statement).all()]


@app.get("/api/agents/{ref}/monitor")
def api_read_monitor(
    ref: str,
    caller: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """What an agent's Monitor shows: {"monitor": {...}} or {"monitor": null}."""
    return {"monitor": monitor_info(find_agent(session, caller, ref))}


@app.get("/api/agents/{ref}/monitor.pdf")
def api_read_monitor_pdf(
    ref: str,
    caller: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> Response:
    """The PDF an agent's Monitor shows (404 if its monitor isn't a PDF)."""
    agent = find_agent(session, caller, ref)
    file = session.get(OutputFile, agent.monitor_file_id) if agent.monitor_file_id else None
    if file is None:
        raise HTTPException(status_code=404, detail="This agent's monitor isn't a PDF")
    return file_response(file, agent.monitor_filename or "monitor.pdf")


def delete_outputs(session: Session, agent: Agent, outputs: list[Output], what: str) -> int:
    """Delete some of the caller's outputs (and their files), log it, and commit."""
    for output in outputs:
        file = session.get(OutputFile, output.file_id) if output.file_id else None
        session.delete(output)
        if file is not None:
            session.delete(file)
    if outputs:
        count = len(outputs)
        log_activity(session, agent.id, "delete", f"Deleted {count} output{'s' if count != 1 else ''}{what}")
    session.commit()
    return len(outputs)


@app.delete("/api/outputs/{output_id}")
def api_delete_output(
    output_id: int,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """Delete one of the caller's own outputs. Other agents' outputs get 403."""
    output = session.get(Output, output_id)
    if output is None:
        raise HTTPException(status_code=404, detail="Output not found")
    if output.agent_id != agent.id:
        raise HTTPException(status_code=403, detail="Agents can only delete their own outputs")
    return {"deleted": delete_outputs(session, agent, [output], f' in "{output.category}"')}


@app.delete("/api/outputs")
def api_delete_outputs(
    category: str | None = None,
    before: str | None = None,
    all: bool = False,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """Delete many of the caller's own outputs: one ?category=, and/or those
    made before ?before=. Deleting everything needs ?all=true, so a missing
    filter can't wipe everything by mistake."""
    before_time = parse_time(before, "before")
    if category is None and before_time is None and not all:
        raise HTTPException(422, "say what to delete: category, before, or all=true")
    statement = select(Output).where(Output.agent_id == agent.id)
    what = ""
    if category is not None:
        statement = statement.where(Output.category == " ".join(category.split()))
        what += f' in "{" ".join(category.split())}"'
    if before_time is not None:
        statement = statement.where(Output.created_at < before_time)
        what += f" made before {before_time:%Y-%m-%d %H:%M:%S} UTC"
    return {"deleted": delete_outputs(session, agent, list(session.exec(statement).all()), what)}


def delete_events(session: Session, agent: Agent, events: list[Event]) -> int:
    """Delete some of the caller's Activity lines, leave one line saying so, and commit."""
    for event in events:
        session.delete(event)
    if events:
        count = len(events)
        log_activity(session, agent.id, "delete", f"Deleted {count} activity line{'s' if count != 1 else ''}")
    session.commit()
    return len(events)


@app.delete("/api/events/{event_id}")
def api_delete_event(
    event_id: int,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """Delete one of the caller's own Activity lines. Other agents' lines get 403."""
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.agent_id != agent.id:
        raise HTTPException(status_code=403, detail="Agents can only delete their own activity")
    return {"deleted": delete_events(session, agent, [event])}


@app.delete("/api/events")
def api_delete_events(
    before: str | None = None,
    all: bool = False,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """Delete the caller's Activity lines made before ?before=, or all of them with ?all=true."""
    before_time = parse_time(before, "before")
    if before_time is None and not all:
        raise HTTPException(422, "say what to delete: before, or all=true")
    statement = select(Event).where(Event.agent_id == agent.id)
    if before_time is not None:
        statement = statement.where(Event.created_at < before_time)
    return {"deleted": delete_events(session, agent, list(session.exec(statement).all()))}


@app.delete("/api/monitor")
def api_delete_monitor(
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
) -> dict:
    """Remove the caller's own Monitor (the same as setting it to null)."""
    had_monitor = bool(agent.monitor_url or agent.monitor_file_id)
    if had_monitor:
        replace_monitor(session, agent)
    return {"deleted": 1 if had_monitor else 0}

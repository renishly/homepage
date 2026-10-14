"""Database setup and table definitions.

The website and the agents never talk to each other directly. Instead:
  - each agent writes Event rows (messages for you) through the API, and
  - the dashboard writes Command rows (messages for one agent).
Each side reads what the other side wrote. Every Event and Command belongs
to one Agent, so several agents can share the same dashboard.

Agents can also be sorted into Folders. An agent can be in several folders;
the AgentFolderLink table records which agent is in which folder.

Besides Events (the activity log), agents send Outputs: the results they
choose to share, each with a category. Files sent as outputs are stored in
the OutputFile table, so they survive restarts on any host.
"""

import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import JSON, Column, LargeBinary, inspect, text
from sqlmodel import Field, Session, SQLModel, create_engine

# Load secrets from the .env file into environment variables. This lives here
# because db.py is the first of our modules to need them (DATABASE_URL below).
# The tests set HOMEPAGE_TESTING=1 so they never read your real .env file.
if os.getenv("HOMEPAGE_TESTING") != "1":
    load_dotenv()


def utc_now() -> datetime:
    """Current time in UTC. Used as the default for created_at columns."""
    return datetime.now(timezone.utc)


class Agent(SQLModel, table=True):
    """One AI agent, added from the dashboard's "Add Agent" card."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)  # display name; can be renamed
    # What the agent does, in a few sentences. Written by you (on Add Agent or
    # in Agent settings) and readable by every agent, so they know each other.
    description: str | None = None
    # The agent proves who it is with its own API key. The key is stored twice
    # (see security.py), never as plain text:
    #   - a fingerprint (SHA-256 hash), used to recognise the agent quickly;
    #   - an encrypted copy, so "View key" can show it again. Decrypting needs
    #     KEY_ENCRYPTION_SECRET, which lives in .env, not in the database.
    api_key_hash: str = Field(unique=True, index=True)
    # None for agents added before keys were stored encrypted; replacing the
    # key fixes that.
    api_key_encrypted: str | None = None
    # The Monitor: the agent's latest "where my data lives" view. Either a link
    # (a Google Sheet, Grafana...) or a PDF shown inside the page (a daily
    # summary, a report...), never both. Set by the agent through the API, or
    # (links only) by you in Agent settings. Only the latest one is kept.
    monitor_url: str | None = None
    monitor_file_id: int | None = Field(default=None, foreign_key="outputfile.id")
    monitor_filename: str | None = None
    monitor_label: str | None = None
    monitor_updated_at: datetime | None = None
    # What's pinned to this agent's grid card: one output category, or the
    # Monitor, or nothing (only one thing at a time).
    pinned_category: str | None = None
    pinned_monitor: bool = False
    # Set by the dashboard's Start/Pause buttons. The connector checks it every
    # few seconds: while paused it holds outputs and monitor updates, and
    # wait_if_paused() lets the agent's own work stop at a safe point.
    paused: bool = False
    # Set by the agent (accept_messages() in the connector). Until it says it
    # accepts messages, the dashboard's message box is switched off.
    accepts_messages: bool = False
    # Set by the agent (accept_inbox() in the connector): it picks up files
    # you upload to its Inbox. You can upload before that; they just wait.
    accepts_inbox: bool = False
    # How often the agent says it checks in, in seconds (from every few seconds
    # to once a day). The dashboard counts it as "online" while it keeps to that
    # rhythm. None until the agent declares one (then a default is assumed).
    check_in_seconds: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    # Updated every time the agent contacts the API; used to show "online".
    # None means the agent has never connected.
    last_seen: datetime | None = None


class Folder(SQLModel, table=True):
    """A folder (tag) for grouping agents in the sidebar."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class AgentFolderLink(SQLModel, table=True):
    """Says "this agent is in this folder". One row per (agent, folder) pair."""

    agent_id: int = Field(foreign_key="agent.id", primary_key=True)
    folder_id: int = Field(foreign_key="folder.id", primary_key=True)


class Event(SQLModel, table=True):
    """A message from an agent to the user (shown on the dashboard)."""

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    type: str = "log"  # usually "log", "status" or "error"
    message: str
    # JSON needs an explicit column type so it works on both SQLite and Postgres.
    data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class Command(SQLModel, table=True):
    """A message from the user to one agent (sent from the dashboard)."""

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    command: str  # e.g. "start", "pause", "message"
    payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    status: str = "pending"  # set to "done" by the agent once handled


class OutputFile(SQLModel, table=True):
    """The bytes of a file an agent sent with output(). Kept apart from Output
    so that listing outputs doesn't load every file into memory."""

    id: int | None = Field(default=None, primary_key=True)
    content_type: str
    size: int
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))


class Output(SQLModel, table=True):
    """One result an agent chose to share with output(content, category)."""

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    category: str = Field(index=True)  # which output channel, e.g. "articles"
    # What `value` holds: "text", "number", "link", "json" (a list or dict,
    # stored as text), or "file" (value is then the file's name).
    kind: str
    value: str
    file_id: int | None = Field(default=None, foreign_key="outputfile.id")


class CategoryNotification(SQLModel, table=True):
    """Marks an output category as "notify me" (the bell icon).

    Nothing sends notifications yet; a future Discord bot will read this table.
    """

    agent_id: int = Field(foreign_key="agent.id", primary_key=True)
    category: str = Field(primary_key=True)


class InboxItem(SQLModel, table=True):
    """A file you uploaded to one agent's Inbox, waiting for that agent.

    The agent downloads it at a check-in, stores the data its own way, and
    confirms; the item (and its file) is then deleted. Only that agent can
    see or take it.
    """

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    filename: str
    content_type: str
    size: int  # bytes
    note: str | None = None  # an optional note you typed with the upload
    uploaded_at: datetime = Field(default_factory=utc_now)


class InboxChunk(SQLModel, table=True):
    """One piece (up to 1 MB) of an inbox file. Large files are stored and sent
    piece by piece, so they never have to fit in the server's memory at once."""

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="inboxitem.id", index=True)
    position: int  # 0, 1, 2... the order of the pieces
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))


class TechSetting(SQLModel, table=True):
    """Developer-mode settings for one "tech" (a card in the home page's tree).

    The techs themselves (their titles, pages and icons) are defined in
    main.py; this only stores what you change in developer mode. A tech with
    no row here is "open".
    """

    slug: str = Field(primary_key=True)  # e.g. "dashboard", "data-tracking"
    # "open": guests can open it. "private": guests see it greyed out and can't
    # open it. "hidden": guests don't see it.
    visibility: str = "open"
    # Your own description for the tech, written in developer mode (None: the
    # one it comes with).
    description: str | None = None
    # Where it sits among the leaf techs (0 = top), after you drag it in
    # developer mode. None: its place in main.py's list.
    position: int | None = None
    # The page-wide API key, for pages that have one (encrypted like agent
    # keys, so it can be shown again; see security.py).
    api_key_encrypted: str | None = None


class LoginSession(SQLModel, table=True):
    """One signed-in device (a browser that logged in on the login page).

    The browser keeps a long random token in a cookie; only its fingerprint
    (SHA-256) is stored here, so a copied database can't be used to sign in.
    Logging out deletes the row, which signs that device out straight away.
    """

    id: int | None = Field(default=None, primary_key=True)
    token_hash: str = Field(unique=True, index=True)
    username: str
    # Changes when DASHBOARD_USER or DASHBOARD_PASSWORD changes, so changing
    # the password signs every device out.
    login_check: str
    user_agent: str | None = None  # which browser, e.g. "Mozilla/5.0 (iPhone...)"
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime


def normalize_database_url(url: str) -> str:
    """Make sure a Postgres URL uses the psycopg (version 3) driver.

    Render hands out URLs starting with "postgres://" or "postgresql://".
    SQLAlchemy needs "postgresql+psycopg://" to know which driver to use.
    """
    for old_prefix in ("postgres://", "postgresql://"):
        if url.startswith(old_prefix):
            return "postgresql+psycopg://" + url[len(old_prefix):]
    return url


def make_engine(url: str):
    """Create a SQLAlchemy engine for the given database URL."""
    if url.startswith("sqlite"):
        # SQLite normally refuses to be used from more than one thread;
        # FastAPI serves requests from several threads, so we allow it.
        return create_engine(url, connect_args={"check_same_thread": False})
    # pool_pre_ping checks a connection still works before using it, which
    # avoids errors after the database has been idle for a while.
    return create_engine(url, pool_pre_ping=True)


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL") or "sqlite:///./local.db")
engine = make_engine(DATABASE_URL)


def create_db_and_tables() -> None:
    """Create any missing tables, then add any missing columns to existing ones.

    This handles *adding* things only. Renaming, removing or changing a column
    still needs a migration tool such as Alembic.
    """
    SQLModel.metadata.create_all(engine)
    add_missing_columns()


def _sql_literal(value) -> str | None:
    """A default value written as SQL, or None if it isn't a simple value."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def add_missing_columns() -> None:
    """Add columns that exist in the code above but not yet in the database.

    create_all() only creates whole tables, so when a new field is added to a
    table that already exists (e.g. on a live database), its column must be
    added separately. Each new column gets the field's default value, so
    existing rows stay valid.
    """
    inspector = inspect(engine)
    statements = []
    for mapper in SQLModel._sa_registry.mappers:
        model, table = mapper.class_, mapper.local_table
        if not inspector.has_table(table.name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            column_type = column.type.compile(dialect=engine.dialect)
            sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'
            field = model.model_fields.get(column.name)
            default = _sql_literal(field.default) if field is not None else None
            if default is not None:
                sql += f" DEFAULT {default}"
                if not column.nullable:
                    sql += " NOT NULL"
            statements.append((f"{table.name}.{column.name}", sql))
    if statements:
        with engine.begin() as connection:
            for name, sql in statements:
                connection.execute(text(sql))
                print(f"Database: added the new column {name}")


def get_session():
    """FastAPI dependency: gives each request its own database session."""
    with Session(engine) as session:
        yield session

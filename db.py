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
from sqlalchemy import JSON, Column, LargeBinary
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
    """Create any tables that don't exist yet.

    Note: this never changes tables that already exist. If you add or rename
    columns later, you'll need a migration tool such as Alembic.
    """
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: gives each request its own database session."""
    with Session(engine) as session:
        yield session

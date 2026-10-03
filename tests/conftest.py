"""Shared test setup.

The tests use an in-memory database and fake secrets, so they never touch
local.db or your real .env file.
"""

import os
import sys
from pathlib import Path

# These must be set BEFORE main/db are imported, because db.py reads them
# at import time.
os.environ["HOMEPAGE_TESTING"] = "1"  # don't load the real .env
os.environ["DATABASE_URL"] = "sqlite://"  # in-memory, never local.db
os.environ["DASHBOARD_USER"] = "test-user"
os.environ["DASHBOARD_PASSWORD"] = "test-password"
os.environ["AGENT_EDIT_PASSWORD"] = "test-edit-password"
os.environ["KEY_ENCRYPTION_SECRET"] = "test-encryption-secret"

# Let the tests import main.py, db.py, ... from the folder above.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from db import get_session  # noqa: E402
from main import app  # noqa: E402
from security import csrf_token  # noqa: E402

TEST_AUTH = ("test-user", "test-password")
TEST_EDIT_PASSWORD = "test-edit-password"


@pytest.fixture
def session():
    """A fresh, empty in-memory database for each test."""
    # StaticPool makes every session share one connection; otherwise each
    # connection to "sqlite://" would get its own empty database.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(session):
    """A test client whose routes use the test database."""
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        # Send the CSRF token with every request, like the dashboard pages do.
        # Tests that check CSRF protection remove or change this header.
        test_client.headers["X-CSRF-Token"] = csrf_token()
        yield test_client
    app.dependency_overrides.clear()

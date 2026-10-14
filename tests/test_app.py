"""Automated tests. Run with:  pytest -v"""

import html
import importlib.util
import json
import re
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlmodel import SQLModel, func, select

from conftest import TEST_AUTH, TEST_EDIT_PASSWORD, TEST_LOGIN
from db import (
    Agent,
    AgentFolderLink,
    CategoryNotification,
    Command,
    Event,
    Folder,
    InboxChunk,
    InboxItem,
    LoginSession,
    Output,
    OutputFile,
    TechSetting,
    normalize_database_url,
    utc_now,
)
from security import SESSION_COOKIE, csrf_token, decrypt_api_key, hash_api_key

# --- Helpers ---------------------------------------------------------------


def key_for(name: str) -> str:
    """A made-up API key for a test agent (at least 20 characters)."""
    return f"test-key-for-{name}-0123456789"


def headers_for(name: str) -> dict:
    return {"X-API-Key": key_for(name)}


def add_agent(client, session, name="agent-1", folder_id=None) -> int:
    """Add an agent through the dashboard's Add Agent form and return its id."""
    data = {"name": name, "api_key": key_for(name)}
    if folder_id is not None:
        data["folder_id"] = folder_id
    response = client.post("/dashboard/agents", data=data, auth=TEST_AUTH)
    assert "Agent added" in response.text
    return session.exec(select(Agent).where(Agent.name == name)).one().id


def add_folder(client, session, name="Research") -> int:
    client.post("/dashboard/folders", data={"name": name}, auth=TEST_AUTH)
    return session.exec(select(Folder).where(Folder.name == name)).one().id


def post_event(client, name="agent-1", message="hello", **extra):
    """Send an event the way the agent does, and return the response."""
    return client.post("/api/events", json={"message": message, **extra}, headers=headers_for(name))


def send_output(client, content, category="news", name="agent-1"):
    """Send an output the way output() does (not for files)."""
    return client.post(
        "/api/outputs", json={"category": category, "content": content}, headers=headers_for(name)
    )


def send_file(client, filename, data, content_type, category="files", name="agent-1"):
    return client.post(
        "/api/outputs/file",
        data={"category": category},
        files={"file": (filename, data, content_type)},
        headers=headers_for(name),
    )


def outputs_html(client, agent_id, categories=(), show_all=None, sort=None, order=None, known=None):
    """The output list, as the Filter would request it.

    By default (no categories given) the Filter's "All" box is ticked.
    """
    if show_all is None:
        show_all = not categories
    params = [("c", name) for name in categories]
    if show_all:
        params.append(("all", "true"))
    if sort:
        params.append(("sort", sort))
    if order:
        params.append(("order", order))
    for name in known or []:
        params.append(("known", name))
    return client.get(f"/dashboard/agents/{agent_id}/outputs", params=params, auth=TEST_AUTH).text


def listed_values(page_html: str) -> list[str]:
    """The text outputs shown in a list, top to bottom."""
    return re.findall(r'<p class="break-words whitespace-pre-wrap">([^<]*)</p>', page_html)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64  # enough to look like a PNG
PDF_BYTES = b"%PDF-1.4\n% a tiny test PDF\n"


def send_monitor_pdf(client, filename="summary.pdf", data=PDF_BYTES, label="Daily summary", name="agent-1"):
    return client.post(
        "/api/monitor/file",
        data={"label": label},
        files={"file": (filename, data, "application/pdf")},
        headers=headers_for(name),
    )


def activity(session, agent_id):
    """The agent's Activity log lines as (type, message), oldest first."""
    events = session.exec(select(Event).where(Event.agent_id == agent_id).order_by(Event.id)).all()
    return [(event.type, event.message) for event in events]


def check_in(client, name="agent-1", accepts_messages=None):
    """The connector's regular check-in; returns what the dashboard says (paused...)."""
    return client.post("/api/state", json={"accepts_messages": accepts_messages}, headers=headers_for(name)).json()


def pending_commands(client, name="agent-1"):
    return client.get("/api/commands", headers=headers_for(name)).json()


def grid(client, **params):
    return client.get("/dashboard/grid", params=params, auth=TEST_AUTH).text


# --- Public pages ----------------------------------------------------------


def test_home_page_is_public(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/login?next=%2Ftree%3Fentered"' in response.text and ">Login</a>" in response.text
    assert 'id="tree"' not in response.text  # no tree until signed in
    assert 'action="/login/guest"' in response.text and ">as guest?</button>" in response.text
    assert "Under construction" not in response.text and "Portfolio coming soon" not in response.text


def test_login_as_guest(client, session):
    add_agent(client, session)
    response = client.post("/login/guest", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/tree?entered"  # the tree
    assert "HttpOnly" in response.headers["set-cookie"]
    token = response.cookies[SESSION_COOKIE]
    client.cookies.clear()
    page = client.get("/dashboard", headers={"Cookie": f"{SESSION_COOKIE}={token}"})
    assert page.status_code == 200 and "signed in as guest" in page.text
    assert ">Log out</button>" not in page.text  # no log out on the dashboard any more
    # For now guests have full access, e.g. Start an agent...
    started = client.post("/dashboard/agents/1/command", data={"command": "start"},
                          headers={"Cookie": f"{SESSION_COOKIE}={token}"})
    assert started.status_code == 200
    # ...but not what needs the agent editing password.
    key = client.post("/dashboard/agents/1/key/view", data={"password": "a-guess"},
                      headers={"Cookie": f"{SESSION_COOKIE}={token}"})
    assert key_for("agent-1") not in key.text


# --- Dashboard login -------------------------------------------------------

DASHBOARD_GET_ROUTES = [
    "/dashboard",
    "/dashboard/grid",
    "/dashboard/agents/{id}",
    "/dashboard/agents/{id}/events",
]
DASHBOARD_POST_ROUTES = [
    ("/dashboard/agents", {"name": "x"}),
    ("/dashboard/agents/{id}/command", {"command": "start"}),
    ("/dashboard/agents/{id}/rename", {"name": "new"}),
    ("/dashboard/agents/{id}/tags", {"folder_id": "1"}),
    ("/dashboard/agents/{id}/tags/1/remove", {}),
    ("/dashboard/agents/{id}/delete", {"password": TEST_EDIT_PASSWORD}),
    ("/dashboard/agents/{id}/key/view", {"password": TEST_EDIT_PASSWORD}),
    ("/dashboard/agents/{id}/key/replace", {"password": TEST_EDIT_PASSWORD}),
    ("/dashboard/agents/{id}/outputs/pin", {"category": "news"}),
    ("/dashboard/agents/{id}/outputs/notify", {"category": "news"}),
    ("/dashboard/agents/{id}/monitor", {"url": "https://example.com"}),
    ("/dashboard/agents/{id}/monitor/pin", {}),
    ("/dashboard/folders", {"name": "f"}),
    ("/dashboard/folders/1/rename", {"name": "g"}),
    ("/dashboard/folders/1/delete", {}),
]


@pytest.mark.parametrize("path", DASHBOARD_GET_ROUTES)
def test_dashboard_requires_login(client, session, path):
    agent_id = add_agent(client, session)
    response = client.get(path.format(id=agent_id))
    assert response.status_code == 401
    # No browser login pop-up: that kind of login can't be signed out of.
    assert "WWW-Authenticate" not in response.headers


@pytest.mark.parametrize("path", DASHBOARD_GET_ROUTES)
def test_dashboard_ignores_popup_logins(client, session, path):
    # Even the right username and password in the old pop-up form don't get in:
    # only a browser signed in on the login page does.
    agent_id = add_agent(client, session)
    response = client.get(path.format(id=agent_id), auth=("test-user", "test-password"))
    assert response.status_code == 401


@pytest.mark.parametrize("path", DASHBOARD_GET_ROUTES)
def test_dashboard_allows_correct_login(client, session, path):
    agent_id = add_agent(client, session)
    response = client.get(path.format(id=agent_id), auth=TEST_AUTH)
    assert response.status_code == 200


@pytest.mark.parametrize("path, data", DASHBOARD_POST_ROUTES)
def test_dashboard_actions_require_login(client, session, path, data):
    agent_id = add_agent(client, session)
    add_folder(client, session)
    response = client.post(path.format(id=agent_id), data=data, follow_redirects=False)
    assert response.status_code == 401
    # Nothing was changed: the agent and folder are still there.
    assert session.get(Agent, agent_id) is not None
    assert session.exec(select(Folder)).first() is not None


def test_dashboard_denied_when_password_env_is_empty(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    response = client.post("/login", data={"username": "test-user", "password": ""}, follow_redirects=False)
    assert response.status_code in (401, 422) and SESSION_COOKIE not in response.cookies
    assert client.get("/dashboard", auth=TEST_AUTH).status_code == 401  # earlier sign-ins end too


def test_unknown_agent_and_folder_return_404(client):
    assert client.get("/dashboard/agents/999", auth=TEST_AUTH).status_code == 404
    response = client.post("/dashboard/agents/999/command", data={"command": "start"}, auth=TEST_AUTH)
    assert response.status_code == 404
    assert client.get("/dashboard?folder=999", auth=TEST_AUTH).status_code == 404


# --- API keys --------------------------------------------------------------

API_CALLS = [
    ("post", "/api/events", {"message": "hi"}),
    ("get", "/api/commands", None),
    ("patch", "/api/commands/1", {"status": "done"}),
    ("post", "/api/outputs", {"category": "news", "content": "hi"}),
    ("put", "/api/monitor", {"url": "https://example.com"}),
]


@pytest.mark.parametrize("method, path, body", API_CALLS)
def test_api_requires_key(client, session, method, path, body):
    add_agent(client, session)
    response = client.request(method, path, json=body)
    assert response.status_code == 401


@pytest.mark.parametrize("method, path, body", API_CALLS)
def test_api_rejects_wrong_key(client, session, method, path, body):
    add_agent(client, session)
    response = client.request(method, path, json=body, headers={"X-API-Key": "wrong-key-0123456789"})
    assert response.status_code == 401


@pytest.mark.parametrize("method, path, body", API_CALLS)
def test_api_rejects_empty_key(client, session, method, path, body):
    add_agent(client, session)
    response = client.request(method, path, json=body, headers={"X-API-Key": ""})
    assert response.status_code == 401


@pytest.mark.parametrize("method, path, body", API_CALLS)
def test_api_rejects_every_key_when_there_are_no_agents(client, method, path, body):
    response = client.request(method, path, json=body, headers={"X-API-Key": ""})
    assert response.status_code == 401


def test_key_is_stored_as_fingerprint_and_encrypted_copy(client, session):
    agent_id = add_agent(client, session)
    agent = session.get(Agent, agent_id)
    assert agent.api_key_hash == hash_api_key(key_for("agent-1"))
    assert key_for("agent-1") not in agent.api_key_hash
    assert key_for("agent-1") not in agent.api_key_encrypted  # scrambled, not plain text
    assert decrypt_api_key(agent.api_key_encrypted) == key_for("agent-1")


# --- Adding agents ---------------------------------------------------------


def test_add_agent_with_own_key(client, session):
    agent_id = add_agent(client, session, "helper")
    assert post_event(client, "helper", "hi").status_code == 201
    assert session.get(Agent, agent_id).last_seen is not None


def test_add_agent_generates_key_when_left_blank(client, session):
    response = client.post("/dashboard/agents", data={"name": "auto", "api_key": ""}, auth=TEST_AUTH)
    assert "View key" in response.text
    generated = re.search(r"\b[0-9a-f]{64}\b", response.text).group(0)
    # The generated key works for the API.
    events = client.post("/api/events", json={"message": "hi"}, headers={"X-API-Key": generated})
    assert events.status_code == 201


@pytest.mark.parametrize(
    "data, error",
    [
        ({"name": "  ", "api_key": key_for("a")}, "Name can't be empty"),
        ({"name": "x" * 51, "api_key": key_for("a")}, "at most 50"),
        ({"name": "ok", "api_key": "too-short"}, "at least 20 characters"),
        ({"name": "ok", "api_key": "has spaces in it 0123456789"}, "no spaces"),
    ],
)
def test_add_agent_rejects_bad_input(client, session, data, error):
    response = client.post("/dashboard/agents", data=data, auth=TEST_AUTH)
    assert error in html.unescape(response.text)
    assert session.exec(select(Agent)).first() is None


def test_add_agent_rejects_duplicate_name_and_key(client, session):
    add_agent(client, session, "taken")
    same_name = client.post(
        "/dashboard/agents", data={"name": "taken", "api_key": key_for("other")}, auth=TEST_AUTH
    )
    assert "already exists" in same_name.text
    same_key = client.post(
        "/dashboard/agents", data={"name": "other", "api_key": key_for("taken")}, auth=TEST_AUTH
    )
    assert "already used" in same_key.text
    assert len(session.exec(select(Agent)).all()) == 1


def test_add_agent_inside_folder_tags_it(client, session):
    folder_id = add_folder(client, session, "Writers")
    agent_id = add_agent(client, session, "scribe", folder_id=folder_id)
    assert session.get(AgentFolderLink, (agent_id, folder_id)) is not None


# --- Full round trip -------------------------------------------------------


def test_round_trip_between_agent_and_dashboard(client, session):
    agent_id = add_agent(client, session)

    # 1. The agent reports an event...
    response = post_event(client, message="Agent online", type="status", data={"version": 1})
    assert response.status_code == 201
    assert response.json()["agent_id"] == agent_id

    # ...its card shows it, and so does its activity log.
    assert "Agent online" in grid(client)
    events_html = client.get(f"/dashboard/agents/{agent_id}/events", auth=TEST_AUTH).text
    assert "Agent online" in events_html
    assert "UTC" in events_html

    # 2. The agent says it accepts messages, and the user sends one from its page...
    check_in(client, accepts_messages=True)
    response = client.post(
        f"/dashboard/agents/{agent_id}/command",
        data={"command": "message", "text": "hello agent"},
        auth=TEST_AUTH,
    )
    assert "alert-success" in response.text

    # ...and the agent sees it as pending.
    pending = pending_commands(client)
    assert len(pending) == 1
    assert pending[0]["command"] == "message"
    assert pending[0]["payload"] == {"text": "hello agent"}

    # 3. The agent marks it done, so it is no longer pending.
    command_id = pending[0]["id"]
    response = client.patch(f"/api/commands/{command_id}", json={"status": "done"}, headers=headers_for("agent-1"))
    assert response.json()["status"] == "done"
    assert pending_commands(client) == []


def test_commands_only_go_to_their_own_agent(client, session):
    first_id = add_agent(client, session, "first")
    add_agent(client, session, "second")
    client.post(f"/dashboard/agents/{first_id}/command", data={"command": "start"}, auth=TEST_AUTH)
    assert [c["command"] for c in pending_commands(client, "first")] == ["start"]
    assert pending_commands(client, "second") == []


def test_agent_cannot_update_another_agents_command(client, session):
    first_id = add_agent(client, session, "first")
    add_agent(client, session, "second")
    client.post(f"/dashboard/agents/{first_id}/command", data={"command": "start"}, auth=TEST_AUTH)
    command_id = pending_commands(client, "first")[0]["id"]
    response = client.patch(f"/api/commands/{command_id}", json={"status": "done"}, headers=headers_for("second"))
    assert response.status_code == 404
    assert len(pending_commands(client, "first")) == 1


def test_events_only_show_on_their_own_agent(client, session):
    first_id = add_agent(client, session, "first")
    add_agent(client, session, "second")
    post_event(client, "second", "only for second")
    events_html = client.get(f"/dashboard/agents/{first_id}/events", auth=TEST_AUTH).text
    assert "only for second" not in events_html


def test_pending_commands_are_oldest_first(client, session):
    agent_id = add_agent(client, session)
    for name in ["start", "pause"]:
        client.post(f"/dashboard/agents/{agent_id}/command", data={"command": name}, auth=TEST_AUTH)
    assert [c["command"] for c in pending_commands(client)] == ["start", "pause"]


def test_empty_message_is_not_saved(client, session):
    agent_id = add_agent(client, session)
    check_in(client, accepts_messages=True)
    response = client.post(
        f"/dashboard/agents/{agent_id}/command", data={"command": "message", "text": "  "}, auth=TEST_AUTH
    )
    assert "alert-warning" in response.text
    assert pending_commands(client) == []


def test_events_empty_state(client, session):
    agent_id = add_agent(client, session)
    response = client.get(f"/dashboard/agents/{agent_id}/events", auth=TEST_AUTH)
    assert "No activity yet" in response.text


def test_patch_missing_command_returns_404(client, session):
    add_agent(client, session)
    response = client.patch("/api/commands/9999", json={"status": "done"}, headers=headers_for("agent-1"))
    assert response.status_code == 404


# --- Renaming --------------------------------------------------------------


def test_rename_keeps_the_agent_connected(client, session):
    agent_id = add_agent(client, session, "old-name")
    response = client.post(f"/dashboard/agents/{agent_id}/rename", data={"name": "New Name"}, auth=TEST_AUTH)
    assert "New Name" in response.text
    assert "New Name" in grid(client)
    assert "old-name" not in grid(client)
    # The agent's key still works, and it's still the same agent.
    assert post_event(client, "old-name", "still me").json()["agent_id"] == agent_id


def test_rename_rejects_taken_or_empty_names(client, session):
    add_agent(client, session, "alpha")
    beta_id = add_agent(client, session, "beta")
    taken = client.post(f"/dashboard/agents/{beta_id}/rename", data={"name": "alpha"}, auth=TEST_AUTH)
    assert "already exists" in taken.text
    empty = client.post(f"/dashboard/agents/{beta_id}/rename", data={"name": "   "}, auth=TEST_AUTH)
    assert "can&#39;t be empty" in empty.text
    assert session.get(Agent, beta_id).name == "beta"


# --- Folders and tags ------------------------------------------------------


def test_create_folder_shows_in_sidebar(client, session):
    response = client.post("/dashboard/folders", data={"name": "Research"}, auth=TEST_AUTH)
    folder_id = session.exec(select(Folder)).one().id
    assert response.url.path == "/dashboard"
    assert f"folder={folder_id}" in str(response.url)
    assert "Research" in client.get("/dashboard", auth=TEST_AUTH).text


def test_duplicate_folder_name_shows_error(client, session):
    add_folder(client, session, "Research")
    response = client.post("/dashboard/folders", data={"name": "Research"}, auth=TEST_AUTH)
    assert "already exists" in response.text
    assert len(session.exec(select(Folder)).all()) == 1


def test_folder_grid_shows_only_tagged_agents(client, session):
    folder_id = add_folder(client, session, "Research")
    inside_id = add_agent(client, session, "inside")
    add_agent(client, session, "outside")
    client.post(f"/dashboard/agents/{inside_id}/tags", data={"folder_id": folder_id}, auth=TEST_AUTH)

    folder_grid = grid(client, folder=folder_id)
    assert "inside" in folder_grid
    assert "outside" not in folder_grid
    all_grid = grid(client)
    assert "inside" in all_grid and "outside" in all_grid


def test_add_and_remove_tag(client, session):
    folder_id = add_folder(client, session, "Research")
    agent_id = add_agent(client, session)
    added = client.post(f"/dashboard/agents/{agent_id}/tags", data={"folder_id": folder_id}, auth=TEST_AUTH)
    assert f"/tags/{folder_id}/remove" in added.text
    assert session.get(AgentFolderLink, (agent_id, folder_id)) is not None

    client.post(f"/dashboard/agents/{agent_id}/tags/{folder_id}/remove", auth=TEST_AUTH)
    assert session.get(AgentFolderLink, (agent_id, folder_id)) is None


def test_adding_same_tag_twice_is_harmless(client, session):
    folder_id = add_folder(client, session)
    agent_id = add_agent(client, session)
    for _ in range(2):
        client.post(f"/dashboard/agents/{agent_id}/tags", data={"folder_id": folder_id}, auth=TEST_AUTH)
    assert len(session.exec(select(AgentFolderLink)).all()) == 1


def test_rename_folder(client, session):
    folder_id = add_folder(client, session, "Old")
    client.post(f"/dashboard/folders/{folder_id}/rename", data={"name": "Fresh"}, auth=TEST_AUTH)
    assert session.get(Folder, folder_id).name == "Fresh"


def test_delete_folder_keeps_its_agents(client, session):
    folder_id = add_folder(client, session)
    agent_id = add_agent(client, session, folder_id=folder_id)
    client.post(f"/dashboard/folders/{folder_id}/delete", auth=TEST_AUTH)
    assert session.get(Folder, folder_id) is None
    assert session.get(Agent, agent_id) is not None
    assert session.exec(select(AgentFolderLink)).first() is None


# --- Deleting agents -------------------------------------------------------


def test_delete_agent_needs_the_edit_password(client, session):
    agent_id = add_agent(client, session)
    response = client.post(f"/dashboard/agents/{agent_id}/delete", data={"password": "wrong"}, auth=TEST_AUTH)
    assert "Wrong agent editing password" in response.text
    assert "HX-Redirect" not in response.headers
    assert session.get(Agent, agent_id) is not None


def test_delete_agent_denied_when_edit_password_env_is_empty(client, session, monkeypatch):
    monkeypatch.setenv("AGENT_EDIT_PASSWORD", "")
    agent_id = add_agent(client, session)
    client.post(f"/dashboard/agents/{agent_id}/delete", data={"password": ""}, auth=TEST_AUTH)
    assert session.get(Agent, agent_id) is not None


def test_delete_agent_removes_everything_it_owns(client, session):
    folder_id = add_folder(client, session)
    agent_id = add_agent(client, session, folder_id=folder_id)
    post_event(client, message="something")
    client.post(f"/dashboard/agents/{agent_id}/command", data={"command": "start"}, auth=TEST_AUTH)

    response = client.post(
        f"/dashboard/agents/{agent_id}/delete", data={"password": TEST_EDIT_PASSWORD}, auth=TEST_AUTH
    )
    assert response.headers["HX-Redirect"] == "/dashboard"
    session.expire_all()
    assert session.get(Agent, agent_id) is None
    for model in (Event, Command, AgentFolderLink):
        assert session.exec(select(model)).first() is None
    assert session.get(Folder, folder_id) is not None  # the folder stays
    # The deleted agent's key no longer works.
    assert post_event(client, message="ghost").status_code == 401


def split_agent_page(page_html: str) -> tuple[str, str]:
    """Split an agent page into (the part above the settings pop-up, the pop-up itself)."""
    before, settings = page_html.split('id="agent-settings"', 1)
    return before, settings.split("<!-- Controls", 1)[0]


def test_agent_settings_hold_name_tags_key_and_delete(client, session):
    folder_id = add_folder(client, session, "Research")
    add_folder(client, session, "Writing")
    agent_id = add_agent(client, session, folder_id=folder_id)
    outside, settings = split_agent_page(client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text)

    # Outside: the name, a gear button, and the tags as plain labels.
    assert 'aria-label="Agent settings"' in outside
    assert "Research" in outside
    for control in ["/rename", "/tags", "/key/", "/delete"]:
        assert control not in outside

    # Inside the settings pop-up: everything that changes the agent.
    for control in [
        f"/dashboard/agents/{agent_id}/rename",
        f"/dashboard/agents/{agent_id}/tags/{folder_id}/remove",  # remove a tag
        "+ Add tag",
        "View key",
        "Replace key",
        "Delete agent",
        "Agent editing password",
    ]:
        assert control in settings


def test_agent_settings_start_closed(client, session):
    agent_id = add_agent(client, session)
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert "settingsOpen: false" in page_html
    assert 'id="agent-settings" class="modal "' in page_html  # not modal-open


def test_settings_stay_open_after_rename_or_tag_change(client, session):
    folder_id = add_folder(client, session)
    agent_id = add_agent(client, session)
    responses = [
        client.post(f"/dashboard/agents/{agent_id}/rename", data={"name": "Renamed"}, auth=TEST_AUTH),
        client.post(f"/dashboard/agents/{agent_id}/tags", data={"folder_id": folder_id}, auth=TEST_AUTH),
        client.post(f"/dashboard/agents/{agent_id}/tags/{folder_id}/remove", auth=TEST_AUTH),
    ]
    for response in responses:
        assert "settingsOpen: true" in response.text
        # Also open in the HTML itself: HTMX restores the received class after a swap.
        assert 'id="agent-settings" class="modal modal-open"' in response.text


# --- CSRF protection --------------------------------------------------------


@pytest.mark.parametrize("path, data", DASHBOARD_POST_ROUTES)
def test_dashboard_actions_need_csrf_token(client, session, path, data):
    agent_id = add_agent(client, session)
    add_folder(client, session)
    del client.headers["X-CSRF-Token"]
    response = client.post(path.format(id=agent_id), data=data, auth=TEST_AUTH, follow_redirects=False)
    assert response.status_code == 403
    assert session.get(Agent, agent_id) is not None


@pytest.mark.parametrize("path, data", DASHBOARD_POST_ROUTES)
def test_dashboard_actions_reject_wrong_csrf_token(client, session, path, data):
    agent_id = add_agent(client, session)
    add_folder(client, session)
    client.headers["X-CSRF-Token"] = "not-the-token"
    response = client.post(path.format(id=agent_id), data=data, auth=TEST_AUTH, follow_redirects=False)
    assert response.status_code == 403


def test_csrf_token_in_hidden_form_field_works(client, session):
    del client.headers["X-CSRF-Token"]
    client.post("/dashboard/folders", data={"name": "From form", "csrf_token": csrf_token()}, auth=TEST_AUTH)
    assert session.exec(select(Folder).where(Folder.name == "From form")).first() is not None


def test_csrf_token_only_on_pages_behind_login(client, session):
    agent_id = add_agent(client, session)
    assert csrf_token() not in client.get("/").text
    assert csrf_token() in client.get("/dashboard", auth=TEST_AUTH).text
    assert csrf_token() in client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text


def test_csrf_token_changes_with_the_password(monkeypatch):
    before = csrf_token()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "a-different-password")
    assert csrf_token() != before


# --- Viewing and replacing keys ---------------------------------------------


def test_view_key_needs_the_edit_password(client, session):
    agent_id = add_agent(client, session)
    response = client.post(f"/dashboard/agents/{agent_id}/key/view", data={"password": "wrong"}, auth=TEST_AUTH)
    assert "Wrong agent editing password" in response.text
    assert key_for("agent-1") not in response.text


def test_view_key_shows_the_key(client, session):
    agent_id = add_agent(client, session)
    response = client.post(
        f"/dashboard/agents/{agent_id}/key/view", data={"password": TEST_EDIT_PASSWORD}, auth=TEST_AUTH
    )
    assert key_for("agent-1") in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_view_key_for_agent_without_stored_copy(client, session):
    agent_id = add_agent(client, session)
    agent = session.get(Agent, agent_id)
    agent.api_key_encrypted = None  # like an agent added before keys were encrypted
    session.add(agent)
    session.commit()
    response = client.post(
        f"/dashboard/agents/{agent_id}/key/view", data={"password": TEST_EDIT_PASSWORD}, auth=TEST_AUTH
    )
    assert "Use Replace key" in response.text


def test_view_key_when_encryption_secret_changed(client, session, monkeypatch):
    agent_id = add_agent(client, session)
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", "a-different-secret")
    response = client.post(
        f"/dashboard/agents/{agent_id}/key/view", data={"password": TEST_EDIT_PASSWORD}, auth=TEST_AUTH
    )
    assert "be decrypted" in response.text
    assert key_for("agent-1") not in response.text


def test_replace_key_needs_the_edit_password(client, session):
    agent_id = add_agent(client, session)
    response = client.post(f"/dashboard/agents/{agent_id}/key/replace", data={"password": "wrong"}, auth=TEST_AUTH)
    assert "was not changed" in response.text
    assert post_event(client).status_code == 201  # old key still works


def test_replace_key_generates_new_key_and_old_one_stops_working(client, session):
    agent_id = add_agent(client, session)
    response = client.post(
        f"/dashboard/agents/{agent_id}/key/replace", data={"password": TEST_EDIT_PASSWORD}, auth=TEST_AUTH
    )
    assert "Key replaced" in response.text
    new_key = re.search(r"\b[0-9a-f]{64}\b", response.text).group(0)
    assert post_event(client).status_code == 401  # old key
    new_event = client.post("/api/events", json={"message": "hi"}, headers={"X-API-Key": new_key})
    assert new_event.json()["agent_id"] == agent_id
    # View key now shows the new one.
    viewed = client.post(
        f"/dashboard/agents/{agent_id}/key/view", data={"password": TEST_EDIT_PASSWORD}, auth=TEST_AUTH
    )
    assert new_key in viewed.text


def test_replace_key_with_own_key(client, session):
    agent_id = add_agent(client, session)
    own_key = "my-own-replacement-key-123"
    client.post(
        f"/dashboard/agents/{agent_id}/key/replace",
        data={"password": TEST_EDIT_PASSWORD, "new_key": own_key},
        auth=TEST_AUTH,
    )
    assert client.get("/api/commands", headers={"X-API-Key": own_key}).status_code == 200


def test_replace_key_rejects_bad_or_used_keys(client, session):
    add_agent(client, session, "first")
    second_id = add_agent(client, session, "second")
    for bad_key, error in [("short", "at least 20"), (key_for("first"), "already used")]:
        response = client.post(
            f"/dashboard/agents/{second_id}/key/replace",
            data={"password": TEST_EDIT_PASSWORD, "new_key": bad_key},
            auth=TEST_AUTH,
        )
        assert error in response.text
    assert post_event(client, "second").status_code == 201  # unchanged


def test_keys_need_the_encryption_secret(client, session, monkeypatch):
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", "")
    response = client.post("/dashboard/agents", data={"name": "nope", "api_key": ""}, auth=TEST_AUTH)
    assert "KEY_ENCRYPTION_SECRET" in response.text
    assert session.exec(select(Agent)).first() is None


# --- Sidebar: info and connector downloads ----------------------------------


def test_sidebar_has_fold_button_info_and_connector(client):
    page_html = client.get("/dashboard", auth=TEST_AUTH).text
    assert "Hide folders" in page_html
    assert "How this dashboard works" in page_html
    assert "Implement connector" in page_html
    assert "/dashboard/connector/code" in page_html
    assert "/dashboard/connector/prompt" in page_html


def test_connector_downloads_require_login(client):
    for file_format in ["code", "prompt"]:
        assert client.get(f"/dashboard/connector/{file_format}").status_code == 401


def test_connector_code_download(client, session):
    add_agent(client, session)
    response = client.get("/dashboard/connector/code", auth=TEST_AUTH)
    assert response.status_code == 200
    assert 'filename="dashboard_connector.py"' in response.headers["Content-Disposition"]
    code = response.text
    assert "def report(" in code and "def listen(" in code
    # The address and key are explicit placeholders, clearly marked for the user to replace.
    assert '"REPLACE_WITH_YOUR_DASHBOARD_URL"' in code
    assert '"REPLACE_WITH_YOUR_AGENT_API_KEY"' in code
    assert code.count("REPLACE THIS PLACEHOLDER") == 2
    assert "This file was downloaded from: http://testserver" in code  # a hint only
    assert "{{" not in code
    assert key_for("agent-1") not in code  # never contains a key
    compile(code, "dashboard_connector.py", "exec")  # it's valid Python


def test_connector_prompt_download(client):
    response = client.get("/dashboard/connector/prompt", auth=TEST_AUTH)
    assert 'filename="dashboard_connector_prompt.md"' in response.headers["Content-Disposition"]
    prompt = response.text
    assert "ask me for the following and wait for my answers" in prompt
    assert "dashboard's address" in prompt and "API key" in prompt
    assert "downloaded from `http://testserver`" in prompt  # offered as a suggestion
    for situation in ["127.0.0.1", "onrender.com", "custom domain"]:
        assert situation in prompt
    assert "X-API-Key" in prompt and "DASHBOARD_API_KEY" in prompt
    assert "{{" not in prompt


@pytest.mark.parametrize("forwarded", ["https", "https,http"])
def test_connector_hint_uses_forwarded_https_address(client, forwarded):
    response = client.get(
        "/dashboard/connector/code", auth=TEST_AUTH, headers={"X-Forwarded-Proto": forwarded}
    )
    assert "downloaded from: https://testserver" in response.text


def test_new_agent_shows_both_connection_values(client):
    response = client.post("/dashboard/agents", data={"name": "shown", "api_key": ""}, auth=TEST_AUTH)
    assert "DASHBOARD_URL=http://testserver" in response.text
    assert "DASHBOARD_API_KEY=" in response.text


def test_unknown_connector_format_returns_404(client):
    assert client.get("/dashboard/connector/zip", auth=TEST_AUTH).status_code == 404


# --- Outputs: the API ----------------------------------------------------------


@pytest.mark.parametrize(
    "content, kind, value",
    [
        ("Found 3 articles", "text", "Found 3 articles"),
        (42, "number", "42"),
        (3.5, "number", "3.5"),
        ("https://example.com/story", "link", "https://example.com/story"),
        ({"top": "story"}, "json", '{\n  "top": "story"\n}'),
        ([1, 2], "json", "[\n  1,\n  2\n]"),
        (True, "text", "true"),
        ("javascript:alert(1)", "text", "javascript:alert(1)"),  # never a clickable link
        ("see https://example.com", "text", "see https://example.com"),
    ],
)
def test_output_kinds(client, session, content, kind, value):
    add_agent(client, session)
    response = send_output(client, content)
    assert response.status_code == 201
    assert (response.json()["kind"], response.json()["value"]) == (kind, value)


@pytest.mark.parametrize("category", ["", "   ", "x" * 51])
def test_output_category_must_be_1_to_50_characters(client, session, category):
    add_agent(client, session)
    assert send_output(client, "hi", category=category).status_code == 422


def test_output_content_cannot_be_empty_or_huge(client, session):
    add_agent(client, session)
    assert send_output(client, None).status_code == 422
    assert send_output(client, "x" * 20_001).status_code == 422


def test_output_file_upload_and_download(client, session):
    agent_id = add_agent(client, session)
    response = send_file(client, "chart.png", PNG_BYTES, "image/png")
    assert response.status_code == 201
    output = response.json()
    assert (output["kind"], output["value"]) == ("file", "chart.png")

    download = client.get(f"/dashboard/outputs/{output['id']}/file", auth=TEST_AUTH)
    assert download.content == PNG_BYTES
    assert download.headers["content-type"] == "image/png"
    assert download.headers["Content-Disposition"].startswith("inline")
    assert download.headers["X-Content-Type-Options"] == "nosniff"
    # Images are shown inline on the agent's page.
    assert f'<img src="/dashboard/outputs/{output["id"]}/file"' in outputs_html(client, agent_id)


@pytest.mark.parametrize("filename, content_type", [("report.pdf", "application/pdf"), ("page.svg", "image/svg+xml"), ("page.html", "text/html")])
def test_non_image_files_are_only_downloads(client, session, filename, content_type):
    agent_id = add_agent(client, session)
    output_id = send_file(client, filename, b"<svg onload=alert(1)>", content_type).json()["id"]
    download = client.get(f"/dashboard/outputs/{output_id}/file", auth=TEST_AUTH)
    assert download.headers["Content-Disposition"].startswith("attachment")
    assert download.headers["content-type"] == "application/octet-stream"
    assert "<img" not in outputs_html(client, agent_id)


def test_output_file_size_limit(client, session):
    add_agent(client, session)
    too_big = b"0" * (5 * 1024 * 1024 + 1)
    assert send_file(client, "big.bin", too_big, "application/octet-stream").status_code == 413
    assert session.exec(select(Output)).first() is None


def test_output_file_name_is_cleaned(client, session):
    add_agent(client, session)
    assert send_file(client, "../../etc/passwd", b"x", "text/plain").json()["value"] == "passwd"


def test_output_file_download_needs_login_and_exists(client, session):
    add_agent(client, session)
    output_id = send_file(client, "a.txt", b"x", "text/plain").json()["id"]
    assert client.get(f"/dashboard/outputs/{output_id}/file").status_code == 401
    assert client.get("/dashboard/outputs/999/file", auth=TEST_AUTH).status_code == 404
    text_output_id = send_output(client, "not a file").json()["id"]
    assert client.get(f"/dashboard/outputs/{text_output_id}/file", auth=TEST_AUTH).status_code == 404


def test_output_file_needs_api_key(client, session):
    add_agent(client, session)
    response = client.post(
        "/api/outputs/file", data={"category": "x"}, files={"file": ("a.txt", b"x", "text/plain")}
    )
    assert response.status_code == 401


def test_outputs_only_show_on_their_own_agent(client, session):
    first_id = add_agent(client, session, "first")
    add_agent(client, session, "second")
    send_output(client, "second's result", name="second")
    assert "second&#39;s result" not in outputs_html(client, first_id)


# --- Outputs: the agent page ---------------------------------------------------


def test_outputs_show_nothing_until_chosen(client, session):
    agent_id = add_agent(client, session)
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert 'id="outputs"' in page_html and "No outputs yet" in page_html
    send_output(client, "first result")
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert "first result" not in page_html  # nothing is chosen yet, not even All
    assert "Use <strong>Filter</strong> to choose" in page_html
    assert 'name="all" value="true" class="checkbox checkbox-sm" >' in page_html  # All unticked
    assert outputs_html(client, agent_id, show_all=False).count("first result") == 0


def test_pinned_category_starts_ticked(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "a news item", category="news")
    send_output(client, "a report", category="reports")
    client.post(f"/dashboard/agents/{agent_id}/outputs/pin", data={"category": "news"}, auth=TEST_AUTH)
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert "a news item" in page_html and "a report" not in page_html
    assert 'name="c" value="news" class="checkbox checkbox-sm" checked' in page_html
    assert 'name="c" value="reports" class="checkbox checkbox-sm" >' in page_html


def test_outputs_filter_by_ticked_categories(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "a news item", category="news")
    send_output(client, "a report", category="reports")
    send_output(client, "a chart note", category="charts")

    news_only = outputs_html(client, agent_id, ["news"])
    assert "a news item" in news_only and "a report" not in news_only
    two = outputs_html(client, agent_id, ["news", "reports"])
    assert "a news item" in two and "a report" in two and "a chart note" not in two
    everything = outputs_html(client, agent_id, show_all=True)
    assert all(text in everything for text in ["a news item", "a report", "a chart note"])
    # Unknown categories are ignored.
    assert "a report" not in outputs_html(client, agent_id, ["no-such-category", "news"])


def test_filter_button_summary(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "x", category="news")
    send_output(client, "y", category="reports")
    summary = r'id="outputs-filter-summary"[^>]*>([^<]*)<'
    assert re.search(summary, outputs_html(client, agent_id, show_all=True)).group(1) == "All"
    assert re.search(summary, outputs_html(client, agent_id, ["news"])).group(1) == "news"
    assert re.search(summary, outputs_html(client, agent_id, ["news", "reports"])).group(1) == "2 categories"
    assert re.search(summary, outputs_html(client, agent_id, show_all=False)).group(1) == "Choose..."


@pytest.mark.parametrize(
    "sort, order, expected",
    [
        ("date", "desc", ["banana", "apple", "cherry"]),
        ("date", "asc", ["cherry", "apple", "banana"]),
        ("category", "asc", ["apple", "cherry", "banana"]),   # categories a, b, c
        ("category", "desc", ["banana", "cherry", "apple"]),
        ("content", "asc", ["apple", "banana", "cherry"]),
        ("content", "desc", ["cherry", "banana", "apple"]),
    ],
)
def test_outputs_sorting(client, session, sort, order, expected):
    agent_id = add_agent(client, session)
    send_output(client, "cherry", category="b")  # oldest
    send_output(client, "apple", category="a")
    send_output(client, "banana", category="c")  # newest
    assert listed_values(outputs_html(client, agent_id, sort=sort, order=order)) == expected


def test_unknown_sort_falls_back_to_newest_first(client, session):
    agent_id = add_agent(client, session)
    for number in range(3):
        send_output(client, f"result {number}")
    page_html = outputs_html(client, agent_id, sort="nonsense", order="sideways")
    assert listed_values(page_html) == ["result 2", "result 1", "result 0"]


def test_filter_rows_only_resent_when_categories_change(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "x", category="news")
    # The panel already lists "news": only the list and summary come back.
    unchanged = outputs_html(client, agent_id, ["news"], known=["news"])
    assert 'id="outputs-options"' not in unchanged
    # A new category appeared: fresh rows come back too, keeping what's ticked.
    send_output(client, "y", category="reports")
    changed = outputs_html(client, agent_id, ["news"], known=["news"])
    assert 'id="outputs-options" class="space-y-1" hx-swap-oob="true"' in changed
    assert 'name="c" value="news" class="checkbox checkbox-sm" checked' in changed
    assert 'name="c" value="reports"' in changed


def test_output_links_are_clickable_and_safe(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "https://example.com/a")
    send_output(client, "javascript:alert(1)")
    page_html = outputs_html(client, agent_id)
    assert 'href="https://example.com/a"' in page_html
    assert 'rel="noopener noreferrer"' in page_html
    assert 'href="javascript:' not in page_html


def test_output_content_and_category_are_escaped(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "<script>alert(1)</script>", category="<b>cat</b>")
    page_html = outputs_html(client, agent_id)
    assert "<script>alert(1)" not in page_html and "<b>cat</b>" not in page_html
    assert "&lt;script&gt;" in page_html


def test_pin_only_one_category_and_show_on_card(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "old news", category="news")
    send_output(client, "latest news", category="news")
    send_output(client, 7, category="count")
    pin = f"/dashboard/agents/{agent_id}/outputs/pin"

    client.post(pin, data={"category": "news"}, auth=TEST_AUTH)
    card = grid(client)
    assert "latest news" in card and "old news" not in card

    client.post(pin, data={"category": "count"}, auth=TEST_AUTH)  # moves the pin
    session.expire_all()
    assert session.get(Agent, agent_id).pinned_category == "count"
    assert "latest news" not in grid(client)

    client.post(pin, data={"category": "count"}, auth=TEST_AUTH)  # same one again: unpin
    session.expire_all()
    assert session.get(Agent, agent_id).pinned_category is None


def test_pin_and_bell_keep_what_is_ticked(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "a news item", category="news")
    send_output(client, "a report", category="reports")
    for action in ["pin", "notify"]:
        response = client.post(
            f"/dashboard/agents/{agent_id}/outputs/{action}", data={"category": "news", "c": ["reports"]}, auth=TEST_AUTH
        )
        assert 'name="c" value="reports" class="checkbox checkbox-sm" checked' in response.text
        assert 'name="c" value="news" class="checkbox checkbox-sm" >' in response.text


def test_agent_page_layout(client, session):
    agent_id = add_agent(client, session)
    check_in(client, accepts_messages=True)
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    # Monitor, then Outputs, then Activity.
    assert page_html.index('id="monitor"') < page_html.index('id="outputs"') < page_html.index("Activity</h2>")
    # Controls: a sticky right-hand column on wide screens, a bottom bar on phones.
    assert 'class="hidden lg:sticky lg:top-6 lg:block" aria-label="Controls"' in page_html
    assert "fixed inset-x-0 bottom-0" in page_html
    for control in ['"command": "start"', '"command": "pause"', '"command": "message"']:
        assert page_html.count(control) == 2  # once in each Controls layout
    # Everything in the Filter: its form holds the category ticks and the sort.
    filter_form = page_html.split('id="outputs-filter"', 1)[1].split("</form>", 1)[0]
    assert 'name="sort"' in filter_form and 'name="order"' in filter_form


def test_pinned_category_with_no_outputs_yet(client, session):
    agent_id = add_agent(client, session)
    client.post(f"/dashboard/agents/{agent_id}/outputs/pin", data={"category": "later"}, auth=TEST_AUTH)
    assert "Nothing yet." in grid(client)


def test_notify_toggle_is_saved(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "x", category="news")
    notify = f"/dashboard/agents/{agent_id}/outputs/notify"
    response = client.post(notify, data={"category": "news"}, auth=TEST_AUTH)
    assert session.get(CategoryNotification, (agent_id, "news")) is not None
    assert 'aria-pressed="true"' in response.text
    client.post(notify, data={"category": "news"}, auth=TEST_AUTH)
    session.expire_all()
    assert session.get(CategoryNotification, (agent_id, "news")) is None


def test_deleting_agent_deletes_its_outputs_and_files(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "x")
    send_file(client, "a.png", PNG_BYTES, "image/png")
    client.post(f"/dashboard/agents/{agent_id}/outputs/notify", data={"category": "news"}, auth=TEST_AUTH)
    client.post(f"/dashboard/agents/{agent_id}/delete", data={"password": TEST_EDIT_PASSWORD}, auth=TEST_AUTH)
    session.expire_all()
    for model in (Output, OutputFile, CategoryNotification):
        assert session.exec(select(model)).first() is None


# --- Monitor -------------------------------------------------------------------


def test_agent_sets_and_clears_monitor(client, session):
    agent_id = add_agent(client, session)
    response = client.put(
        "/api/monitor", json={"url": "https://docs.google.com/spreadsheets/d/abc", "label": "Results"}, headers=headers_for("agent-1")
    )
    assert response.json() == {"url": "https://docs.google.com/spreadsheets/d/abc", "label": "Results", "applied": True}
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert 'href="https://docs.google.com/spreadsheets/d/abc"' in page_html
    assert 'iframe src="https://docs.google.com/spreadsheets/d/abc"' in page_html  # "Show here"
    client.put("/api/monitor", json={"url": None}, headers=headers_for("agent-1"))
    assert "No monitor yet" in client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://example.com", "example.com"])
def test_monitor_must_be_http_or_https(client, session, url):
    agent_id = add_agent(client, session)
    assert client.put("/api/monitor", json={"url": url}, headers=headers_for("agent-1")).status_code == 422
    response = client.post(f"/dashboard/agents/{agent_id}/monitor", data={"url": url}, auth=TEST_AUTH)
    assert "must start with http" in response.text
    session.expire_all()
    assert session.get(Agent, agent_id).monitor_url is None


def test_user_sets_monitor_in_settings(client, session):
    agent_id = add_agent(client, session)
    response = client.post(
        f"/dashboard/agents/{agent_id}/monitor", data={"url": "https://grafana.example.com/d/1", "label": "Grafana"}, auth=TEST_AUTH
    )
    assert "settingsOpen: true" in response.text  # settings stay open
    assert 'hx-swap-oob="true"' in response.text  # and the Monitor section updates too
    assert "Grafana" in response.text
    client.post(f"/dashboard/agents/{agent_id}/monitor", data={"url": ""}, auth=TEST_AUTH)  # empty: remove
    session.expire_all()
    assert session.get(Agent, agent_id).monitor_url is None


# --- Monitor PDFs, pinning the monitor, and activity lines ---------------------


def test_monitor_pdf_is_shown_inside_the_page(client, session):
    agent_id = add_agent(client, session)
    response = send_monitor_pdf(client)
    assert response.json() == {"filename": "summary.pdf", "label": "Daily summary", "applied": True}

    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert f'<iframe src="/dashboard/agents/{agent_id}/monitor.pdf?v=' in page_html
    assert "Daily summary" in page_html and "summary.pdf" in page_html

    pdf = client.get(f"/dashboard/agents/{agent_id}/monitor.pdf", auth=TEST_AUTH)
    assert pdf.content == PDF_BYTES
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["Content-Disposition"].startswith("inline")
    assert pdf.headers["X-Content-Type-Options"] == "nosniff"


def test_monitor_pdf_must_be_a_real_pdf(client, session):
    add_agent(client, session)
    # An HTML page pretending to be a PDF is refused.
    assert send_monitor_pdf(client, "fake.pdf", b"<html><script>alert(1)</script>").status_code == 422
    assert send_monitor_pdf(client, data=b"%PDF-" + b"0" * (5 * 1024 * 1024)).status_code == 413


def test_monitor_pdf_needs_key_and_login(client, session):
    agent_id = add_agent(client, session)
    no_key = client.post("/api/monitor/file", files={"file": ("a.pdf", PDF_BYTES, "application/pdf")})
    assert no_key.status_code == 401
    send_monitor_pdf(client)
    assert client.get(f"/dashboard/agents/{agent_id}/monitor.pdf").status_code == 401


def test_only_the_latest_monitor_is_kept(client, session):
    agent_id = add_agent(client, session)
    send_monitor_pdf(client, "monday.pdf")
    send_monitor_pdf(client, "tuesday.pdf")
    session.expire_all()
    agent = session.get(Agent, agent_id)
    assert agent.monitor_filename == "tuesday.pdf"
    assert len(session.exec(select(OutputFile)).all()) == 1  # Monday's PDF was deleted

    client.put("/api/monitor", json={"url": "https://example.com/sheet"}, headers=headers_for("agent-1"))
    session.expire_all()
    agent = session.get(Agent, agent_id)
    assert (agent.monitor_url, agent.monitor_file_id) == ("https://example.com/sheet", None)
    assert session.exec(select(OutputFile)).first() is None
    assert client.get(f"/dashboard/agents/{agent_id}/monitor.pdf", auth=TEST_AUTH).status_code == 404


def test_monitor_section_only_refreshes_when_changed(client, session):
    agent_id = add_agent(client, session)
    send_monitor_pdf(client)
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    version = re.search(r"/monitor\?version=(\w+)", page_html).group(1)
    unchanged = client.get(f"/dashboard/agents/{agent_id}/monitor", params={"version": version}, auth=TEST_AUTH)
    assert unchanged.status_code == 204  # nothing new: the PDF being read isn't reloaded

    send_monitor_pdf(client, "newer.pdf")
    changed = client.get(f"/dashboard/agents/{agent_id}/monitor", params={"version": version}, auth=TEST_AUTH)
    assert changed.status_code == 200 and "newer.pdf" in changed.text


def test_pin_monitor_shares_the_single_pin(client, session):
    agent_id = add_agent(client, session)
    send_monitor_pdf(client)
    send_output(client, "headline", category="news")

    client.post(f"/dashboard/agents/{agent_id}/outputs/pin", data={"category": "news"}, auth=TEST_AUTH)
    pinned = client.post(f"/dashboard/agents/{agent_id}/monitor/pin", auth=TEST_AUTH)
    assert 'aria-pressed="true"' in pinned.text
    session.expire_all()
    agent = session.get(Agent, agent_id)
    assert agent.pinned_monitor is True and agent.pinned_category is None  # the category was unpinned
    card = grid(client)
    pinned_news = '<span class="truncate">news</span>'  # the pinned-category block's heading
    assert "Monitor &middot; Daily summary" in card and "summary.pdf" in card
    assert pinned_news not in card

    # Pinning a category unpins the monitor, and sends its pin button back updated.
    response = client.post(f"/dashboard/agents/{agent_id}/outputs/pin", data={"category": "news"}, auth=TEST_AUTH)
    assert 'id="monitor-pin" hx-swap-oob="true"' in response.text
    session.expire_all()
    assert session.get(Agent, agent_id).pinned_monitor is False
    assert pinned_news in grid(client) and "Monitor &middot;" not in grid(client)

    client.post(f"/dashboard/agents/{agent_id}/monitor/pin", auth=TEST_AUTH)
    client.post(f"/dashboard/agents/{agent_id}/monitor/pin", auth=TEST_AUTH)  # again: unpin
    session.expire_all()
    assert session.get(Agent, agent_id).pinned_monitor is False


def test_pinned_monitor_link_on_card(client, session):
    agent_id = add_agent(client, session)
    client.put("/api/monitor", json={"url": "https://example.com/sheet", "label": "Sheet"}, headers=headers_for("agent-1"))
    client.post(f"/dashboard/agents/{agent_id}/monitor/pin", auth=TEST_AUTH)
    card = grid(client)
    assert "Monitor &middot; Sheet" in card and 'href="https://example.com/sheet"' in card


def test_activity_logs_output_and_monitor_updates(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "Found 3 articles\nmore detail", category="news")
    send_output(client, {"a": 1}, category="stats")
    send_file(client, "chart.png", PNG_BYTES, "image/png", category="charts")
    send_monitor_pdf(client, "daily.pdf")
    client.put("/api/monitor", json={"url": "https://example.com/sheet"}, headers=headers_for("agent-1"))
    client.post(f"/dashboard/agents/{agent_id}/monitor", data={"url": ""}, auth=TEST_AUTH)

    assert activity(session, agent_id) == [
        ("output", 'New output in "news": Found 3 articles'),
        ("output", 'New output in "stats": a list/dict'),
        ("output", 'New output in "charts": file chart.png'),
        ("monitor", "Monitor updated: PDF daily.pdf"),
        ("monitor", "Monitor link set: https://example.com/sheet"),
        ("monitor", "Monitor removed (from the dashboard)"),
    ]
    events_html = client.get(f"/dashboard/agents/{agent_id}/events", auth=TEST_AUTH).text
    assert "badge-secondary" in events_html and "badge-accent" in events_html  # output / monitor colours
    assert "UTC" in events_html


def test_long_output_is_shortened_in_activity(client, session):
    agent_id = add_agent(client, session)
    send_output(client, "x" * 200, category="long")
    message = activity(session, agent_id)[0][1]
    assert message.endswith("\u2026") and len(message) < 120


def test_deleting_agent_deletes_its_monitor_pdf(client, session):
    agent_id = add_agent(client, session)
    send_monitor_pdf(client)
    client.post(f"/dashboard/agents/{agent_id}/delete", data={"password": TEST_EDIT_PASSWORD}, auth=TEST_AUTH)
    session.expire_all()
    assert session.exec(select(OutputFile)).first() is None


# --- Pause and messages --------------------------------------------------------


def test_pause_and_start_switch_the_paused_state(client, session):
    agent_id = add_agent(client, session)
    assert check_in(client)["paused"] is False
    response = client.post(f"/dashboard/agents/{agent_id}/command", data={"command": "pause"}, auth=TEST_AUTH)
    assert check_in(client)["paused"] is True
    assert 'id="run-state" hx-swap-oob="true"' in response.text and "paused" in response.text
    assert ">paused<" in grid(client)  # badge on the grid card
    assert [c["command"] for c in pending_commands(client)] == ["pause"]  # on_command still gets it
    client.post(f"/dashboard/agents/{agent_id}/command", data={"command": "start"}, auth=TEST_AUTH)
    assert check_in(client)["paused"] is False
    assert ">paused<" not in grid(client)


def test_check_in_keeps_agent_online(client, session):
    agent_id = add_agent(client, session)
    check_in(client)
    assert session.get(Agent, agent_id).last_seen is not None
    assert client.post("/api/state", json={}).status_code == 401  # needs the key


def test_messages_are_off_until_the_agent_accepts_them(client, session):
    agent_id = add_agent(client, session)
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert '"command": "message"' not in page_html  # no working message box
    assert "said it accepts messages" in page_html
    refused = client.post(
        f"/dashboard/agents/{agent_id}/command", data={"command": "message", "text": "hi"}, auth=TEST_AUTH
    )
    assert "accept messages." in refused.text and "alert-warning" in refused.text
    assert pending_commands(client) == []

    assert check_in(client, accepts_messages=True)["accepts_messages"] is True
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert page_html.count('"command": "message"') == 2  # the box is back (wide screens and phones)
    client.post(f"/dashboard/agents/{agent_id}/command", data={"command": "message", "text": "hi"}, auth=TEST_AUTH)
    assert pending_commands(client)[0]["payload"] == {"text": "hi"}

    check_in(client, accepts_messages=False)  # e.g. restarted with code that doesn't take messages
    session.expire_all()
    assert session.get(Agent, agent_id).accepts_messages is False


def test_messages_ready_check(client, session):
    agent_id = add_agent(client, session)
    url = f"/dashboard/agents/{agent_id}/messages-ready"
    assert client.get(url, params={"ready": "false"}, auth=TEST_AUTH).status_code == 204  # unchanged
    check_in(client, accepts_messages=True)
    changed = client.get(url, params={"ready": "false"}, auth=TEST_AUTH)
    assert changed.headers.get("HX-Refresh") == "true"  # the page reloads to switch the box on
    assert client.get(url, params={"ready": "true"}).status_code == 401


# --- Agent-defined check-ins ------------------------------------------------------


def seen_ago(session, agent_id, **ago):
    agent = session.get(Agent, agent_id)
    agent.last_seen = utc_now() - timedelta(**ago)
    session.add(agent)
    session.commit()


def test_agent_declares_its_check_in_interval(client, session):
    agent_id = add_agent(client, session)
    reply = client.post("/api/state", json={"check_in_every": 3600}, headers=headers_for("agent-1")).json()
    assert reply["check_in_every"] == 3600
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert "checks in every 1 h" in page_html


@pytest.mark.parametrize("every", [0, -5, 7 * 24 * 3600 + 1, "often"])
def test_check_in_interval_must_be_sensible(client, session, every):
    add_agent(client, session)
    response = client.post("/api/state", json={"check_in_every": every}, headers=headers_for("agent-1"))
    assert response.status_code == 422


@pytest.mark.parametrize(
    "every, seen, online",
    [
        (None, {"seconds": 80}, True),      # default: expected every 60 s (+30 s slack)
        (None, {"seconds": 100}, False),
        (5, {"seconds": 30}, True),         # every 5 s: 5 + 30 s slack
        (5, {"seconds": 40}, False),
        (3600, {"minutes": 80}, True),      # hourly: 1 h + 30 min slack
        (3600, {"minutes": 100}, False),
        (86400, {"hours": 30}, True),       # daily: 1 day + 12 h slack
        (86400, {"hours": 40}, False),
    ],
)
def test_online_follows_the_agents_own_rhythm(client, session, every, seen, online):
    agent_id = add_agent(client, session)
    if every:
        client.post("/api/state", json={"check_in_every": every}, headers=headers_for("agent-1"))
    seen_ago(session, agent_id, **seen)
    page_html = grid(client)
    assert (">online<" in page_html) is online
    assert (">offline<" in page_html) is not online


def test_check_in_interval_wording(client, session):
    from main import human_interval

    assert [human_interval(s) for s in (3, 60, 300, 3600, 5400, 86400, 172800)] == [
        "3 s", "1 min", "5 min", "1 h", "1 h 30 min", "1 day", "2 days"
    ]
    agent_id = add_agent(client, session)
    page_html = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert "checks in every 1 min (default)" in page_html


def test_missing_columns_are_added_to_an_existing_database(tmp_path, monkeypatch):
    """A live database made by an older version gets new columns, keeping its rows."""
    import db
    from sqlmodel import create_engine as make_engine
    from sqlalchemy import inspect as inspect_db, text as sql

    old_engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    SQLModel.metadata.create_all(old_engine)
    with old_engine.begin() as connection:  # pretend it predates two newer columns
        connection.execute(sql('ALTER TABLE agent DROP COLUMN check_in_seconds'))
        connection.execute(sql('ALTER TABLE agent DROP COLUMN paused'))
        connection.execute(sql("INSERT INTO agent (name, api_key_hash, created_at, pinned_monitor, accepts_messages, "
                               "accepts_inbox) VALUES ('old agent', 'hash', '2026-01-01', 0, 0, 0)"))
    monkeypatch.setattr(db, "engine", old_engine)
    db.create_db_and_tables()
    columns = {c["name"] for c in inspect_db(old_engine).get_columns("agent")}
    assert {"check_in_seconds", "paused"} <= columns
    with old_engine.connect() as connection:
        row = connection.execute(sql("SELECT name, paused, check_in_seconds FROM agent")).one()
    assert tuple(row) == ("old agent", 0, None)  # existing row kept, with the defaults
    db.create_db_and_tables()  # running it again changes nothing


# --- The connector: agent-defined check-ins ---------------------------------------


def test_connector_check_in_declares_interval_and_handles_commands(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    dashboard_says(fake_site, paused=False)
    seen = []
    connector._command_handler = seen.append  # as listen(on_command) would set
    assert connector.check_in(every=3600) is True  # e.g. an hourly agent, at the start of a run
    state, commands = fake_site["requests"][:2]
    assert (state["method"], state["path"]) == ("POST", "/api/state")
    assert json_body(state)["check_in_every"] == 3600
    assert (commands["method"], commands["path"]) == ("GET", "/api/commands")  # picks up waiting commands


def test_connector_check_in_without_handlers_only_checks_in(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    dashboard_says(fake_site, paused=True)
    assert connector.check_in() is True and connector.is_paused()
    assert sent_paths(fake_site) == [("POST", "/api/state")]
    assert "check_in_every" not in json_body(fake_site["requests"][0])  # nothing declared yet


def test_connector_start_check_ins_runs_in_background(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    dashboard_says(fake_site, paused=False)
    connector.start_check_ins(every=3600)  # the first check-in happens right away
    for _ in range(50):
        if fake_site["requests"]:
            break
        time.sleep(0.05)
    assert json_body(fake_site["requests"][0])["check_in_every"] == 3600


def test_connector_out_of_range_interval_is_clamped_not_an_error(monkeypatch, fake_site, tmp_path, capsys):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    dashboard_says(fake_site, paused=False)
    assert connector.check_in(every=0) is True
    assert json_body(fake_site["requests"][0])["check_in_every"] == 1
    connector.check_in(every=10**9)
    assert json_body(fake_site["requests"][1])["check_in_every"] == 7 * 24 * 3600
    assert "out of range" in capsys.readouterr().out


# --- Late arrivals (from the connector's offline buffer) ------------------------


def test_output_keeps_its_original_time(client, session):
    agent_id = add_agent(client, session)
    made = (utc_now() - timedelta(hours=2)).isoformat()
    response = client.post(
        "/api/outputs", json={"category": "news", "content": "old news", "created_at": made}, headers=headers_for("agent-1")
    )
    assert response.json()["created_at"].startswith(made[:16])
    # A newer output still comes first; the late one sits at its real time.
    send_output(client, "fresh news")
    assert listed_values(outputs_html(client, agent_id)) == ["fresh news", "old news"]
    late_line = [m for t, m in activity(session, agent_id) if "old news" in m][0]
    assert late_line.endswith("(delivered late)")


def test_future_times_become_now(client, session):
    add_agent(client, session)
    future = (utc_now() + timedelta(days=1)).isoformat()
    response = client.post(
        "/api/outputs", json={"category": "news", "content": "x", "created_at": future}, headers=headers_for("agent-1")
    )
    sent = datetime.fromisoformat(response.json()["created_at"].replace("Z", "+00:00"))
    assert as_aware(sent) <= utc_now()


def test_late_file_output_and_report(client, session):
    agent_id = add_agent(client, session)
    made = (utc_now() - timedelta(hours=1)).isoformat()
    response = client.post(
        "/api/outputs/file",
        data={"category": "files", "created_at": made},
        files={"file": ("a.txt", b"x", "text/plain")},
        headers=headers_for("agent-1"),
    )
    assert response.json()["created_at"].startswith(made[:16])
    event = client.post("/api/events", json={"message": "was offline", "created_at": made}, headers=headers_for("agent-1"))
    assert event.json()["created_at"].startswith(made[:16])
    bad = client.post(
        "/api/outputs/file",
        data={"category": "files", "created_at": "yesterday"},
        files={"file": ("a.txt", b"x", "text/plain")},
        headers=headers_for("agent-1"),
    )
    assert bad.status_code == 422


def test_late_monitor_never_replaces_a_newer_one(client, session):
    agent_id = add_agent(client, session)
    client.put("/api/monitor", json={"url": "https://example.com/new"}, headers=headers_for("agent-1"))
    old = (utc_now() - timedelta(hours=1)).isoformat()
    response = client.put(
        "/api/monitor", json={"url": "https://example.com/old", "created_at": old}, headers=headers_for("agent-1")
    )
    assert response.json()["applied"] is False
    stale_pdf = client.post(
        "/api/monitor/file",
        data={"created_at": old},
        files={"file": ("old.pdf", PDF_BYTES, "application/pdf")},
        headers=headers_for("agent-1"),
    )
    assert stale_pdf.json()["applied"] is False
    session.expire_all()
    assert session.get(Agent, agent_id).monitor_url == "https://example.com/new"
    assert session.exec(select(OutputFile)).first() is None  # the skipped PDF wasn't kept
    assert ("monitor", "Older monitor update skipped (delivered late)") in activity(session, agent_id)


def as_aware(moment):
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# --- The connector itself, against a stand-in website -------------------------
#
# These load connector/dashboard_connector.py exactly as a user would, and point
# it at a tiny fake website on a random local port. That shows it works with any
# address (local, Render, another host), not just this app's.

CONNECTOR_FILE = Path(__file__).resolve().parent.parent / "connector" / "dashboard_connector.py"


def load_connector(monkeypatch, url=None, key=None, buffer_dir=None):
    """Import a fresh copy of the connector with these environment variables.

    Each copy gets its own empty offline-buffer folder, unless one is given.
    """
    monkeypatch.setenv("DASHBOARD_BUFFER_DIR", str(buffer_dir or tempfile.mkdtemp()))
    for name, value in [("DASHBOARD_URL", url), ("DASHBOARD_API_KEY", key)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location("dashboard_connector_under_test", CONNECTOR_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # No background retries either: tests call flush() themselves, so the
    # requests they check aren't racing a retry thread.
    module._sender_started = True
    return module


@pytest.fixture
def fake_site():
    """A stand-in website that records requests and answers with a chosen status."""
    site = {"requests": [], "status": 201, "headers": {}, "body": b"{}"}

    class Handler(BaseHTTPRequestHandler):
        def _answer(self):
            length = int(self.headers.get("Content-Length") or 0)
            site["requests"].append(
                {"method": self.command, "path": self.path,
                 "key": self.headers.get("X-API-Key"), "body": self.rfile.read(length)}
            )
            self.send_response(site["status"])
            for name, value in site["headers"].items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(site["body"])))
            self.end_headers()
            self.wfile.write(site["body"])

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _answer

        def log_message(self, *args):  # keep test output quiet
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site["url"] = f"http://127.0.0.1:{server.server_port}"
    yield site
    server.shutdown()


def test_connector_reports_to_any_address(monkeypatch, fake_site):
    # A trailing "/dashboard/" (copied from the browser) is tidied away.
    connector = load_connector(monkeypatch, fake_site["url"] + "/dashboard/", "agent-key-0123456789")
    assert connector.report("hello", "status", {"url": "https://example.com"}) is True
    sent = fake_site["requests"][0]
    assert (sent["method"], sent["path"], sent["key"]) == ("POST", "/api/events", "agent-key-0123456789")
    assert b'"message": "hello"' in sent["body"]


def test_connector_handles_commands_and_marks_them_done(monkeypatch, fake_site):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    fake_site["status"] = 200
    fake_site["body"] = b'[{"id": 7, "command": "start", "payload": null}]'
    handled = []
    connector._check_commands(handled.append)
    assert [c["id"] for c in handled] == [7]
    assert ("PATCH", "/api/commands/7") in [(r["method"], r["path"]) for r in fake_site["requests"]]


def test_connector_with_placeholders_does_nothing(monkeypatch, fake_site, capsys):
    connector = load_connector(monkeypatch)  # no environment variables, placeholders untouched
    assert connector.PROBLEM is not None
    assert "Set DASHBOARD_URL" in capsys.readouterr().out
    assert connector.report("hi") is False
    assert connector.listen(lambda c: None) is None
    assert fake_site["requests"] == []


@pytest.mark.parametrize(
    "url, key, problem",
    [
        ("your-site.onrender.com", "k" * 20, "must start with http"),
        ("https://your-site.onrender.com", "", "Set DASHBOARD_API_KEY"),
        ("https://your-site.onrender.com", "REPLACE_WITH_YOUR_AGENT_API_KEY", "Set DASHBOARD_API_KEY"),
    ],
)
def test_connector_explains_bad_settings(monkeypatch, url, key, problem):
    assert problem in load_connector(monkeypatch, url, key).PROBLEM


def test_connector_warns_about_plain_http_on_remote_hosts(monkeypatch, capsys):
    load_connector(monkeypatch, "http://dashboard.example.com", "k" * 20)
    assert "unencrypted" in capsys.readouterr().out
    load_connector(monkeypatch, "http://127.0.0.1:8000", "k" * 20)
    assert "unencrypted" not in capsys.readouterr().out


def test_connector_does_not_follow_redirects(monkeypatch, fake_site, capsys):
    # e.g. Render redirecting http:// to https://; following it would turn the POST into a GET.
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    fake_site["status"] = 308
    fake_site["headers"] = {"Location": "https://dashboard.example.com/api/events"}
    assert connector.report("hi") is False
    assert len(fake_site["requests"]) == 1  # not followed
    output = capsys.readouterr().out
    assert "redirected to https://dashboard.example.com" in output
    assert "Set DASHBOARD_URL" in output


def test_connector_explains_wrong_key(monkeypatch, fake_site, capsys):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    fake_site["status"] = 401
    assert connector.report("hi") is False
    assert "Check DASHBOARD_API_KEY" in capsys.readouterr().out


def test_connector_output_sends_content_and_category(monkeypatch, fake_site):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    assert connector.output(42, "articles found") is True
    assert connector.output({"day": date(2026, 10, 3)}, "summary") is True  # dates become text
    first, second = fake_site["requests"]
    assert (first["method"], first["path"]) == ("POST", "/api/outputs")
    first_body, second_body = json_body(first), json_body(second)
    assert first_body.pop("created_at") and second_body.pop("created_at")  # when it was made
    assert first_body == {"category": "articles found", "content": 42}
    assert second_body == {"category": "summary", "content": {"day": "2026-10-03"}}


def test_connector_output_sends_files(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    report_file = tmp_path / "today.pdf"
    report_file.write_bytes(b"%PDF-1.4 hello")
    assert connector.output(report_file, "reports") is True
    sent = fake_site["requests"][0]
    assert sent["path"] == "/api/outputs/file"
    assert b'name="category"' in sent["body"] and b"reports" in sent["body"]
    assert b'filename="today.pdf"' in sent["body"] and b"%PDF-1.4 hello" in sent["body"]
    assert b"application/pdf" in sent["body"]


def test_connector_output_skips_oversize_and_missing_files(monkeypatch, fake_site, tmp_path, capsys):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    big = tmp_path / "big.bin"
    big.write_bytes(b"0" * (5 * 1024 * 1024 + 1))
    assert connector.output(big, "files") is False
    assert connector.output(tmp_path / "missing.pdf", "files") is False  # no crash
    assert fake_site["requests"] == []
    output = capsys.readouterr().out
    assert "over 5 MB" in output and "FileNotFoundError" in output


def test_connector_set_monitor(monkeypatch, fake_site):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    fake_site["status"] = 200
    assert connector.set_monitor("https://docs.google.com/x", "Sheet") is True
    sent = fake_site["requests"][0]
    assert (sent["method"], sent["path"]) == ("PUT", "/api/monitor")
    body = json_body(sent)
    assert body.pop("created_at")
    assert body == {"url": "https://docs.google.com/x", "label": "Sheet"}


def test_connector_set_monitor_with_pdf(monkeypatch, fake_site, tmp_path, capsys):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    fake_site["status"] = 200
    summary = tmp_path / "daily_summary.pdf"
    summary.write_bytes(PDF_BYTES)
    assert connector.set_monitor(summary, "Daily summary") is True
    sent = fake_site["requests"][0]
    assert (sent["method"], sent["path"]) == ("POST", "/api/monitor/file")
    assert b'filename="daily_summary.pdf"' in sent["body"] and b"Daily summary" in sent["body"]

    not_pdf = tmp_path / "notes.txt"
    not_pdf.write_text("hello")
    assert connector.set_monitor(not_pdf) is False  # refused before sending
    assert len(fake_site["requests"]) == 1
    assert "isn't a PDF" in capsys.readouterr().out


# --- The connector's offline buffer ---------------------------------------------


def sent_paths(site):
    return [(r["method"], r["path"]) for r in site["requests"]]


def test_buffer_saves_and_later_sends_with_original_time(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    fake_site["status"] = 503  # the dashboard is having a problem
    assert connector.output("made while down", "news") is False
    assert connector.pending() == 1
    made_at = json_body(fake_site["requests"][0])["created_at"]

    fake_site["status"] = 201  # back again
    fake_site["requests"].clear()
    assert connector.flush() == 0
    resent = json_body(fake_site["requests"][0])
    assert resent["content"] == "made while down"
    assert resent["created_at"] == made_at  # the original time, not the resend time


def test_buffer_keeps_order(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    fake_site["status"] = 503
    connector.output("first", "news")
    connector.report("second")
    fake_site["status"] = 201
    # Reachable again, but older items are waiting: the new one queues behind them.
    assert connector.output("third", "news") is False
    fake_site["requests"].clear()
    connector.flush()
    sent = [json_body(r).get("content") or json_body(r).get("message") for r in fake_site["requests"]]
    assert sent == ["first", "second", "third"]
    assert connector.pending() == 0


def test_buffer_survives_restart(monkeypatch, fake_site, tmp_path):
    first_run = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    fake_site["status"] = 503
    first_run.output("from before the restart", "news")
    fake_site["status"] = 201
    fake_site["requests"].clear()
    second_run = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    assert second_run.pending() == 1
    second_run.flush()
    assert json_body(fake_site["requests"][0])["content"] == "from before the restart"


def test_buffer_when_dashboard_unreachable(monkeypatch, tmp_path, capsys):
    connector = load_connector(monkeypatch, "http://127.0.0.1:9", "agent-key-0123456789", tmp_path)
    assert connector.output("nobody home", "news") is False
    assert connector.pending() == 1
    assert "offline buffer" in capsys.readouterr().out


def test_buffer_copies_files(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path / "buffer")
    report_file = tmp_path / "report.pdf"
    report_file.write_bytes(b"%PDF-1.4 saved for later")
    fake_site["status"] = 503
    connector.output(report_file, "reports")
    report_file.unlink()  # the original is gone; the buffer has its own copy
    fake_site["status"] = 201
    fake_site["requests"].clear()
    connector.flush()
    body = fake_site["requests"][0]["body"]
    assert b"%PDF-1.4 saved for later" in body and b'name="created_at"' in body
    assert not list((tmp_path / "buffer" / "files").iterdir())  # cleaned up after sending


def test_buffer_keeps_only_latest_monitor(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    fake_site["status"] = 503
    connector.set_monitor("https://example.com/old")
    connector.set_monitor("https://example.com/new")
    assert connector.pending() == 1
    fake_site["status"] = 200
    fake_site["requests"].clear()
    connector.flush()
    assert [json_body(r)["url"] for r in fake_site["requests"]] == ["https://example.com/new"]


def test_mistakes_are_not_buffered(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    for status in (401, 404, 413, 422):  # retrying wouldn't help
        fake_site["status"] = status
        assert connector.output("x", "news") is False
    assert connector.pending() == 0


def test_buffer_has_a_size_limit(monkeypatch, fake_site, tmp_path, capsys):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    monkeypatch.setattr(connector, "BUFFER_MAX_ITEMS", 2)
    fake_site["status"] = 503
    for number in range(3):
        connector.output(f"item {number}", "news")
    assert connector.pending() == 2
    assert "dropped the 1 oldest" in capsys.readouterr().out
    fake_site["status"] = 201
    fake_site["requests"].clear()
    connector.flush()
    assert [json_body(r)["content"] for r in fake_site["requests"]] == ["item 1", "item 2"]


# --- The connector: Start/Pause and messages ------------------------------------


def dashboard_says(site, paused):
    """Make the stand-in site answer the next check-in with this pause state."""
    site["status"], site["body"] = 200, json.dumps({"paused": paused}).encode()


def test_connector_holds_outputs_while_paused(monkeypatch, fake_site, tmp_path, capsys):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    dashboard_says(fake_site, paused=True)
    assert connector._check_in() and connector.is_paused()
    fake_site["requests"].clear()

    assert connector.output("made while paused", "news") is False
    assert connector.set_monitor("https://example.com/sheet") is False
    assert fake_site["requests"] == []  # nothing sent: held
    assert connector.pending() == 2
    assert connector.flush() == 2  # flush() doesn't send held items while paused
    assert "holding outputs and monitor updates until Start" in capsys.readouterr().out

    fake_site["status"], fake_site["body"] = 201, b"{}"
    assert connector.report("still visible while paused") is True  # reports go through
    assert sent_paths(fake_site) == [("POST", "/api/events")]

    dashboard_says(fake_site, paused=False)
    connector._check_in()  # Start pressed
    fake_site["status"], fake_site["body"] = 201, b"{}"
    fake_site["requests"].clear()
    assert connector.flush() == 0
    assert sent_paths(fake_site) == [("POST", "/api/outputs"), ("PUT", "/api/monitor")]
    assert json_body(fake_site["requests"][0])["content"] == "made while paused"


def test_connector_wait_if_paused(monkeypatch, fake_site, tmp_path, capsys):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    dashboard_says(fake_site, paused=False)
    assert connector.wait_if_paused() is False  # running: carries straight on

    dashboard_says(fake_site, paused=True)
    connector._check_in()
    # Press Start a moment later, from another thread.
    threading.Timer(0.3, lambda: dashboard_says(fake_site, paused=False)).start()
    assert connector.wait_if_paused(check_every=0.1) is True
    assert not connector.is_paused()
    assert "waiting for Start" in capsys.readouterr().out


def test_connector_start_pause_commands_update_state(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    seen = []
    connector._command_handler = seen.append
    fake_site["status"] = 200
    fake_site["body"] = b'[{"id": 1, "command": "pause", "payload": null}]'
    connector._check_commands()
    assert connector.is_paused() and [c["command"] for c in seen] == ["pause"]
    fake_site["body"] = b'[{"id": 2, "command": "start", "payload": null}]'
    connector._check_commands()
    assert not connector.is_paused()


def test_connector_accept_messages(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    dashboard_says(fake_site, paused=False)
    received, other_commands = [], []
    connector.accept_messages(received.append)
    check_in = fake_site["requests"][0]
    assert (check_in["method"], check_in["path"]) == ("POST", "/api/state")
    assert json_body(check_in) == {"accepts_messages": True, "accepts_inbox": False}  # the "OK, I take messages" signal

    connector._command_handler = other_commands.append
    fake_site["body"] = b'[{"id": 3, "command": "message", "payload": {"text": "focus on earnings"}}]'
    connector._check_commands()
    assert received == ["focus on earnings"]  # straight to the message handler, as text
    assert other_commands == []


def test_messages_go_to_on_command_without_accept_messages(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    seen = []
    connector._command_handler = seen.append
    fake_site["status"] = 200
    fake_site["body"] = b'[{"id": 4, "command": "message", "payload": {"text": "hi"}}]'
    connector._check_commands()
    assert seen[0]["payload"] == {"text": "hi"}


def json_body(request: dict):
    return json.loads(request["body"])


def test_connector_survives_unreachable_dashboard(monkeypatch, capsys):
    connector = load_connector(monkeypatch, "http://127.0.0.1:9", "agent-key-0123456789")
    assert connector.report("hi") is False  # port 9: nothing listening
    connector._check_commands(lambda c: None)
    assert "can't reach" in capsys.readouterr().out


# --- Grid and pages --------------------------------------------------------


def test_empty_grid_shows_only_add_agent_card(client):
    page_html = grid(client)
    assert "Add Agent" in page_html
    assert "No agents yet" in page_html


def test_grid_pages_hold_nine_cells_including_add_card(client, session):
    for number in range(1, 10):  # 9 agents + the Add Agent card = 10 cells -> 2 pages
        add_agent(client, session, f"agent-{number:02d}")

    page_one = grid(client)
    assert "agent-09" in page_one
    assert "open-add-agent" not in page_one  # no room left on page 1
    assert "page 1 of 2" in page_one
    assert 'href="/dashboard?page=2"' in page_one

    page_two = grid(client, page=2)
    assert "agent-01" not in page_two
    assert "open-add-agent" in page_two


def test_no_page_buttons_when_everything_fits(client, session):
    for number in range(1, 9):  # 8 agents + Add Agent card = 9 cells
        add_agent(client, session, f"agent-{number}")
    page_html = grid(client)
    assert "dashboard?page=2" not in page_html
    assert "open-add-agent" in page_html


def test_folder_page_buttons_keep_the_folder(client, session):
    folder_id = add_folder(client, session)
    for number in range(1, 10):
        add_agent(client, session, f"agent-{number}", folder_id=folder_id)
    assert f'href="/dashboard?page=2&amp;folder={folder_id}"' in grid(client, folder=folder_id)


def test_out_of_range_page_shows_last_page(client, session):
    add_agent(client, session)
    response = client.get("/dashboard?page=50", auth=TEST_AUTH)
    assert response.status_code == 200
    assert "agent-1" in response.text


def test_grid_cell_has_only_start_and_pause(client, session):
    add_agent(client, session)
    page_html = grid(client)
    assert '"command": "start"' in page_html
    assert '"command": "pause"' in page_html
    assert '"command": "message"' not in page_html


def test_online_offline_and_never_connected_badges(client, session):
    add_agent(client, session, "fresh")
    add_agent(client, session, "stale")
    add_agent(client, session, "brand-new")
    post_event(client, "fresh")
    post_event(client, "stale")
    stale = session.exec(select(Agent).where(Agent.name == "stale")).one()
    stale.last_seen = utc_now() - timedelta(minutes=5)
    session.add(stale)
    session.commit()

    page_html = grid(client)
    assert page_html.count(">online<") == 1
    assert page_html.count(">offline<") == 1
    assert page_html.count(">never connected<") == 1


# --- HTML escaping ---------------------------------------------------------


def test_event_message_html_is_escaped(client, session):
    agent_id = add_agent(client, session)
    post_event(client, message="<script>alert('x')</script>")
    for path in [f"/dashboard/agents/{agent_id}/events", "/dashboard/grid"]:
        page_html = client.get(path, auth=TEST_AUTH).text
        assert "<script>alert" not in page_html
        assert "&lt;script&gt;" in page_html


def test_agent_and_folder_names_are_escaped(client, session):
    folder_id = add_folder(client, session, "<i>folder</i>")
    agent_id = add_agent(client, session, "<b>bot</b>", folder_id=folder_id)
    for path in ["/dashboard", f"/dashboard/agents/{agent_id}", f"/dashboard?folder={folder_id}"]:
        page_html = client.get(path, auth=TEST_AUTH).text
        assert "<b>bot</b>" not in page_html and "<i>folder</i>" not in page_html


def test_command_alert_html_is_escaped(client, session):
    agent_id = add_agent(client, session)
    response = client.post(f"/dashboard/agents/{agent_id}/command", data={"command": "<b>x</b>"}, auth=TEST_AUTH)
    assert "<b>" not in response.text
    assert "&lt;b&gt;" in response.text


# --- DATABASE_URL conversion -----------------------------------------------


@pytest.mark.parametrize(
    "given, expected",
    [
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgresql://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///./local.db", "sqlite:///./local.db"),
    ],
)
def test_database_url_conversion(given, expected):
    assert normalize_database_url(given) == expected


# --- Reading (any agent's data) and deleting (own data only) ---------------


def two_agents_with_data(client, session):
    """agent-1 and agent-2, each with some outputs; agent-2 also has a file and a PDF monitor."""
    ids = add_agent(client, session, "agent-1"), add_agent(client, session, "agent-2")
    send_output(client, "first news", "news", name="agent-1")
    send_output(client, 42, "counts", name="agent-2")
    send_output(client, {"top": "story"}, "stats", name="agent-2")
    send_file(client, "notes.txt", b"hello file", "text/plain", category="files", name="agent-2")
    client.post("/api/monitor/file", files={"file": ("report.pdf", b"%PDF-1.4 test", "application/pdf")},
                headers=headers_for("agent-2"))
    return ids


def test_agents_can_list_every_agent(client, session):
    one, two = two_agents_with_data(client, session)
    response = client.get("/api/agents", headers=headers_for("agent-1"))
    assert response.status_code == 200
    agents = response.json()
    assert [(a["id"], a["name"], a["you"]) for a in agents] == [(one, "agent-1", True), (two, "agent-2", False)]
    assert agents[1]["monitor"]["kind"] == "pdf"
    # Never a key, in any form.
    assert "api_key" not in response.text and key_for("agent-2") not in response.text


def test_agent_can_read_another_agents_outputs(client, session):
    one, two = two_agents_with_data(client, session)
    outputs = client.get(f"/api/agents/{two}/outputs", headers=headers_for("agent-1")).json()
    by_category = {o["category"]: o for o in outputs}
    assert by_category["counts"]["content"] == 42  # a number again, not text
    assert by_category["stats"]["content"] == {"top": "story"}
    file_info = by_category["files"]["file"]
    assert (file_info["filename"], file_info["size"]) == ("notes.txt", 10)
    # ...and the file itself.
    file = client.get(file_info["url"], headers=headers_for("agent-1"))
    assert file.content == b"hello file" and "attachment" in file.headers["content-disposition"]


def test_read_outputs_filters_and_pages(client, session):
    one, two = two_agents_with_data(client, session)
    picked = client.get(f"/api/agents/{two}/outputs?category=counts&category=stats", headers=headers_for("agent-1"))
    assert sorted(o["category"] for o in picked.json()) == ["counts", "stats"]
    newest = client.get(f"/api/agents/{two}/outputs?limit=1", headers=headers_for("agent-1")).json()
    assert [o["category"] for o in newest] == ["files"]
    future = (utc_now() + timedelta(hours=1)).isoformat()
    assert client.get(f"/api/agents/{two}/outputs", params={"since": future},
                      headers=headers_for("agent-1")).json() == []
    assert client.get(f"/api/agents/{two}/outputs?since=yesterday", headers=headers_for("agent-1")).status_code == 422
    assert client.get(f"/api/agents/{two}/outputs?limit=501", headers=headers_for("agent-1")).status_code == 422


def test_agents_are_found_by_me_id_or_name(client, session):
    one, two = two_agents_with_data(client, session)
    me = client.get("/api/agents/me", headers=headers_for("agent-1")).json()
    assert (me["id"], me["you"]) == (one, True)
    by_name = client.get("/api/agents/agent-2", headers=headers_for("agent-1")).json()
    assert by_name["id"] == two
    assert {c["name"]: c["count"] for c in by_name["categories"]} == {"counts": 1, "files": 1, "stats": 1}
    assert client.get("/api/agents/nobody", headers=headers_for("agent-1")).status_code == 404


def test_agent_can_read_another_agents_activity_and_monitor(client, session):
    one, two = two_agents_with_data(client, session)
    post_event(client, "agent-2", "something broke", type="error")
    errors = client.get(f"/api/agents/{two}/events?type=error", headers=headers_for("agent-1")).json()
    assert [e["message"] for e in errors] == ["something broke"]
    monitor = client.get(f"/api/agents/{two}/monitor", headers=headers_for("agent-1")).json()["monitor"]
    assert monitor["filename"] == "report.pdf"
    pdf = client.get(monitor["file_url"], headers=headers_for("agent-1"))
    assert pdf.content == b"%PDF-1.4 test"
    assert client.get(f"/api/agents/{one}/monitor.pdf", headers=headers_for("agent-2")).status_code == 404


def test_reads_never_show_commands(client, session):
    one, two = two_agents_with_data(client, session)
    session.add(Command(agent_id=two, command="message", payload={"text": "secret plan"}))
    session.commit()
    for path in (f"/api/agents/{two}", f"/api/agents/{two}/events", f"/api/agents/{two}/outputs", "/api/agents"):
        assert "secret plan" not in client.get(path, headers=headers_for("agent-1")).text


def test_reads_and_deletes_need_a_valid_key(client, session):
    one, two = two_agents_with_data(client, session)
    for method, path in [("GET", "/api/agents"), ("GET", f"/api/agents/{two}/outputs"),
                         ("GET", "/api/outputs/1/file"), ("DELETE", "/api/outputs/1"),
                         ("DELETE", "/api/outputs?all=true"), ("DELETE", "/api/events?all=true"),
                         ("DELETE", "/api/monitor")]:
        assert client.request(method, path).status_code == 401
        assert client.request(method, path, headers={"X-API-Key": "wrong-key-0123456789"}).status_code == 401


def test_agent_can_delete_its_own_output(client, session):
    one, two = two_agents_with_data(client, session)
    file_output = session.exec(select(Output).where(Output.kind == "file")).one()
    file_id = file_output.file_id
    response = client.delete(f"/api/outputs/{file_output.id}", headers=headers_for("agent-2"))
    assert response.json() == {"deleted": 1}
    session.expire_all()
    assert session.get(Output, file_output.id) is None
    assert session.get(OutputFile, file_id) is None  # its file went too
    note = session.exec(select(Event).where(Event.agent_id == two, Event.type == "delete")).one()
    assert note.message == 'Deleted 1 output in "files"'


def test_agent_cannot_delete_another_agents_data(client, session):
    one, two = two_agents_with_data(client, session)
    theirs = session.exec(select(Output).where(Output.agent_id == two)).first()
    assert client.delete(f"/api/outputs/{theirs.id}", headers=headers_for("agent-1")).status_code == 403
    event_id = post_event(client, "agent-2", "mine").json()["id"]
    assert client.delete(f"/api/events/{event_id}", headers=headers_for("agent-1")).status_code == 403
    # Bulk deletes only ever touch the caller's own data.
    assert client.delete("/api/outputs?all=true", headers=headers_for("agent-1")).json() == {"deleted": 1}
    assert client.delete("/api/events?all=true", headers=headers_for("agent-1")).status_code == 200
    session.expire_all()
    assert len(session.exec(select(Output).where(Output.agent_id == two)).all()) == 3
    assert session.get(Event, event_id) is not None
    assert session.get(Agent, two).monitor_file_id is not None
    assert client.delete("/api/outputs/99999", headers=headers_for("agent-1")).status_code == 404


def test_bulk_output_delete_needs_a_filter(client, session):
    one, two = two_agents_with_data(client, session)
    assert client.delete("/api/outputs", headers=headers_for("agent-2")).status_code == 422
    assert client.delete("/api/outputs?category=counts", headers=headers_for("agent-2")).json() == {"deleted": 1}
    past = (utc_now() - timedelta(hours=1)).isoformat()
    assert client.delete("/api/outputs", params={"before": past}, headers=headers_for("agent-2")).json() == {"deleted": 0}
    assert client.delete("/api/outputs?all=true", headers=headers_for("agent-2")).json() == {"deleted": 2}
    session.expire_all()
    assert session.exec(select(Output).where(Output.agent_id == two)).all() == []
    assert len(session.exec(select(OutputFile)).all()) == 1  # only the monitor PDF is left


def test_agent_can_clear_its_own_activity(client, session):
    one, two = two_agents_with_data(client, session)
    old = Event(agent_id=one, message="old line", created_at=utc_now() - timedelta(days=2))
    session.add(old)
    session.commit()
    assert client.delete("/api/events", headers=headers_for("agent-1")).status_code == 422
    yesterday = (utc_now() - timedelta(days=1)).isoformat()
    assert client.delete("/api/events", params={"before": yesterday}, headers=headers_for("agent-1")).json() == {"deleted": 1}
    client.delete("/api/events?all=true", headers=headers_for("agent-1"))
    left = client.get("/api/agents/me/events", headers=headers_for("agent-1")).json()
    assert [e["message"] for e in left] == ["Deleted 2 activity lines"]  # the output line and the first delete note


def test_agent_can_remove_its_own_monitor(client, session):
    one, two = two_agents_with_data(client, session)
    assert client.delete("/api/monitor", headers=headers_for("agent-2")).json() == {"deleted": 1}
    assert client.delete("/api/monitor", headers=headers_for("agent-2")).json() == {"deleted": 0}
    session.expire_all()
    assert session.get(Agent, two).monitor_file_id is None
    assert session.exec(select(OutputFile).where(OutputFile.content_type == "application/pdf")).all() == []


def test_delete_lines_show_on_the_agent_page(client, session):
    one, two = two_agents_with_data(client, session)
    client.delete("/api/outputs?category=stats", headers=headers_for("agent-2"))
    page = client.get(f"/dashboard/agents/{two}/events", auth=TEST_AUTH).text
    assert "badge-warning" in page and "Deleted 1 output in &#34;stats&#34;" in page


def test_connector_reads_with_filters(monkeypatch, fake_site):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    fake_site["status"], fake_site["body"] = 200, b'[{"id": 1, "content": 42}]'
    since = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)
    assert connector.read_outputs("agent two", category=["a", "b"], since=since, limit=5) == [{"id": 1, "content": 42}]
    sent = fake_site["requests"][-1]
    assert sent["method"] == "GET"
    assert sent["path"].startswith("/api/agents/agent%20two/outputs?")
    assert "category=a&category=b" in sent["path"] and "limit=5" in sent["path"]
    assert "since=2026-10-03T08%3A00%3A00%2B00%3A00" in sent["path"]


def test_connector_downloads_files(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    fake_site["status"], fake_site["body"] = 200, b"file bytes"
    target = tmp_path / "saved.txt"
    item = {"id": 3, "file": {"url": "/api/outputs/3/file"}}
    assert connector.download(item, save_to=target) == b"file bytes"
    assert target.read_bytes() == b"file bytes"
    assert connector.download({"monitor": None}) is None


def test_connector_deletes_and_explains_refusals(monkeypatch, fake_site, capsys):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789")
    fake_site["status"], fake_site["body"] = 200, b'{"deleted": 4}'
    assert connector.delete_outputs(category="drafts") == 4
    assert fake_site["requests"][-1]["method"] == "DELETE"
    assert fake_site["requests"][-1]["path"] == "/api/outputs?category=drafts"
    # No filter: nothing is sent.
    count = len(fake_site["requests"])
    assert connector.delete_outputs() is None and connector.delete_activity() is None
    assert connector.delete_output("not an id") is False
    assert len(fake_site["requests"]) == count
    # Another agent's output: the dashboard's reason is shown.
    fake_site["status"], fake_site["body"] = 403, b'{"detail": "Agents can only delete their own outputs"}'
    assert connector.delete_output({"id": 9}) is False
    assert "HTTP 403: Agents can only delete their own outputs" in capsys.readouterr().out


def test_connector_reads_survive_unreachable_dashboard(monkeypatch, capsys):
    connector = load_connector(monkeypatch, "http://127.0.0.1:9", "agent-key-0123456789")
    assert connector.agents() is None
    assert connector.read_monitor("me") is None
    assert connector.delete_activity(everything=True) is None
    assert "can't reach" in capsys.readouterr().out


# --- Agent descriptions -----------------------------------------------------


def test_description_can_be_given_when_adding_an_agent(client, session):
    response = client.post(
        "/dashboard/agents",
        data={"name": "news-bot", "api_key": key_for("news-bot"), "description": "  Finds AI news.\r\n\r\n\r\n\r\nDaily.  "},
        auth=TEST_AUTH,
    )
    assert "Agent added" in response.text
    agent = session.exec(select(Agent).where(Agent.name == "news-bot")).one()
    assert agent.description == "Finds AI news.\n\nDaily."  # trimmed, blank lines squeezed
    page = client.get(f"/dashboard/agents/{agent.id}", auth=TEST_AUTH).text
    assert "Finds AI news." in page


def test_description_is_optional_and_too_long_is_refused(client, session):
    agent_id = add_agent(client, session, "plain")
    assert session.get(Agent, agent_id).description is None
    response = client.post(
        "/dashboard/agents",
        data={"name": "wordy", "api_key": key_for("wordy"), "description": "x" * 1001},
        auth=TEST_AUTH,
    )
    assert "at most 1000 characters" in response.text
    assert 'value="wordy"' in response.text and "x" * 1001 in response.text  # what was typed is kept
    assert session.exec(select(Agent).where(Agent.name == "wordy")).first() is None


def test_description_can_be_changed_in_settings(client, session):
    agent_id = add_agent(client, session)
    url = f"/dashboard/agents/{agent_id}/description"
    response = client.post(url, data={"description": "Summarises <b>reports</b>."}, auth=TEST_AUTH)
    assert "Summarises &lt;b&gt;reports&lt;/b&gt;." in response.text  # escaped, not run as HTML
    assert "modal-open" in response.text  # settings stay open
    session.refresh(session.get(Agent, agent_id))
    assert session.get(Agent, agent_id).description == "Summarises <b>reports</b>."
    response = client.post(url, data={"description": "y" * 1001}, auth=TEST_AUTH)
    assert "at most 1000 characters" in response.text
    assert session.get(Agent, agent_id).description == "Summarises <b>reports</b>."  # unchanged
    client.post(url, data={"description": "   "}, auth=TEST_AUTH)
    session.expire_all()
    assert session.get(Agent, agent_id).description is None  # empty removes it


def test_description_needs_login_and_csrf(client, session):
    agent_id = add_agent(client, session)
    url = f"/dashboard/agents/{agent_id}/description"
    assert client.post(url, data={"description": "hi"}).status_code == 401
    assert client.post(url, data={"description": "hi"}, auth=TEST_AUTH,
                       headers={"X-CSRF-Token": "wrong"}).status_code == 403


def test_agents_can_read_each_others_descriptions(client, session):
    one = add_agent(client, session, "agent-1")
    two = add_agent(client, session, "agent-2")
    client.post(f"/dashboard/agents/{two}/description", data={"description": "Makes PDF reports."}, auth=TEST_AUTH)
    listed = client.get("/api/agents", headers=headers_for("agent-1")).json()
    assert {a["name"]: a["description"] for a in listed} == {"agent-1": None, "agent-2": "Makes PDF reports."}
    assert client.get("/api/agents/agent-2", headers=headers_for("agent-1")).json()["description"] == "Makes PDF reports."


def test_private_pages_are_never_stored_by_browsers(client, session):
    agent_id = add_agent(client, session)
    for path in ("/dashboard", "/dashboard/grid", f"/dashboard/agents/{agent_id}",
                 f"/dashboard/agents/{agent_id}/events"):
        assert client.get(path, auth=TEST_AUTH).headers["cache-control"] == "no-store"
        assert client.get(path).headers["cache-control"] == "no-store"  # the login refusal too
    assert client.get("/api/agents", headers=headers_for("agent-1")).headers["cache-control"] == "no-store"
    assert client.get("/tree", auth=TEST_AUTH).headers["cache-control"] == "no-store"  # the tree is personal



# --- Signing in and out -----------------------------------------------------


def sign_in(client, **extra):
    """Sign in on the login page; returns the response (not followed)."""
    return client.post("/login", data={**TEST_LOGIN, **extra}, follow_redirects=False)


def as_device(token):
    """Headers for a request from a browser holding this session cookie."""
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


def test_login_page_signs_a_device_in(client, session):
    assert "Sign in" in client.get("/login").text
    response = sign_in(client)
    assert response.status_code == 303 and response.headers["location"] == "/dashboard"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=86400" in cookie
    assert "Secure" in cookie  # https only on a deployed site
    token = response.cookies[SESSION_COOKIE]
    assert client.get("/dashboard", headers=as_device(token)).status_code == 200
    # Only a fingerprint of the token is stored.
    stored = session.exec(select(LoginSession)).all()
    assert all(token not in row.token_hash for row in stored)


def test_wrong_login_is_refused(client):
    response = sign_in(client, password="wrong")
    assert response.status_code == 401 and "Wrong username or password" in response.text
    assert SESSION_COOKIE not in response.cookies
    assert 'value="test-user"' in response.text  # the username is kept
    assert sign_in(client, username="someone-else").status_code == 401


def test_each_device_signs_in_separately(client):
    # Signing in on one device doesn't let a second one in.
    first = sign_in(client).cookies[SESSION_COOKIE]
    client.cookies.clear()
    assert client.get("/dashboard", headers=as_device(first)).status_code == 200
    assert client.get("/dashboard").status_code == 401
    assert client.get("/dashboard", headers=as_device("made-up-token")).status_code == 401


def test_logging_out_ends_only_this_devices_sign_in(client):
    phone = sign_in(client).cookies[SESSION_COOKIE]
    client.cookies.clear()
    response = client.post("/logout", auth=TEST_AUTH, follow_redirects=False)
    assert response.headers["location"] == "/"  # back to the front page
    assert SESSION_COOKIE in response.headers["set-cookie"] and "Max-Age=0" in response.headers["set-cookie"]
    assert client.get("/dashboard", auth=TEST_AUTH).status_code == 401  # this device: out at once
    assert client.get("/dashboard", headers=as_device(phone)).status_code == 200  # the other: still in
    assert "signed out on this device" in client.get("/login?signed_out=true").text


def test_sign_out_all_devices(client):
    phone = sign_in(client).cookies[SESSION_COOKIE]
    client.cookies.clear()
    client.post("/logout", data={"everywhere": "true"}, auth=TEST_AUTH)
    assert client.get("/dashboard", auth=TEST_AUTH).status_code == 401
    assert client.get("/dashboard", headers=as_device(phone)).status_code == 401


def test_logout_needs_the_csrf_token(client):
    del client.headers["X-CSRF-Token"]
    assert client.post("/logout", auth=TEST_AUTH).status_code == 403
    assert client.get("/dashboard", auth=TEST_AUTH).status_code == 200  # still signed in


def test_sign_in_expires_after_a_day(client, session):
    for login in session.exec(select(LoginSession)).all():
        login.expires_at = utc_now() - timedelta(seconds=1)
        session.add(login)
    session.commit()
    assert client.get("/dashboard", auth=TEST_AUTH).status_code == 401


def test_changing_the_password_signs_everyone_out(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "a-new-password")
    assert client.get("/dashboard", auth=TEST_AUTH).status_code == 401


def test_browsers_are_sent_to_the_login_page_and_back(client, session):
    agent_id = add_agent(client, session)
    page = f"/dashboard/agents/{agent_id}"
    response = client.get(page, headers={"Accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/login?next=%2Fdashboard%2Fagents%2F{agent_id}"
    assert f'value="{page}"' in client.get(response.headers["location"]).text
    back = client.post("/login", data={**TEST_LOGIN, "next": page}, follow_redirects=False)
    assert back.headers["location"] == page


def test_htmx_requests_are_sent_to_the_login_page(client, session):
    agent_id = add_agent(client, session)
    response = client.get(f"/dashboard/agents/{agent_id}/events", headers={
        "HX-Request": "true", "HX-Current-URL": f"http://testserver/dashboard/agents/{agent_id}"})
    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == f"/login?next=%2Fdashboard%2Fagents%2F{agent_id}"


@pytest.mark.parametrize("next_page", ["https://evil.example", "//evil.example", "/dashboard//evil.example", "/"])
def test_login_only_returns_to_dashboard_pages(client, next_page):
    assert sign_in(client, next=next_page).headers["location"] == "/dashboard"


def test_signed_in_device_skips_the_login_page(client):
    response = client.get("/login", auth=TEST_AUTH, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/dashboard"


def test_cookie_works_over_plain_http_on_this_computer(client):
    local = client.post("http://localhost/login", data=TEST_LOGIN, follow_redirects=False)
    assert "Secure" not in local.headers["set-cookie"]


def test_agents_still_use_only_their_key(client, session):
    add_agent(client, session)
    assert post_event(client).status_code == 201  # no dashboard sign-in needed


def test_dashboard_shows_log_out_and_sign_out_all(client):
    page = client.get("/dashboard", auth=TEST_AUTH).text
    assert 'action="/logout"' in page and "Sign out all devices" in page


# --- Refreshing sections only when something changed -------------------------


def seen_value(response) -> str:
    return re.search(r'name="seen" value="([0-9a-f]+)"', response.text).group(1)


@pytest.mark.parametrize("path, seen_id", [
    ("/dashboard/grid", "grid-seen"),
    ("/dashboard/agents/{id}/events", "events-seen"),
    ("/dashboard/agents/{id}/outputs?all=true", "outputs-seen"),
])
def test_unchanged_sections_are_not_resent(client, session, path, seen_id):
    agent_id = add_agent(client, session)
    send_output(client, "first")
    url = path.format(id=agent_id)
    first = client.get(url, auth=TEST_AUTH)
    assert f'id="{seen_id}"' in first.text
    seen = seen_value(first)
    joiner = "&" if "?" in url else "?"
    # Nothing changed: an empty "204", so the page isn't rebuilt.
    unchanged = client.get(f"{url}{joiner}seen={seen}", auth=TEST_AUTH)
    assert unchanged.status_code == 204 and unchanged.text == ""
    # Something changed: the new content, with a new fingerprint.
    send_output(client, "second")
    changed = client.get(f"{url}{joiner}seen={seen}", auth=TEST_AUTH)
    assert changed.status_code == 200 and seen_value(changed) != seen


def test_refreshing_sections_pause_in_hidden_tabs(client, session):
    agent_id = add_agent(client, session)
    pages = client.get("/dashboard", auth=TEST_AUTH).text + client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    triggers = re.findall(r'hx-trigger="([^"]*every[^"]*)"', html.unescape(pages))
    assert len(triggers) == 6  # grid, outputs, activity, monitor, messages-ready, inbox list
    assert all("document.visibilityState === 'visible'" in trigger for trigger in triggers)


def test_pages_use_the_prebuilt_tailwind_stylesheet(client):
    page = client.get("/").text
    assert "@tailwindcss/browser" not in page and "text/tailwindcss" not in page  # no in-browser build
    href = re.search(r'href="(/static/tailwind\.css\?v=[0-9a-f]+)"', page).group(1)
    css = client.get(href).text
    # A few classes the templates use, to catch a stylesheet that wasn't rebuilt.
    for selector in (".grid-cols-1", ".line-clamp-2", ".min-h-screen", ".whitespace-pre-line"):
        assert selector in css


# --- The Inbox ----------------------------------------------------------------


def upload_to_inbox(client, agent_id, *files, note=""):
    """Upload files from the agent page's Inbox window: (filename, bytes) pairs."""
    return client.post(
        f"/dashboard/agents/{agent_id}/inbox",
        data={"note": note},
        files=[("files", (name, data, "text/csv")) for name, data in files],
        auth=TEST_AUTH,
    )


def test_upload_waits_in_the_inbox_in_pieces(client, session):
    agent_id = add_agent(client, session)
    big = bytes(range(256)) * 10_000  # 2.56 MB: three 1 MB pieces
    response = upload_to_inbox(client, agent_id, ("sales.csv", big), note="Q3 numbers")
    assert "Uploaded sales.csv" in response.text and "Q3 numbers" in response.text
    item = session.exec(select(InboxItem)).one()
    assert (item.filename, item.size, item.note) == ("sales.csv", len(big), "Q3 numbers")
    assert len(session.exec(select(InboxChunk).where(InboxChunk.item_id == item.id)).all()) == 3
    # You can download it again to check, and it's in the agent's Activity.
    assert client.get(f"/dashboard/inbox/{item.id}/file", auth=TEST_AUTH).content == big
    events = client.get("/api/agents/me/events", headers=headers_for("agent-1")).json()
    assert events[0]["message"] == "Inbox: you uploaded sales.csv (2.4 MB)"


def test_agent_takes_its_inbox_file_and_it_is_deleted(client, session):
    agent_id = add_agent(client, session)
    upload_to_inbox(client, agent_id, ("a.csv", b"x,y\n1,2\n"), ("b.json", b"{}"))
    state = client.post("/api/state", json={"accepts_inbox": True}, headers=headers_for("agent-1")).json()
    assert state["inbox_waiting"] == 2 and state["accepts_inbox"] is True
    items = client.get("/api/inbox", headers=headers_for("agent-1")).json()
    assert [i["filename"] for i in items] == ["a.csv", "b.json"]
    file = client.get(items[0]["file_url"], headers=headers_for("agent-1"))
    assert file.content == b"x,y\n1,2\n" and "attachment" in file.headers["content-disposition"]
    assert client.delete(f"/api/inbox/{items[0]['id']}", headers=headers_for("agent-1")).json() == {"deleted": 1}
    session.expire_all()
    assert session.get(InboxItem, items[0]["id"]) is None
    assert session.exec(select(InboxChunk).where(InboxChunk.item_id == items[0]["id"])).all() == []
    assert "Inbox: agent received a.csv" in client.get(f"/dashboard/agents/{agent_id}/events", auth=TEST_AUTH).text
    assert client.post("/api/state", json={}, headers=headers_for("agent-1")).json()["inbox_waiting"] == 1


def test_inbox_is_private_to_its_agent(client, session):
    one = add_agent(client, session, "agent-1")
    add_agent(client, session, "agent-2")
    upload_to_inbox(client, one, ("secret.csv", b"private"))
    item_id = session.exec(select(InboxItem)).one().id
    assert client.get("/api/inbox", headers=headers_for("agent-2")).json() == []
    assert client.get(f"/api/inbox/{item_id}/file", headers=headers_for("agent-2")).status_code == 404
    assert client.delete(f"/api/inbox/{item_id}", headers=headers_for("agent-2")).status_code == 404
    assert session.get(InboxItem, item_id) is not None


def test_inbox_refuses_files_over_the_limit(client, session, monkeypatch):
    import main
    agent_id = add_agent(client, session)
    monkeypatch.setattr(main, "MAX_INBOX_FILE_BYTES", 10)
    response = upload_to_inbox(client, agent_id, ("ok.csv", b"small"), ("big.csv", b"x" * 11))
    assert "Uploaded ok.csv. Not uploaded: big.csv is over" in response.text
    assert [i.filename for i in session.exec(select(InboxItem)).all()] == ["ok.csv"]


def test_inbox_has_a_total_size_limit(client, session, monkeypatch):
    import main
    agent_id = add_agent(client, session)
    monkeypatch.setattr(main, "MAX_INBOX_TOTAL_BYTES", 12)
    upload_to_inbox(client, agent_id, ("first.csv", b"x" * 8))
    response = upload_to_inbox(client, agent_id, ("second.csv", b"x" * 8))
    assert "The inbox is full" in response.text
    assert session.exec(select(func.count(InboxChunk.id))).one() == 1  # nothing of the second was kept


def test_you_can_take_a_file_back_out_of_the_inbox(client, session):
    agent_id = add_agent(client, session)
    upload_to_inbox(client, agent_id, ("wrong.csv", b"oops"))
    item_id = session.exec(select(InboxItem)).one().id
    response = client.post(f"/dashboard/inbox/{item_id}/delete", auth=TEST_AUTH)
    assert "Removed wrong.csv" in response.text and "Nothing waiting" in response.text
    assert session.exec(select(InboxChunk)).all() == []
    assert client.post(f"/dashboard/inbox/{item_id}/delete", auth=TEST_AUTH).status_code == 404


def test_inbox_needs_login_csrf_and_a_key(client, session):
    agent_id = add_agent(client, session)
    files = [("files", ("a.csv", b"1", "text/csv"))]
    assert client.post(f"/dashboard/agents/{agent_id}/inbox", files=files).status_code == 401
    del client.headers["X-CSRF-Token"]
    assert client.post(f"/dashboard/agents/{agent_id}/inbox", files=files, auth=TEST_AUTH).status_code == 403
    assert client.get("/api/inbox").status_code == 401
    assert session.exec(select(InboxItem)).all() == []


def test_agent_page_shows_the_inbox(client, session):
    agent_id = add_agent(client, session)
    page = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert "open-inbox" in page and "hasn't switched its inbox on yet" in page
    upload_to_inbox(client, agent_id, ("a.csv", b"1"), ("b.csv", b"2"))
    client.post("/api/state", json={"accepts_inbox": True}, headers=headers_for("agent-1"))
    page = client.get(f"/dashboard/agents/{agent_id}", auth=TEST_AUTH).text
    assert '<span class="badge badge-sm">2</span>' in page and "switched its inbox on yet" not in page


def test_deleting_an_agent_deletes_its_inbox(client, session):
    agent_id = add_agent(client, session)
    upload_to_inbox(client, agent_id, ("a.csv", b"1"))
    client.post(f"/dashboard/agents/{agent_id}/delete", data={"password": TEST_EDIT_PASSWORD}, auth=TEST_AUTH)
    assert session.exec(select(InboxItem)).all() == [] and session.exec(select(InboxChunk)).all() == []


def test_connector_check_in_says_it_reads_its_inbox(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    fake_site["status"], fake_site["body"] = 200, b'{"paused": false, "inbox_waiting": 0}'
    connector.accept_inbox(lambda item, path: None)
    body = json.loads(fake_site["requests"][-1]["body"])
    assert body["accepts_inbox"] is True


def test_connector_hands_inbox_files_over_then_confirms(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    fake_site["status"], fake_site["body"] = 200, b"a,b\n1,2\n"  # the file's bytes
    items = [{"id": 1, "filename": "good.csv"}, {"id": 2, "filename": "later.csv"}, {"id": 3, "filename": "bad.csv"}]
    monkeypatch.setattr(connector, "inbox", lambda: items)
    confirmed, seen = [], {}
    monkeypatch.setattr(connector, "confirm_inbox", lambda item: confirmed.append(item["id"]) or True)
    monkeypatch.setattr(connector, "report", lambda *args, **kwargs: True)

    def on_file(item, path):
        seen[item["filename"]] = path.read_bytes()
        if item["filename"] == "later.csv":
            return False  # not now: keep it in the inbox
        if item["filename"] == "bad.csv":
            raise ValueError("can't parse")

    connector._inbox_handler = on_file
    connector._check_inbox()
    assert seen == {"good.csv": b"a,b\n1,2\n", "later.csv": b"a,b\n1,2\n", "bad.csv": b"a,b\n1,2\n"}
    assert confirmed == [1]  # only the one that was stored; the others are offered again next time


def test_connector_download_inbox_streams_to_a_file(monkeypatch, fake_site, tmp_path):
    connector = load_connector(monkeypatch, fake_site["url"], "agent-key-0123456789", tmp_path)
    fake_site["status"], fake_site["body"] = 200, b"payload"
    path = connector.download_inbox({"id": 7, "filename": "../../etc/data.csv"}, save_to=tmp_path / "out.csv")
    assert path.read_bytes() == b"payload" and fake_site["requests"][-1]["path"] == "/api/inbox/7/file"
    temp = connector.download_inbox({"id": 7, "filename": "../../etc/data.csv"})
    assert temp.name == "data.csv" and temp.read_bytes() == b"payload"  # never outside its temporary folder



# --- The home page's tree of techs ---------------------------------------------


def as_guest(client) -> dict:
    """Sign in with "as guest?"; returns headers for requests as that guest."""
    token = client.post("/login/guest", follow_redirects=False).cookies[SESSION_COOKIE]
    client.cookies.clear()
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


def test_signing_in_from_home_returns_to_the_tree(client):
    response = client.post("/login", data={**TEST_LOGIN, "next": "/tree?entered"}, follow_redirects=False)
    assert response.headers["location"] == "/tree?entered"
    # Already signed in, Login goes straight into the tree's build.
    again = client.get("/login?next=%2Ftree%3Fentered", auth=TEST_AUTH, follow_redirects=False)
    assert again.headers["location"] == "/tree?entered"


def test_front_page_shows_login_even_when_signed_in(client):
    page = client.get("/", auth=TEST_AUTH).text
    assert ">Login</a>" in page and 'id="tree"' not in page


def test_tree_shows_the_techs(client):
    page = client.get("/tree", auth=TEST_AUTH).text
    assert 'class="tree"' in page  # finished, no build animation
    assert 'id="home-name"' not in page and "login-ghost" not in page
    assert ">Ren</span>" in page and ">signed in</span>" in page
    assert 'href="/dashboard"' in page and "Portfolio" in page and "Data tracking" in page
    # The root tech: a click goes to the front page; holding signs out (a hidden form).
    assert 'href="/" class="root-main"' in page and ">Hold to sign out</span>" in page
    assert 'action="/logout" class="root-signout" hidden' in page and f'value="{csrf_token()}"' in page
    assert "Choose where to go" not in page
    assert 'class="tree-badge root-badge"' in page and "icon-cog" in page  # Ren's developer-mode cog
    assert 'id="tech-settings"' in page


def test_tree_needs_signing_in(client):
    response = client.get("/tree", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"


def test_tree_builds_itself_right_after_signing_in(client):
    page = client.get("/tree?entered", auth=TEST_AUTH).text
    assert "data-entered" in page and "tree is-building" in page
    assert 'id="home-name"' in page and 'id="login-ghost"' in page  # the Login button, about to move


def test_guest_tree_root_says_guest(client):
    page = client.get("/tree?entered", headers=as_guest(client)).text
    assert ">Guest</span>" in page and ">Ren</span>" not in page
    assert "root-badge" not in page and "icon-cog" not in page and "tech-settings" not in page  # no developer mode


def test_signing_out_returns_to_the_front_page(client):
    response = client.post("/logout", auth=TEST_AUTH, follow_redirects=False)
    assert response.headers["location"] == "/"
    assert client.get("/tree", auth=TEST_AUTH, follow_redirects=False).status_code == 303  # signed out


def test_developer_settings_set_who_can_see_a_tech(client, session):
    settings = client.get("/tree/techs/dashboard/settings", auth=TEST_AUTH).text
    assert "Dashboard settings" in settings and 'type="range"' in settings and 'value="0"' in settings
    assert "Page API key" not in settings  # the dashboard has one key per agent instead
    response = client.post("/tree/techs/dashboard/visibility", data={"level": 1}, auth=TEST_AUTH)
    assert 'value="1"' in response.text and "Private:" in response.text
    assert 'id="tech-dashboard"' in response.text and 'hx-swap-oob="true"' in response.text  # the card updates too
    assert session.get(TechSetting, "dashboard").visibility == "private"
    assert client.post("/tree/techs/dashboard/visibility", data={"level": 3}, auth=TEST_AUTH).status_code == 422
    assert client.get("/tree/techs/nope/settings", auth=TEST_AUTH).status_code == 404


def test_guests_cannot_use_developer_settings(client):
    guest = as_guest(client)
    assert client.get("/tree/techs/dashboard/settings", headers=guest).status_code == 403
    assert client.post("/tree/techs/dashboard/visibility", data={"level": 2}, headers=guest).status_code == 403


def test_private_and_hidden_techs_for_guests(client, session):
    guest = as_guest(client)
    session.add(TechSetting(slug="dashboard", visibility="private"))
    session.add(TechSetting(slug="portfolio", visibility="hidden"))
    session.commit()
    page = client.get("/tree", headers=guest).text
    # Private: shown greyed out, can't be opened. Hidden: not there at all.
    assert "Dashboard" in page and 'href="/dashboard"' not in page and ">private</span>" in page
    assert "Portfolio" not in page
    # You still see and open everything, with its setting in the corner.
    mine = client.get("/tree", auth=TEST_AUTH).text
    assert 'href="/dashboard"' in mine and ">private</span>" in mine and "Portfolio" in mine
    # And the server keeps guests out of a private dashboard, whatever they type.
    blocked = client.get("/dashboard", headers={**guest, "Accept": "text/html"}, follow_redirects=False)
    assert blocked.status_code == 303 and blocked.headers["location"] == "/tree"
    assert client.get("/dashboard/grid", headers=guest).status_code == 403
    assert client.get("/dashboard", auth=TEST_AUTH).status_code == 200


def test_page_wide_api_key_can_be_set_shown_and_randomized(client, session):
    settings = client.get("/tree/techs/data-tracking/settings", auth=TEST_AUTH).text
    assert "Page API key" in settings and "No key yet" in settings
    randomized = client.post("/tree/techs/data-tracking/key", data={"new_key": ""}, auth=TEST_AUTH)
    key = re.search(r"<code[^>]*>([0-9a-f]{64})</code>", randomized.text).group(1)
    assert "New random key saved" in randomized.text and randomized.headers["cache-control"] == "no-store"
    assert key not in session.get(TechSetting, "data-tracking").api_key_encrypted  # stored encrypted
    assert "View key" in client.get("/tree/techs/data-tracking/settings", auth=TEST_AUTH).text
    assert key in client.post("/tree/techs/data-tracking/key/show", auth=TEST_AUTH).text
    typed = client.post("/tree/techs/data-tracking/key", data={"new_key": "my-own-page-key-0123456789"}, auth=TEST_AUTH)
    assert "my-own-page-key-0123456789" in typed.text and "Key saved" in typed.text
    short = client.post("/tree/techs/data-tracking/key", data={"new_key": "short"}, auth=TEST_AUTH)
    assert "at least 20 characters" in short.text
    assert client.post("/tree/techs/dashboard/key", data={"new_key": ""}, auth=TEST_AUTH).status_code == 404
    assert client.post("/tree/techs/data-tracking/key/show", headers=as_guest(client)).status_code == 403


def test_entered_does_nothing_when_signed_out(client):
    response = client.get("/tree?entered", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"


def test_tech_descriptions_can_be_edited(client, session):
    response = client.post("/tree/techs/portfolio/description",
                           data={"description": "  My   best projects.  "}, auth=TEST_AUTH)
    assert "Description saved" in response.text and 'id="tech-portfolio"' in response.text  # card updates too
    assert session.get(TechSetting, "portfolio").description == "My best projects."  # tidied
    assert "My best projects." in client.get("/tree", auth=TEST_AUTH).text
    too_long = client.post("/tree/techs/portfolio/description", data={"description": "x" * 121}, auth=TEST_AUTH)
    assert "at most 120 characters" in too_long.text
    session.expire_all()
    assert session.get(TechSetting, "portfolio").description == "My best projects."  # unchanged
    reset = client.post("/tree/techs/portfolio/description", data={"description": "  "}, auth=TEST_AUTH)
    assert "Back to the original description" in reset.text
    assert "Projects and write-ups. Coming soon." in client.get("/tree", auth=TEST_AUTH).text
    assert client.post("/tree/techs/portfolio/description", data={"description": "hi"},
                       headers=as_guest(client)).status_code == 403


# --- One device, several accounts ------------------------------------------------


def device_cookie(response, cookies: dict) -> dict:
    """Keep a device's cookies up to date from a response (set or deleted)."""
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        value = rest.split(";")[0]
        if "Max-Age=0" in header or 'expires=Thu, 01 Jan 1970' in header:
            cookies.pop(name, None)
        else:
            cookies[name] = value.strip('"')
    return cookies


def send(client, method, url, cookies, **kwargs):
    client.cookies.clear()
    header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = {**kwargs.pop("headers", {}), **({"Cookie": header} if header else {})}
    response = client.request(method, url, headers=headers, follow_redirects=False, **kwargs)
    device_cookie(response, cookies)
    return response


def test_login_uses_the_highest_account_the_device_has(client):
    device = {}
    send(client, "POST", "/login", device, data={**TEST_LOGIN, "next": "/tree?entered"})  # signed in as Ren
    send(client, "POST", "/login/guest", device)  # ...and then "as guest?"
    assert ">Guest</span>" in send(client, "GET", "/tree", device).text  # the explicit choice: Guest
    # Logging out (a click) keeps both; pressing Login then picks Ren, the higher account.
    login = send(client, "GET", "/login?next=%2Ftree%3Fentered", device)
    assert login.status_code == 303 and login.headers["location"] == "/tree?entered"
    assert ">Ren</span>" in send(client, "GET", "/tree", device).text
    # "as guest?" again reuses the same guest sign-in rather than starting another.
    tokens_before = device["dashboard_session"].split(".")
    send(client, "POST", "/login/guest", device)
    assert sorted(device["dashboard_session"].split(".")) == sorted(tokens_before)
    # Signing out (holding) ends every account on the device.
    send(client, "POST", "/logout", device, headers={"X-CSRF-Token": csrf_token()})
    assert send(client, "GET", "/tree", device).status_code == 303
    assert send(client, "GET", "/login?next=%2Ftree%3Fentered", device).status_code == 200  # asks for the password


def test_guest_only_device_logs_in_as_guest(client):
    device = {}
    send(client, "POST", "/login/guest", device)
    login = send(client, "GET", "/login?next=%2Ftree%3Fentered", device)
    assert login.status_code == 303  # straight in: Guest is the highest account it has
    assert ">Guest</span>" in send(client, "GET", "/tree", device).text


def test_techs_can_be_rearranged(client, session):
    new_order = ["data-tracking", "dashboard", "portfolio"]
    response = client.post("/tree/techs/order", data={"order": new_order}, auth=TEST_AUTH)
    assert response.status_code == 204
    page = client.get("/tree", auth=TEST_AUTH).text
    positions = [page.index(f'id="tech-{slug}"') for slug in new_order]
    assert positions == sorted(positions)  # shown top to bottom in the new order
    # Guests see the same order (minus anything hidden from them).
    hidden = session.get(TechSetting, "data-tracking")
    hidden.visibility = "hidden"
    session.add(hidden)
    session.commit()
    guest_page = client.get("/tree", headers=as_guest(client)).text
    assert guest_page.index('id="tech-dashboard"') < guest_page.index('id="tech-portfolio"')
    assert 'id="tech-data-tracking"' not in guest_page
    # Every tech, once each; owner only.
    assert client.post("/tree/techs/order", data={"order": ["dashboard"]}, auth=TEST_AUTH).status_code == 422
    assert client.post("/tree/techs/order", data={"order": new_order + ["dashboard"]}, auth=TEST_AUTH).status_code == 422
    assert client.post("/tree/techs/order", data={"order": new_order}, headers=as_guest(client)).status_code == 403


# --- Lighter pages: everything from this site, cached for good -----------------


def test_pages_load_nothing_from_other_servers(client):
    for page in (client.get("/").text, client.get("/tree", auth=TEST_AUTH).text,
                 client.get("/dashboard", auth=TEST_AUTH).text):
        assert "cdn.jsdelivr.net" not in page and "fonts.googleapis.com" not in page
        assert re.search(r'src="/static/vendor/htmx-[\d.]+\.min\.js\?v=[0-9a-f]+"', page)
        assert re.search(r'src="/static/vendor/alpine-[\d.]+\.min\.js\?v=[0-9a-f]+"', page)
    css = client.get("/static/theme.css").text
    assert 'src: url("fonts/ibm-plex-mono-latin-400-normal.woff2")' in css
    font = client.get("/static/fonts/ibm-plex-mono-latin-400-normal.woff2")
    assert font.status_code == 200 and font.content[:4] == b"wOF2"
    assert client.get("/static/fonts/OFL.txt").status_code == 200  # the font's licence travels with it


def test_static_files_are_cached_for_good_only_when_versioned(client):
    page = client.get("/").text
    href = re.search(r'href="(/static/tailwind\.css\?v=[0-9a-f]+)"', page).group(1)
    assert client.get(href).headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "immutable" in client.get("/static/fonts/ibm-plex-mono-latin-700-normal.woff2").headers["cache-control"]
    # Without a fingerprint, the browser keeps checking (it might change).
    assert "immutable" not in client.get("/static/theme.css").headers.get("cache-control", "")


def test_daisyui_is_built_in_not_loaded_whole(client):
    page = client.get("/dashboard", auth=TEST_AUTH).text
    assert "npm/daisyui" not in page  # not the whole library from the CDN
    href = re.search(r'href="(/static/tailwind\.css\?v=[0-9a-f]+)"', page).group(1)
    css = client.get(href).text
    for selector in (".btn", ".card", ".modal", ".badge", ".alert-success", ".alert-warning", ".toast"):
        assert selector in css
    assert len(css) < 300_000  # the whole of daisyUI is over 1 MB


def test_health_check_for_uptime_monitors(client):
    # UptimeRobot checks with HEAD requests by default; both must answer 200.
    assert client.get("/health").text == "ok"
    assert client.head("/health").status_code == 200
    assert client.head("/").status_code == 200

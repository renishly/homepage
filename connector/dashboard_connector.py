"""Dashboard connector: lets any Python agent report to your Agent Dashboard.

Works wherever your dashboard runs: on your own computer, on Render, or on
any other website. Drop this file next to your agent's code. It needs Python
3.10+ and the `requests` package (pip install requests). Nothing else.

SETUP: two values (see the PLACEHOLDERS section below)
  1. DASHBOARD_URL      the address of your dashboard website, without /dashboard,
                        e.g. https://your-service.onrender.com
  2. DASHBOARD_API_KEY  this agent's key, from the dashboard's "Add Agent" card
                        (or later: the agent's settings, the gear next to its
                        name, then "View key").
  Set them as environment variables (recommended), e.g.
      DASHBOARD_URL=https://your-site.onrender.com DASHBOARD_API_KEY=the-key python your_agent.py
  or replace the placeholders below.

QUICK START: everything this file offers, in the order you'd usually use it

    from pathlib import Path
    from dashboard_connector import (
        accept_messages, check_in, flush, listen, output, report, set_monitor,
        start_check_ins, wait_if_paused,
    )

    # 1. Optional: let the dashboard send this agent text messages. Until you
    #    call this, the dashboard's message box stays switched off.
    def on_message(text):            # e.g. pass the text to your agent's LLM
        ...
    accept_messages(on_message)

    # 2. Optional: run your own code when Start or Pause is pressed.
    def on_command(command):         # command["command"] is "start" or "pause"
        report("Paused" if command["command"] == "pause" else "Started", "status")
    listen(on_command)

    # 3. Check in, at a rhythm that suits this agent (see CHECK-INS below).
    #    An agent that runs all the time checks in in the background:
    start_check_ins(every=30)        # seconds; shorter = quicker reactions
    #    ...an agent that runs on a schedule instead calls, at each run:
    #    check_in(every=3600)        # e.g. an hourly agent

    # 4. Say hello (a status line in the agent's Activity log).
    report("Agent online", "status")

    # 5. Optional: the Monitor, showing either a link to where your data lives,
    #    or a PDF shown inside the dashboard (only the latest one is kept).
    set_monitor("https://docs.google.com/spreadsheets/d/...", "Results sheet")

    # 6. Your agent's work loop.
    while True:
        wait_if_paused()             # a safe point: waits here while paused
        ...                          # your agent's real work
        # output(content, category) is like print(), but to the dashboard's
        # Outputs section. Only what you wrap in output() is sent, so choose
        # what matters, or send a short summary of a lot of data.
        output("Found 12 new articles", "daily summary")       # text
        output(12, "articles found")                           # a number
        output("https://example.com/story", "links")           # a clickable link
        output({"top": "story", "count": 12}, "stats")         # a list or dict
        output(Path("reports/today.pdf"), "reports")           # a file, up to 5 MB
        set_monitor(Path("daily_summary.pdf"), "Daily summary")  # a PDF on schedule

    # A short script that runs on a schedule and then exits should end with:
    flush()                          # try to send anything still waiting

FUNCTIONS
  output(content, category)  Show a result in Outputs, sorted by category (1-50
                             characters; the dashboard can filter by it and pin
                             one). content: text (up to 20,000 characters), a
                             number, an http(s) link, a list/dict, or a file
                             (pathlib.Path, open file, or bytes; up to 5 MB).
  report(message, kind)      A status line in Activity. kind: "log" (blue),
                             "status" (green) or "error" (red).
  set_monitor(link_or_pdf, label)
                             The Monitor: an http(s) link, a PDF (up to 5 MB) shown
                             inside the page, or None to remove it. The label is up
                             to 50 characters.
  start_check_ins(every)     Check in automatically every `every` seconds, in the
                             background (for agents that run all the time).
  check_in(every=None)       Check in once, now (for agents that run on a schedule:
                             call it at the start of each run). `every` says how
                             often to expect check-ins; it's remembered.
  accept_messages(on_message)
                             Switch on the dashboard's message box; on_message(text)
                             receives each message, at check-ins.
  listen(on_command, every=None)
                             Run on_command(command) when Start/Pause is pressed,
                             at check-ins. (Messages go to on_message instead, if
                             set.) Passing `every` also starts background check-ins.
  wait_if_paused()           Wait while the dashboard has this agent paused.
  is_paused()                True while paused.
  flush(), pending()         Send what's waiting in the offline buffer now / count it.
  All of them return quickly and never raise: problems are printed as one-line
  "[dashboard] ..." warnings, and your agent carries on.

CHECK-INS
  Each agent decides how often it checks in: every few seconds, every few
  minutes, hourly, daily (1 second to 1 week). A check-in says "I'm here",
  tells the dashboard how often to expect the next one, and picks up any
  waiting Start/Pause/messages. The dashboard shows the agent as "online" while
  it keeps to its own rhythm (plus half an interval of slack), so an hourly
  agent stays "online" between runs. Agents that never say how often they
  check in are expected every 60 seconds. Any call to the dashboard also counts
  as being seen.

START AND PAUSE (the dashboard's buttons)
  They reach the agent at its next check-in. While paused, output() and
  set_monitor() hold what you send and deliver it, in order and with its
  original time, when Start is pressed. report() still goes through, so status lines and errors
  stay visible. This needs no extra code. To pause the agent's *work* too,
  call wait_if_paused() at safe points in your loop.

OFFLINE BUFFER
  If the dashboard can't be reached for a while (no internet, a restart, a
  sleeping free site, a server error), output(), report() and set_monitor()
  save what they couldn't send in a "dashboard_buffer" folder next to this file
  (or wherever DASHBOARD_BUFFER_DIR points). It's sent automatically, in order
  and with its original times, once the dashboard is back, even if your agent
  was restarted in between. Mistakes retrying can't fix (a wrong key, a file
  over 5 MB) aren't saved; they're printed once instead.
"""

import json
import mimetypes
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

# =============================================================================
# PLACEHOLDERS: replace these two values, OR set the environment variables
# DASHBOARD_URL and DASHBOARD_API_KEY (environment variables win if both are set).
# =============================================================================

# >>> REPLACE THIS PLACEHOLDER with your dashboard's address (no /dashboard at the end):
#       "http://127.0.0.1:8000"               if the dashboard runs on this same computer
#       "https://your-service.onrender.com"   if it's deployed on Render
#       "https://your-own-domain.com"         if it's on a custom domain or another host
#     This file was downloaded from: {{DOWNLOADED_FROM}}
#     (that may be a local test address; use the address your agent can actually reach)
DASHBOARD_URL_PLACEHOLDER = "REPLACE_WITH_YOUR_DASHBOARD_URL"

# >>> REPLACE THIS PLACEHOLDER with this agent's API key, from "Add Agent" or "View key".
#     Prefer the DASHBOARD_API_KEY environment variable instead: a key typed in here
#     must never be committed to Git or shared.
DASHBOARD_API_KEY_PLACEHOLDER = "REPLACE_WITH_YOUR_AGENT_API_KEY"

# =============================================================================

REPORT_TIMEOUT_SECONDS = 10  # report() runs in your agent's own code, so keep it short
LISTEN_TIMEOUT_SECONDS = 30  # the listener runs in the background; allow sleepy servers
UPLOAD_TIMEOUT_SECONDS = 60  # sending a file can take a while
MAX_FILE_BYTES = 5 * 1024 * 1024  # the dashboard accepts files up to 5 MB
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# Offline buffer: where unsent items wait, how often to retry, and how much to keep.
# Set DASHBOARD_BUFFER_DIR to keep the buffer somewhere else.
BUFFER_DIR = os.getenv("DASHBOARD_BUFFER_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dashboard_buffer"
)
RETRY_SECONDS = 15
MIN_CHECK_IN, MAX_CHECK_IN = 1, 7 * 24 * 60 * 60  # check-in interval limits: 1 second to a week
BUFFER_MAX_ITEMS = 1000  # beyond this, the oldest waiting items are dropped
BUFFER_MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB of waiting files at most


def normalize_url(url: str) -> str:
    """Tidy a dashboard address: trim spaces and a trailing "/" or "/dashboard"."""
    url = url.strip().rstrip("/")
    if url.endswith("/dashboard"):  # easy to copy from the browser's address bar
        url = url[: -len("/dashboard")]
    return url


def config_problem(url: str, api_key: str) -> str | None:
    """Explain what's wrong with the settings, or return None if they look fine."""
    if not url or url.startswith("REPLACE_WITH_"):
        return "Set DASHBOARD_URL (or replace DASHBOARD_URL_PLACEHOLDER) with your dashboard's address."
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return f"DASHBOARD_URL must start with http:// or https://, got {url!r}."
    if not api_key or api_key.startswith("REPLACE_WITH_"):
        return "Set DASHBOARD_API_KEY (or replace DASHBOARD_API_KEY_PLACEHOLDER) with this agent's key."
    return None


DASHBOARD_URL = normalize_url(os.getenv("DASHBOARD_URL") or DASHBOARD_URL_PLACEHOLDER)
API_KEY = (os.getenv("DASHBOARD_API_KEY") or DASHBOARD_API_KEY_PLACEHOLDER).strip()
PROBLEM = config_problem(DASHBOARD_URL, API_KEY)

if PROBLEM:
    print(f"[dashboard] Not connected: {PROBLEM}")
elif urlparse(DASHBOARD_URL).scheme == "http" and urlparse(DASHBOARD_URL).hostname not in LOCAL_HOSTS:
    print(
        "[dashboard] Warning: DASHBOARD_URL uses http://, so the API key travels unencrypted. "
        "Use https:// for a deployed dashboard."
    )

_http = requests.Session()
_http.headers["X-API-Key"] = API_KEY


def _send(method: str, path: str, timeout: float, **kwargs) -> requests.Response:
    """Make one request to the dashboard API.

    Redirects are not followed: a redirect (e.g. http:// to https://) would turn a
    POST into a GET and silently lose the report, so it's reported as a setup problem.
    """
    response = _http.request(
        method, f"{DASHBOARD_URL}{path}", timeout=timeout, allow_redirects=False, **kwargs
    )
    if response.is_redirect:
        where = response.headers.get("Location", "another address")
        raise requests.HTTPError(f"redirected to {where}", response=response)
    response.raise_for_status()
    return response


def _warn(what: str, error: Exception) -> None:
    """Print a one-line warning with a hint, instead of crashing."""
    response = getattr(error, "response", None)
    status = response.status_code if response is not None else None
    if status in (301, 302, 303, 307, 308):
        reason = f"{error}. Set DASHBOARD_URL to that address (often https:// instead of http://)"
    elif status == 401:
        reason = "HTTP 401: the API key was refused. Check DASHBOARD_API_KEY (it may have been replaced)"
    elif status == 404:
        reason = "HTTP 404: check DASHBOARD_URL points at the dashboard website itself"
    elif status == 413:
        reason = "HTTP 413: the file is too big (max 5 MB)"
    elif status == 422:
        reason = "HTTP 422: the dashboard rejected the content (check the category and content)"
    elif status is not None:
        reason = f"HTTP {status}"
    elif isinstance(error, requests.Timeout):
        reason = "timed out (a sleeping free Render site can take about a minute to wake)"
    elif isinstance(error, requests.ConnectionError):
        reason = f"can't reach {DASHBOARD_URL} (is it running, and is the address right?)"
    else:
        reason = f"{type(error).__name__}: {error}"
    print(f"[dashboard] Could not {what}: {reason}.")


# =============================================================================
# Check-ins, Start/Pause and messages
#
# A check-in tells the dashboard "I'm here" (keeping the agent "online"), says
# how often to expect the next one and whether this agent accepts messages,
# learns whether the agent is paused, and delivers any waiting Start/Pause/
# messages to your handlers. How often to check in is up to each agent:
#   - an agent that runs all the time: start_check_ins(every=30) once;
#   - an agent that runs on a schedule (e.g. hourly): check_in(every=3600) at
#     the start of each run.
# =============================================================================

_paused = False  # what the dashboard said at the last check-in
_state_known = False  # True once a check-in has succeeded
_accepts_messages = False  # set by accept_messages()
_declared_every = None  # seconds between check-ins, as this agent declared it
_message_handler = None
_command_handler = None
_check_in_thread = None
_announced_hold = False


def _set_paused(paused: bool) -> None:
    """Remember the pause state; on Start, send whatever was held."""
    global _paused, _announced_hold
    was_paused, _paused = _paused, paused
    if was_paused and not paused:
        _announced_hold = False
        _retry_now.set()  # wake the buffer's sender: held items can go now


def _check_in() -> bool:
    """Send the check-in itself (POST /api/state) and learn the pause state."""
    global _state_known
    body = {"accepts_messages": _accepts_messages}
    if _declared_every is not None:
        body["check_in_every"] = _declared_every
    try:
        state = _send("POST", "/api/state", REPORT_TIMEOUT_SECONDS, json=body).json()
    except (requests.RequestException, ValueError):
        return False  # unreachable: keep the last known state and try again later
    _state_known = True
    _set_paused(bool(state.get("paused")))
    return True


def _declare_every(every) -> None:
    """Remember how often this agent checks in (seconds, 1 second to a week).

    Values outside that range are brought into it, with a warning (never an error).
    """
    global _declared_every
    try:
        wanted = int(every)
    except (TypeError, ValueError):
        print(f"[dashboard] Ignoring check-in interval {every!r}: it must be a number of seconds.")
        return
    allowed = min(max(wanted, MIN_CHECK_IN), MAX_CHECK_IN)
    if allowed != wanted:
        print(f"[dashboard] Check-in interval {wanted}s is out of range; using {allowed}s.")
    _declared_every = allowed


def check_in(every: float | None = None) -> bool:
    """Check in with the dashboard once, now.

    every: how often this agent checks in, in seconds (e.g. 3600 for an hourly
           agent). The dashboard shows the agent as online while it keeps to
           this rhythm, plus some slack. Set it once; it's remembered.
    Also learns whether the agent is paused (see is_paused()) and hands any
    waiting Start/Pause/messages to your listen()/accept_messages() handlers.
    Returns True if the dashboard was reached.

    For an agent that runs on a schedule, call it at the start of each run.
    """
    if PROBLEM:
        return False
    if every is not None:
        _declare_every(every)
    reached = _check_in()
    if reached and (_command_handler is not None or _message_handler is not None):
        _check_commands()
    return reached


def start_check_ins(every: float = 30) -> None:
    """Check in automatically every `every` seconds, in the background.

    For agents that run continuously. Start/Pause and messages reach the agent
    at each check-in, so a shorter interval means quicker reactions (e.g. 5);
    a longer one means fewer requests (e.g. 300). Calling it again changes the
    interval.
    """
    global _check_in_thread
    if PROBLEM:
        print("[dashboard] Not checking in until the settings are fixed.")
        return
    _declare_every(every)
    if _check_in_thread is not None:
        return  # already running; it picks up the new interval

    def loop():
        while True:
            check_in()
            time.sleep(_declared_every)

    _check_in_thread = threading.Thread(target=loop, name="dashboard-check-in", daemon=True)
    _check_in_thread.start()


def is_paused() -> bool:
    """True while the dashboard has this agent paused (as of the last check-in)."""
    return _paused


def wait_if_paused(check_every: float = 5.0) -> bool:
    """If the dashboard has this agent paused, wait here until Start is pressed.

    Call it at safe points in your agent's loop, e.g. before starting the next
    task, so Pause stops the agent's work and not just its outputs. While it
    waits, it checks in every `check_every` seconds to notice Start.
    Returns True if it had to wait.
    """
    if PROBLEM:
        return False
    if not _state_known:
        _check_in()  # make sure we know the state before deciding
    if not _paused:
        return False
    print("[dashboard] Paused from the dashboard; waiting for Start...")
    while _paused:
        time.sleep(check_every)
        check_in()
    print("[dashboard] Started again from the dashboard.")
    return True


def accept_messages(on_message) -> None:
    """Switch on the dashboard's message box for this agent.

    on_message(text) is called with each message you send from the dashboard
    (e.g. to pass it to the agent's LLM). Messages arrive at the agent's check-ins,
    so the agent must also check in: start_check_ins() or check_in().
    Until an agent calls this, the dashboard keeps its message box switched off.
    """
    global _accepts_messages, _message_handler
    if PROBLEM:
        print("[dashboard] Not accepting messages until the settings are fixed.")
        return
    _message_handler = on_message
    _accepts_messages = True
    _check_in()  # tell the dashboard straight away


# =============================================================================
# Offline buffer
#
# Each thing to send is an "item": a small dict saying what it is (kind), when
# it was made (created_at), and what to send. If sending fails for a reason
# that should pass (the dashboard is unreachable, asleep, or has a server
# error), the item is appended to dashboard_buffer/queue.jsonl (one item per
# line; files are copied into dashboard_buffer/files/). A background thread
# retries every RETRY_SECONDS and sends waiting items oldest first.
# Mistakes that retrying can't fix (a wrong key, a file that's too big...)
# are never buffered; they're reported once, as before.
# =============================================================================

_buffer_lock = threading.Lock()  # one change to the queue file at a time
_flush_lock = threading.Lock()  # one sender at a time, so nothing is sent twice
_retry_now = threading.Event()  # set to make the background sender try straight away
_sender_started = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _queue_path() -> str:
    return os.path.join(BUFFER_DIR, "queue.jsonl")


def _load_queue() -> list[dict]:
    try:
        with open(_queue_path(), encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        print(f"[dashboard] The offline buffer couldn't be read ({error}); starting a new one.")
        return []


def _save_queue(items: list[dict]) -> None:
    """Rewrite the queue file safely (write a new copy, then swap it in)."""
    os.makedirs(BUFFER_DIR, exist_ok=True)
    temporary = _queue_path() + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item) + "\n")
    os.replace(temporary, _queue_path())


def _delete_item_file(item: dict) -> None:
    if item.get("file"):
        try:
            os.remove(os.path.join(BUFFER_DIR, "files", item["file"]))
        except FileNotFoundError:
            pass


def _item_data(item: dict) -> bytes:
    """The bytes of a file item: still in memory, or saved in the buffer folder."""
    if "_data" in item:
        return item["_data"]
    with open(os.path.join(BUFFER_DIR, "files", item["file"]), "rb") as handle:
        return handle.read()


def _deliver(item: dict) -> None:
    """Send one item to the dashboard. Raises requests.RequestException on failure."""
    kind, made = item["kind"], item["created_at"]
    if kind == "report":
        _send("POST", "/api/events", REPORT_TIMEOUT_SECONDS, json={**item["body"], "created_at": made})
    elif kind == "output":
        _send("POST", "/api/outputs", REPORT_TIMEOUT_SECONDS, json={**item["body"], "created_at": made})
    elif kind == "output_file":
        _send(
            "POST",
            "/api/outputs/file",
            UPLOAD_TIMEOUT_SECONDS,
            data={"category": item["category"], "created_at": made},
            files={"file": (item["filename"], _item_data(item), item["content_type"])},
        )
    elif kind == "monitor":
        _send("PUT", "/api/monitor", REPORT_TIMEOUT_SECONDS, json={**item["body"], "created_at": made})
    elif kind == "monitor_file":
        _send(
            "POST",
            "/api/monitor/file",
            UPLOAD_TIMEOUT_SECONDS,
            data={"label": item["label"] or "", "created_at": made},
            files={"file": (item["filename"], _item_data(item), "application/pdf")},
        )


def _worth_retrying(error: requests.RequestException) -> bool:
    """True if the problem should pass by itself: no connection, a timeout, or a
    server-side error (5xx, e.g. a restart, an outage, or a full database)."""
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    response = getattr(error, "response", None)
    return response is not None and (response.status_code >= 500 or response.status_code == 429)


def _add_to_buffer(item: dict) -> int:
    """Save an item to send later. Returns how many items are now waiting."""
    with _buffer_lock:
        items = _load_queue()
        if item["kind"] in ("monitor", "monitor_file"):
            # Only the latest monitor matters: drop older ones still waiting.
            for old in [i for i in items if i["kind"] in ("monitor", "monitor_file")]:
                _delete_item_file(old)
            items = [i for i in items if i["kind"] not in ("monitor", "monitor_file")]
        if "_data" in item:  # copy the file into the buffer folder
            os.makedirs(os.path.join(BUFFER_DIR, "files"), exist_ok=True)
            item["file"] = uuid.uuid4().hex
            with open(os.path.join(BUFFER_DIR, "files", item["file"]), "wb") as handle:
                handle.write(item.pop("_data"))
            item["size"] = os.path.getsize(os.path.join(BUFFER_DIR, "files", item["file"]))
        items.append(item)
        # Keep the buffer from growing without limit: drop the oldest first.
        dropped = 0
        while len(items) > BUFFER_MAX_ITEMS or sum(i.get("size", 0) for i in items) > BUFFER_MAX_FILE_BYTES:
            _delete_item_file(items.pop(0))
            dropped += 1
        if dropped:
            print(f"[dashboard] Offline buffer full: dropped the {dropped} oldest waiting item(s).")
        _save_queue(items)
        waiting = len(items)
    _start_sender()
    return waiting


def _remove_from_buffer(item_id: str) -> None:
    with _buffer_lock:
        items = _load_queue()
        for item in items:
            if item["id"] == item_id:
                _delete_item_file(item)
        _save_queue([i for i in items if i["id"] != item_id])


def flush() -> int:
    """Try to send everything waiting in the offline buffer now.

    Returns how many items are still waiting (0 = all sent). Handy at the end
    of a short script; long-running agents don't need it, as waiting items are
    retried automatically every RETRY_SECONDS. While the dashboard has the
    agent paused, nothing is sent: held items wait for Start.
    """
    if PROBLEM or _paused:
        return len(_load_queue())
    sent = 0
    with _flush_lock:
        with _buffer_lock:
            items = _load_queue()
        for item in items:
            # Skip anything dropped from the buffer since we read it (e.g. when
            # the buffer was full), so it's never sent after all.
            with _buffer_lock:
                still_waiting = any(i["id"] == item["id"] for i in _load_queue())
            if not still_waiting:
                continue
            try:
                _deliver(item)
            except requests.RequestException as error:
                if _worth_retrying(error):
                    break  # still unreachable: keep this and everything after it, in order
                _warn(f"send a saved {item['kind'].replace('_', ' ')} (dropping it)", error)
            except OSError as error:  # its saved file went missing
                print(f"[dashboard] Dropping a saved {item['kind']}: {error}")
            else:
                sent += 1
            _remove_from_buffer(item["id"])
    waiting = len(_load_queue())
    if sent:
        print(f"[dashboard] Sent {sent} saved item(s) from the offline buffer ({waiting} still waiting).")
    return waiting


def pending() -> int:
    """How many items are waiting in the offline buffer."""
    return len(_load_queue())


def _start_sender() -> None:
    """Start the background thread that retries the buffer (once per program)."""
    global _sender_started
    if _sender_started or PROBLEM:
        return
    _sender_started = True

    def loop():
        while True:
            _retry_now.wait(RETRY_SECONDS)
            _retry_now.clear()
            if pending() and not _paused:
                flush()

    threading.Thread(target=loop, name="dashboard-buffer", daemon=True).start()


def _send_or_buffer(item: dict, what: str) -> bool:
    """Send an item now, or save it for later if the dashboard is unreachable.

    Returns True if the dashboard got it now. While older items are waiting,
    new ones queue up behind them so everything arrives in order.
    """
    global _announced_hold
    item.setdefault("id", uuid.uuid4().hex)
    item.setdefault("created_at", _now())
    if _paused and item["kind"] != "report":
        # Paused from the dashboard: hold it (reports still go through).
        waiting = _add_to_buffer(item)
        if not _announced_hold:
            print("[dashboard] Paused from the dashboard: holding outputs and monitor updates until Start.")
            _announced_hold = True
        print(f"[dashboard] Held {what} ({waiting} waiting).")
        return False
    if pending() and not (_paused and item["kind"] == "report"):
        waiting = _add_to_buffer(item)
        _retry_now.set()
        print(f"[dashboard] Queued {what} behind {waiting - 1} waiting item(s).")
        return False
    try:
        _deliver(item)
        return True
    except requests.RequestException as error:
        if not _worth_retrying(error):
            _warn(what, error)
            return False
        waiting = _add_to_buffer(item)
        _warn(what, error)
        print(f"[dashboard] Saved it to the offline buffer; will retry every {RETRY_SECONDS}s ({waiting} waiting).")
        return False


def report(message: str, kind: str = "log", data: dict | None = None) -> bool:
    """Show a message on this agent's dashboard card and activity log.

    kind: "log" (blue), "status" (green) or "error" (red).
    data: optional extra details, e.g. {"url": ...} or {"path": ...}.
    Returns True if the dashboard received it now. If the dashboard couldn't
    be reached, it's saved and sent later (see "Offline buffer" above).
    """
    if PROBLEM:
        return False
    body = json.loads(json.dumps({"message": str(message), "type": kind, "data": data}, default=str))
    return _send_or_buffer({"kind": "report", "body": body}, "send report")


def _is_file(content) -> bool:
    """True for things output() sends as a file: a path, bytes, or an open file."""
    return isinstance(content, (os.PathLike, bytes, bytearray)) or hasattr(content, "read")


def _read_file(content) -> tuple[str, bytes]:
    """Return (file name, file bytes) for a path, bytes, or an open file."""
    if isinstance(content, os.PathLike):
        with open(content, "rb") as handle:
            return os.path.basename(os.fspath(content)), handle.read()
    if isinstance(content, (bytes, bytearray)):
        return "output.bin", bytes(content)
    data = content.read()
    if isinstance(data, str):
        data = data.encode("utf-8")
    return os.path.basename(getattr(content, "name", "") or "output.bin"), data


def output(content, category: str) -> bool:
    """Send a result to this agent's Outputs section on the dashboard, like print().

    content:  what to show. Text, a number, a link ("https://..."), a list or
              dict, or a file: a pathlib.Path, an open file, or bytes (max 5 MB).
    category: a short name for this output channel, e.g. "articles" or "reports".
              The dashboard can filter by it, and you can pin one category so
              its latest output shows on the agent's card.

    Only what you pass to output() is sent. To log everything, send a short
    summary of it rather than the raw data. Returns True if the dashboard got
    it now. If the dashboard couldn't be reached, it's saved and sent later,
    with its original time (see "Offline buffer" above).
    """
    if PROBLEM:
        return False
    category = " ".join(str(category).split())
    what = f"send output to {category!r}"
    if _is_file(content):
        try:
            name, data = _read_file(content)
        except OSError as error:
            _warn(what, error)
            return False
        if len(data) > MAX_FILE_BYTES:
            print(f"[dashboard] Not sending {name!r} to {category!r}: it's over 5 MB.")
            return False
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        item = {"kind": "output_file", "category": category, "filename": name,
                "content_type": content_type, "_data": data}
    else:
        # default=str turns anything JSON can't handle (dates, objects...) into text.
        body = json.loads(json.dumps({"category": category, "content": content}, default=str))
        item = {"kind": "output", "body": body}
    return _send_or_buffer(item, what)


def set_monitor(link_or_pdf, label: str | None = None) -> bool:
    """Set what this agent's Monitor section shows. Only the latest one is shown.

    link_or_pdf:
      - a web address (http:// or https://) of where the agent's data lives,
        e.g. a Google Sheet or a Grafana board; or
      - a PDF (a pathlib.Path, an open file, or bytes; max 5 MB), shown inside
        the dashboard page. Call it again on a schedule (e.g. a daily summary)
        and the page swaps in the new PDF within about 10 seconds; or
      - None, to remove the monitor.
    Returns True if the dashboard got it now. If the dashboard couldn't be
    reached, the latest monitor is saved and sent later (see "Offline buffer").
    """
    if PROBLEM:
        return False
    if _is_file(link_or_pdf):
        try:
            name, data = _read_file(link_or_pdf)
        except OSError as error:
            _warn("set the monitor", error)
            return False
        if not data.startswith(b"%PDF-"):
            print(f"[dashboard] Not setting the monitor: {name!r} isn't a PDF.")
            return False
        if len(data) > MAX_FILE_BYTES:
            print(f"[dashboard] Not setting the monitor: {name!r} is over 5 MB.")
            return False
        item = {"kind": "monitor_file", "filename": name, "label": label, "_data": data}
    else:
        item = {"kind": "monitor", "body": {"url": link_or_pdf, "label": label}}
    return _send_or_buffer(item, "set the monitor")


def _check_commands(on_command=None) -> None:
    """Fetch waiting commands once, hand each to its handler, then mark it done.

    Start/Pause also update is_paused() straight away. Messages go to the
    accept_messages() handler if there is one, otherwise to on_command.
    """
    on_command = on_command or _command_handler
    try:
        commands = _send("GET", "/api/commands", LISTEN_TIMEOUT_SECONDS).json()
    except (requests.RequestException, ValueError) as error:
        _warn("check for commands", error)
        return
    if not isinstance(commands, list):
        return  # not the reply we expect (e.g. a proxy's page): ignore it
    for command in commands:
        if not isinstance(command, dict) or "id" not in command:
            continue
        name = command.get("command")
        if name in ("start", "pause"):
            _set_paused(name == "pause")
        try:
            if name == "message" and _message_handler is not None:
                _message_handler((command.get("payload") or {}).get("text", ""))
            elif on_command is not None:
                on_command(command)
        except Exception as error:  # a bug in a handler shouldn't stop the agent
            report(f"Failed to handle {name!r}: {error}", "error")
        try:
            _send("PATCH", f"/api/commands/{command['id']}", LISTEN_TIMEOUT_SECONDS, json={"status": "done"})
        except requests.RequestException as error:
            _warn(f"mark command {command['id']} done", error)


def listen(on_command, every: float | None = None) -> None:
    """Run on_command(command) when Start or Pause is pressed on the dashboard.

    command is a dict like {"id": 7, "command": "start", "payload": None, ...}.
    Commands arrive at check-ins, so the agent must check in: pass `every`
    (seconds) to start background check-ins at that rhythm (same as
    start_check_ins(every)), or call check_in() yourself, e.g. in a scheduled run.
    Messages go to the accept_messages() handler instead, if you set one.
    """
    global _command_handler
    if PROBLEM:
        print("[dashboard] Not listening for commands until the settings are fixed.")
        return
    _command_handler = on_command
    if every is not None:
        start_check_ins(every)


# Items left in the offline buffer by an earlier run are sent in the background.
if not PROBLEM and os.path.exists(_queue_path()) and pending():
    print(f"[dashboard] {pending()} item(s) waiting in the offline buffer from an earlier run; sending in the background.")
    _start_sender()
    _retry_now.set()

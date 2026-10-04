"""Demo agent: shows the dashboard connector in action.

It uses the very same connector/dashboard_connector.py that "Implement
connector" lets you download, so it behaves exactly like your own agents will.

What it does:
  1. Reports "Agent online" (Activity log).
  2. Says it accepts messages, so the dashboard's message box switches on,
     and replies to each one.
  3. Does a small piece of "work" every 20 seconds: it sends a "ticks" output.
     Press Pause on the dashboard and the work stops (wait_if_paused), and any
     output made just before is held until you press Start.
  4. Also sends "starts" (a number), "messages" (text) and "links" (a link)
     outputs, so you can try the Outputs section's filters and pin.
  5. Takes files you upload to its Inbox on the dashboard and keeps them in
     agent/received/ (a real agent would load them into its own database).

Before running it, add an agent on the dashboard ("Add Agent" card) and copy
its API key. Then (with the website running):
  macOS/Linux:  DASHBOARD_API_KEY=the-key python agent/agent.py
  Windows:      set DASHBOARD_API_KEY=the-key  then  python agent\\agent.py
Or put DASHBOARD_API_KEY in your .env file.

It talks to http://127.0.0.1:8000 unless you set DASHBOARD_URL, e.g. to
https://your-service.onrender.com or any other address your dashboard has.
"""

import os
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent

# Read the .env file that sits next to main.py, then default to the local
# dashboard if no address was given. Both must happen before the connector is
# imported, because it reads DASHBOARD_URL and DASHBOARD_API_KEY when imported.
load_dotenv(APP_DIR / ".env")
os.environ.setdefault("DASHBOARD_URL", "http://127.0.0.1:8000")

# Use the connector file from this project's connector/ folder.
sys.path.insert(0, str(APP_DIR / "connector"))
import dashboard_connector  # noqa: E402
from dashboard_connector import (  # noqa: E402
    accept_inbox,
    accept_messages,
    listen,
    output,
    report,
    start_check_ins,
    wait_if_paused,
)


# ===========================================================================
# YOUR AI LOGIC GOES HERE
# ---------------------------------------------------------------------------
# handle() is called once for every command you send from the dashboard.
# Replace the example replies below with whatever your real agent should do,
# use report() for status lines, and output(content, category) for results.
# ===========================================================================
starts = 0  # how many times Start was pressed, sent as an output


def handle(command: dict) -> None:
    """Start and Pause. (While paused, the connector holds outputs by itself.)"""
    global starts
    name = command["command"]
    if name == "start":
        starts += 1
        report("Starting work.", "status")
        output(starts, "starts")
    elif name == "pause":
        report("Pausing.", "status")
    else:
        report(f"Unknown command: {name}", "error")


def handle_message(text: str) -> None:
    """A message typed on the dashboard. A real agent might pass it to its LLM."""
    report(f"You said: {text}")
    output(f"Message received: {text}", "messages")


RECEIVED_DIR = Path(__file__).resolve().parent / "received"


def handle_inbox_file(item: dict, path: Path) -> None:
    """A file you uploaded to this agent's Inbox. Keep it (a real agent might
    load it into its own database instead). Once this returns, the dashboard
    deletes its copy."""
    RECEIVED_DIR.mkdir(exist_ok=True)
    target = RECEIVED_DIR / Path(item["filename"]).name  # just the name, never another folder
    shutil.copy(path, target)
    note = f' (note: "{item["note"]}")' if item.get("note") else ""
    report(f"Stored inbox file {item['filename']} in agent/received/{note}")
    output(f"{item['filename']}: {item['size']} bytes", "inbox files")


def main() -> None:
    if dashboard_connector.PROBLEM:
        sys.exit("Fix the setting above, then run the agent again.")

    print(f"Agent connecting to {dashboard_connector.DASHBOARD_URL} (Ctrl+C to stop)")
    listen(handle)
    accept_messages(handle_message)  # switches on the dashboard's message box
    accept_inbox(handle_inbox_file)  # takes files you upload to its Inbox
    # This demo runs all the time, so it checks in in the background. Every 5
    # seconds keeps Start/Pause and messages quick; a real agent might use 30-300.
    start_check_ins(every=5)
    report("Agent online", "status")
    output("https://github.com/", "links")  # an example link output

    tick = 0
    while True:
        wait_if_paused()  # a safe point: while paused, the agent waits here
        tick += 1
        output(f"Tick {tick}: did a small piece of work", "ticks")
        time.sleep(20)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAgent stopped.")

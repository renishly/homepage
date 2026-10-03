# Task: connect this agent to my Agent Dashboard

I have an AI agent (the code in this project) and a separate web dashboard where I monitor and control my agents. Please add a small "dashboard connector" to this agent, written in the agent's own language and style, so that:

1. The agent **sends its chosen results ("outputs")** to the dashboard through an `output(content, category)` function, much like `print()`. It keeps them wherever it already does as well.
2. The agent **reports its status** (online, paused, errors) to the dashboard's activity log.
3. The agent **receives commands** from the dashboard (Start, Pause, and text messages) and reacts to them.
4. Optionally, the agent **sets its monitor**. This is either a link to wherever its data lives (such as a Google Sheet or a dashboard), or a PDF the dashboard shows inside the page (such as a daily summary it regenerates on a schedule). Only the latest monitor is shown.

Don't change what the agent already does, beyond what's needed for this.

**If this agent is written in Python,** there's a ready-made connector you can use instead of writing one: the dashboard's **Implement connector → Code** download, `dashboard_connector.py`. It needs only `requests` and implements everything described below. Ask me for it, then integrate it, and still do everything else in this prompt. For other languages, build the equivalent from the description below.

## First: ask me for these values

Before writing any code, **ask me for the following and wait for my answers.** Don't guess them or invent placeholder values.

1. **The dashboard's address (base URL).** It depends on where my dashboard runs:
   - on my own computer, e.g. `http://127.0.0.1:8000`;
   - deployed on Render, e.g. `https://my-service.onrender.com`;
   - on another host or a custom domain, e.g. `https://dashboard.example.com`.

   This prompt was downloaded from `{{DOWNLOADED_FROM}}`. Offer that as a suggestion, but confirm it with me: it may be a local test address that this agent can't reach. Use the bare address, without `/dashboard` on the end.
2. **This agent's API key.** I get it from the dashboard's "Add Agent" card, or "View key" in the agent's settings (the gear next to its name). Ask whether I'd rather give it to you or set it myself.
   - Either way, store it in an environment variable or a git-ignored config file (e.g. `.env`). **Never hard-code it in source files, commit it, print it, or write it to logs.**
   - If I set it myself, tell me exactly where to put it.
3. **Where this agent will run** (my computer, a server, a cloud function, etc.), so you can check it can actually reach the dashboard's address.

Read the values from the environment variables `DASHBOARD_URL` and `DASHBOARD_API_KEY`. If you also add a config file, it should be the fallback.

## The dashboard's API

- Every request goes to `<DASHBOARD_URL><path>` and must send the header `X-API-Key: <DASHBOARD_API_KEY>`.
- The key identifies this agent, so no agent name or ID is needed in requests.
- Request bodies are JSON, except the two file uploads, which are multipart forms.

| Request | Body | Response |
|---|---|---|
| `POST /api/events` | `{"message": "text", "type": "log", "data": {...} or null}` | `201` with the saved event |
| `GET /api/commands` | none | `200` with a list of this agent's waiting commands, oldest first |
| `PATCH /api/commands/{id}` | `{"status": "done"}` | `200`, or `404` if the command doesn't belong to this agent |
| `POST /api/outputs` | `{"category": "articles", "content": <text, number, link, list or dict>}` | `201` |
| `POST /api/outputs/file` | multipart form: `category` (text) and `file` (the file, max 5 MB) | `201`, or `413` if too big |
| `POST /api/state` | `{"check_in_every": <seconds>, "accepts_messages": true or false}`; both optional | `200` with `{"paused": true/false, "accepts_messages": ..., "check_in_every": <seconds>}` |
| `PUT /api/monitor` | `{"url": "https://...", "label": "Results sheet"}`, or `{"url": null}` to remove it | `200` with `{"url", "label", "applied"}` |
| `POST /api/monitor/file` | multipart form: `file` (a PDF, max 5 MB) and optional `label` | `200` with `{"filename", "label", "applied"}`, `413` if too big, `422` if not a PDF |

- `type` is `"log"` (shown blue), `"status"` (green), or `"error"` (red).
- `data` is optional extra detail, such as `{"url": "..."}` or `{"path": "..."}`.
- A command looks like `{"id": 7, "command": "message", "payload": {"text": "hi"}, "status": "pending", "created_at": "..."}`. `command` is `"start"`, `"pause"` or `"message"`. `payload` is only set for messages.
- How the dashboard shows an output's `content`:
  - numbers as numbers;
  - text that is a single `http(s)://` address as a clickable link;
  - lists and dicts as formatted JSON;
  - anything else as text.
- Files are stored on the dashboard. PNG, JPEG, GIF and WebP images are shown inline; other files are offered as downloads.
- Text `content` can be up to 20,000 characters, and a monitor `label` up to 50.
- `category` is 1 to 50 characters. It sorts outputs into channels the user can filter by. The user can also pin one category, so its latest output shows on the agent's card in the grid.
- The monitor link must be `http://` or `https://`.
- `POST /api/events`, `POST /api/outputs`, `POST /api/outputs/file`, `PUT /api/monitor` and `POST /api/monitor/file` also accept an optional `created_at` (an ISO 8601 date and time in UTC, e.g. `2026-10-03T08:00:00Z`). It's sent as a JSON field, or a form field for the file uploads. It's when the item was really made, so items sent late land at their real time. Times in the future are treated as "now", and a late monitor update older than the current monitor is ignored.
- A wrong or missing key gets `401`. Input the dashboard can't accept (an empty or over-long category, over-long content, a non-PDF monitor file, a bad `created_at`) gets `422`.
- `applied: false` from a monitor update means it was older than the current monitor and was ignored (this only happens for late updates).

## It must work wherever the dashboard runs

The same code must work whether the dashboard is local, on Render, or on another host. Only `DASHBOARD_URL` changes. So:

- **Tidy the address.** Remove a trailing `/` or `/dashboard` from `DASHBOARD_URL`. If it doesn't start with `http://` or `https://`, print a clear setup message and don't connect.
- **Never follow redirects automatically.** A redirect (commonly `http://` to `https://` on Render and most hosts) can turn a POST into a GET and silently lose reports. If a request is redirected, print a warning saying which address to use instead.
- **Warn about plain http.** If the address uses `http://` and isn't `localhost` or `127.0.0.1`, warn that the key is sent unencrypted and `https://` should be used.
- **Allow for a sleeping site.** Free Render sites sleep when idle and take about a minute to wake. Use short timeouts (about 10 seconds) for reports sent from the agent's main work, longer ones (about 30 seconds) for the background command check, and just retry later.
- **Check the address can be reached.** `127.0.0.1`/`localhost` only works when the agent runs on the same computer as the dashboard. If the agent runs elsewhere, tell me it needs the deployed address.
- **Handle missing settings.** If either value is missing or still a placeholder, print one clear message saying what to set. Then keep the agent running without the dashboard rather than crashing.

## Never lose outputs: an offline buffer

The dashboard can be unreachable for a while: no internet, a redeploy, a sleeping free site, or a server error. Whatever the agent sends during that time must not be lost:

- Give every item (output, report, monitor update) a `created_at` timestamp when it's made, and send it with the item.
- If sending fails with a connection error, a timeout, HTTP `429`, or any `5xx`, save the item to a local buffer and resend it later.
  - Use a small file or folder next to the agent, e.g. `dashboard_buffer/`, with one JSON line per item. Copy files into the buffer folder, since the original might change or be deleted.
  - Don't buffer errors that retrying can't fix (`401`, `404`, `413`, `422`, redirects); report those once instead.
- The buffer must **survive the agent restarting**. Load any waiting items at startup.
- Retry in the background, about every 15 seconds. Send waiting items **oldest first**, and stop at the first temporary failure so the order is kept.
  - While items are waiting, queue new items behind them rather than sending them first.
  - Remove each item (and its copied file) only after the dashboard accepted it.
  - Make sure two retries never run at the same time, so nothing is sent twice.
- Keep only the newest pending monitor update; older ones are pointless.
- Cap the buffer (for example 1,000 items or 100 MB of files), dropping the oldest with a warning.
- Provide a `flush()` function that tries to send everything now. For agents that run as short scheduled scripts, call it before the script exits; anything still waiting is sent on the next run.

## Start, Pause and messages

- **Check in at a rhythm that suits this agent**, with `POST /api/state`, sending `check_in_every`: how many seconds until the next check-in (1 to 604800, i.e. a week). The dashboard shows the agent as **online** while it keeps to that rhythm, plus half an interval of slack (at least 30 seconds). Without `check_in_every`, it expects a check-in every 60 seconds.
  - **An agent that runs all the time:** check in in the background every few seconds to minutes. Shorter means Start/Pause and messages reach it faster.
  - **An agent that runs on a schedule** (hourly, daily, as a cron job or cloud function): check in once at the start of each run, with `check_in_every` set to the schedule, e.g. `3600` for hourly. It then stays "online" between runs.
  - Ask me which kind this agent is if it isn't obvious from the code.
- **Each check-in also handles waiting commands:** after `POST /api/state`, `GET /api/commands` and handle them (see the listener below). The `POST /api/state` reply says whether the dashboard has the agent **paused** (from its Start/Pause buttons).
- Provide `check_in(every=None)` (one check-in now, remembering `every`) and `start_check_ins(every)` (background check-ins at that rhythm), so the agent's own code decides.
- **While paused, hold outputs and monitor updates.** Put them in the offline buffer without sending, and send them, in order and with their original times, as soon as a check-in says the agent isn't paused. Status reports (`report()`) still go through, so errors stay visible.
- **Provide `wait_if_paused()`** (waits while paused, checking in every few seconds meanwhile to notice Start) and `is_paused()`. Call `wait_if_paused()` at safe points in the agent's main loop, such as before starting the next task, so Pause also stops the work.
- A `start`/`pause` command arriving through `GET /api/commands` should update the pause state straight away, too.
- **Messages are opt-in.** The dashboard keeps its message box switched off until the agent says it accepts messages, by sending `"accepts_messages": true` in its check-ins.
  - Provide `accept_messages(on_message)`. It registers a handler that receives each message's text, turns that flag on, and checks in straight away so the box switches on. Messages then arrive at the agent's check-ins.
  - Only call it if this agent can do something useful with free-text messages, for example pass them to its LLM as an instruction. Ask me if you're unsure.
  - Send `"accepts_messages": false` (or never call it) otherwise.

## What to build

1. **An `output(content, category)` function, the most important part.** It should feel like `print()`: whatever is passed in is sent to the dashboard's Outputs section under that category.
   - `content` can be text, a number, a link, a list/dict, or a file (a path, an open file, or bytes). Files go to `/api/outputs/file`; everything else goes to `/api/outputs` as JSON. Turn anything else into text.
   - Check a file's size before uploading (max 5 MB) and skip it with a warning if it's too big.
   - It must **never raise or crash the agent**. It returns whether the dashboard received it right away; if not, the item goes to the offline buffer (above).
   - **Then use it selectively.** Wrap only the results that matter to me, each with a clear, stable category name (for example `"articles"`, `"reports"`, `"daily summary"`). Don't send raw logs or every intermediate step. Where the agent produces a lot of data, send a short summary (counts, highlights, a link to the full data) rather than everything.
   - Show me which outputs and categories you chose, so I can adjust them.
2. **A `set_monitor(link_or_pdf, label=None)` helper.**
   - A web address goes to `PUT /api/monitor`. A PDF (a path, an open file, or bytes) goes to `POST /api/monitor/file`; check it starts with `%PDF-` and is at most 5 MB first. `None` removes the monitor.
   - Each call replaces the previous monitor, and the dashboard logs it in the activity log.
   - If the agent already writes its data somewhere I can view (a Google Sheet, a database dashboard, a results page), call it once at startup with that address.
   - If the agent produces a document on a schedule (a daily summary, a report), call it with the new PDF each time; the dashboard shows it inside the page.
   - Ask me if you're not sure which to use.
3. **A `report(message, type="log", data=None)` helper** that sends an event (status lines for the activity log).
   - It must **never raise or crash the agent**: catch network errors and print a one-line warning with a helpful hint (`401`: check the key; `404`: check the address; timeout: the site may be waking up).
4. **Command handling at each check-in.**
   - At each check-in, `GET /api/commands`. For each command, call a handler, then `PATCH` it to `done`.
   - Route `message` commands to the `accept_messages` handler, passing the text. Route `start`/`pause` to an optional `on_command` handler, after updating the pause state.
   - Do this even if the handler fails; report the failure as an `"error"` event.
   - A command that isn't marked `done` (e.g. the `PATCH` failed) is delivered again on the next check, so handling the same command twice must be harmless.
   - For background check-ins, run them in a thread, async task, or whatever suits this codebase, so they **never block the agent's main work**.
   - If the reply isn't a list of commands, ignore it.
5. **Wire up Start/Pause and messages** as described in "Start, Pause and messages" above:
   - call `wait_if_paused()` at the agent's safe points;
   - report `"Paused"` / `"Started"` as `"status"` events when the state changes;
   - if the agent can use messages, call `accept_messages(on_message)` with a handler that treats the text as an instruction or note.
6. **Report status to the activity log** with `report()`:
   - `"Agent online"` as a `"status"` when the agent starts;
   - errors, as `"error"` events;
   - occasional progress, as `"log"` events.

   Results belong in `output()`, not here. The dashboard already adds a timestamped activity line for every output and monitor update, so don't report those separately.

   Keep messages short (one line) and don't send more than about one event per second.

## When you're done

- Tell me which files you changed or added, and which outputs and categories the agent now sends.
- Tell me exactly how to set `DASHBOARD_URL` and `DASHBOARD_API_KEY` for running locally and for running wherever the agent will be deployed.
- Tell me how to check it works: run the agent, and its card on the dashboard should turn **online** and show "Agent online" within a few seconds. Its outputs should appear in the **Outputs** section of its page, and clicking **Pause** and **Start** on the card should change the agent's behavior.

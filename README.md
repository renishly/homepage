# Homepage

Your personal website, version 1:

- **`/`**: the home page. Signed out: your name with its base on the screen's centre line, a **Login** button below it, and an "as guest?" link that slides out from under it on hover (always shown on phones). Signed in: a "tech tree" of places to go, with you (Ren, or Guest) as the root on the left, joined by dashed lines to **Dashboard**, **Portfolio** and **Data tracking** (the last two marked "soon"). Each card in the tree is called a **tech**. Right after signing in, the Login button glides into the root's place and the tree builds itself. The tree lives at `/tree`; the front page `/` always shows the name and Login (Login goes straight into the tree if you're signed in).
  - Hover the root tech (hold it, on a phone) and it reads "Log out / Hold to sign out". A click goes back to the front page, still signed in. Holding it rewrites "Log out" into "Sign out", a letter at a time, and then signs this device out (holding Space does the same from the keyboard).
  - As Ren, hovering (holding) the root's badge spins it into a cog; clicking the cog switches **developer mode** on or off. It always starts off when the tree opens.
  - In developer mode, clicking a leaf tech opens its **settings** instead of its page: a three-stop slider sets it to **Open** (guests can open it), **Private** (guests see it greyed out but can't open it) or **Hidden** (guests don't see it), and you can write its description (up to 120 characters; empty restores the original). Also in developer mode, **drag a leaf tech** up or down to rearrange the techs; the order is saved, and guests see it too. Pages with one page-wide API key (for now, Data tracking) also show it there, to view, set or randomize. Only you can change these; the server checks, and keeps guests out of a Private or Hidden dashboard.
- **`/dashboard`**: a password-protected dashboard for your AI agents.
  - Agents appear as cards in a 3 × 3 grid, with page buttons when they don't all fit.
  - Each card has Start (▷) and Pause (‖) buttons, and the last cell is an **Add Agent** card.
  - A folder sidebar shows **All Agents** or just the agents tagged with one folder. It can be folded out of the way, and its corner has an ⓘ guide and **Implement connector** downloads.
  - Click a card to open that agent's page: rename it, tag it with folders, send commands, read its activity log, or delete it.
- **`/api/...`**: a small API your agents use to talk to the site. Any agent can read every agent's outputs, activity and monitor, but can only delete its own.

Everything is written in Python. The pages use HTML attributes from
[HTMX](https://htmx.org) and [Alpine.js](https://alpinejs.dev) instead of
hand-written JavaScript, and [daisyUI](https://daisyui.com) with [Tailwind CSS](https://tailwindcss.com) for styling.

## How the pieces connect

```text
 agents ──POST /api/outputs───────▶ ┌──────────┐ ◀──GET /dashboard (grid)──── your browser
 (each   ──POST /api/events───────▶ │ database │ ◀──GET /dashboard/agents/N─
 with its◀─GET /api/commands──────── │ (owned by│ ◀──POST .../agents/N/command
 own key)──PUT /api/monitor───────▶ │ the site)│
          ◀─GET /api/agents/...─────── │          │   (read any agent's data)
          ──DELETE /api/outputs...──▶ │          │   (delete its own data only)
                                     └──────────┘
```

**One shared database, reached only through the API.** The database belongs to the dashboard website: a SQLite file (`local.db`) on your computer, or the Postgres database Render creates. Agents never connect to it themselves and never need its password. They read and write through the website's API, using their own key, and the website stores everything. This means:
- an agent can run anywhere that can reach the website;
- a leaked agent key lets someone read every agent's outputs, activity and monitor, and post or delete as that one agent (never as another), until you replace the key;
- moving the dashboard to another host or database never requires changing an agent.

These are the tables. Each side reads what the other writes:

- **Agent**: one row per agent, added with the dashboard's **Add Agent** card.
  - It stores a display name, which you can rename at any time, and an optional description that every agent can read.
  - It also stores the agent's API key in two forms, never as plain text: a *fingerprint* (SHA-256 hash), used to recognise the agent, and an *encrypted copy*, so **View key** can show it again. The encryption secret (`KEY_ENCRYPTION_SECRET`) lives in `.env`, not in the database, so a copied database doesn't reveal any keys.
- **Event**: messages from an agent to you, such as "Agent online" or "Error: ...".
- **Command**: messages from you to one agent (`start`, `pause`, or `message` with some text).
- **Folder** and **AgentFolderLink**: your folders, and which agents are tagged with which folder. An agent can be in several folders.
- **Output** and **OutputFile**: results an agent chose to share with `output(content, category)`. Files are stored in the database itself, up to 5 MB each, so they survive restarts on any host.
- **CategoryNotification**: which output categories have the bell turned on.
- **InboxItem** and **InboxChunk**: files you uploaded to an agent's Inbox, stored in 1 MB pieces, deleted once the agent has taken them.
- **TechSetting**: each tech's developer-mode settings (Open / Private / Hidden, and a page-wide API key, encrypted).
- **LoginSession**: one row per signed-in device (only a fingerprint of its token), deleted when it logs out.

**Each agent has its own API key.** The agent sends it in the `X-API-Key` header, and the site uses it to work out which agent is calling. That's why renaming an agent never disconnects it.

Each agent decides how often it **checks in**: every few seconds, every few minutes, hourly, or daily. A card shows **online** while its agent keeps to its own rhythm (plus half an interval of slack, at least 30 seconds), so an hourly agent stays online between runs. It shows **offline** once a check-in is overdue, and **never connected** before the first one. Agents that don't say how often they check in are expected every 60 seconds.

Here's the flow:

1. An agent posts an event, and the dashboard shows it. The grid, Activity and Outputs check for changes every 3 seconds; the server answers with an empty "nothing changed" (204) unless something did, so the page is only redrawn when needed. Checks pause while the tab is hidden and resume when you come back.
2. You click **Start** on a card, or type a message on an agent's page, and a pending command is saved for that agent.
3. Each agent picks up its own pending commands when it checks in (at whatever rhythm it chose), handles each one, and marks it `done`.

| File | What it does |
|---|---|
| `main.py` | All the routes (pages, dashboard, API). |
| `db.py` | Database connection and the tables (`Agent`, `Folder`, `AgentFolderLink`, `Event`, `Command`, `Output`, `OutputFile`, `CategoryNotification`). |
| `security.py` | The dashboard login (sign-in sessions), CSRF protection, the per-agent API-key check, key encryption, and the agent editing password check. |
| `static/tailwind.css` | The Tailwind CSS styles the templates use, built ahead of time from `tailwind.input.css` (see "Changing the styles"). |
| `static/home.js` | Draws the home page tree's dashed lines, and plays its build right after signing in. |
| `static/vendor/` | HTMX and Alpine.js, served by this site (their versions are in the file names). |
| `static/fonts/` | The IBM Plex Mono font, served by this site, with its licence (`OFL.txt`). |
| `static/grid.js` | Makes the background grid carry on from where it was on the previous page, and plays its rush on each page load. |
| `static/theme.css` | The site's look: the "codepaper" theme (black IBM Plex Mono text on `#ffff83` yellow paper, cards with thin black borders and hard shadows, vibrant yellow `#ffe600` hovers, a tilted background grid that drifts and rushes forward on each page load) and all the animations (page transitions, a typed home title, pressing buttons, snapping pop-ups, sliding toasts, a pulsing "online" light). Change colours here: they're the variables at the top. Animations switch off for visitors who ask their device to reduce motion. |
| `templates/` | The HTML pages (Jinja2). |
| `templates/login.html` | The dashboard's login page. |
| `templates/dashboard.html` | The grid page, with the folder sidebar and the Add Agent window. |
| `templates/agent.html` | One agent's page. |
| `templates/partials/` | Pieces the pages reuse or refresh: the grid (`agent_grid.html`), the Add Agent form and its result (`add_agent_form.html`, `agent_created.html`), the agent's name, tags and settings pop-up (`agent_header.html`), the control buttons' icons (`icons.html`), its running/paused badge (`run_state.html`), a shown or replaced API key (`api_key.html`), the two connection values (`connection_values.html`), the Outputs section (`outputs.html`, with its Filter rows `outputs_options.html`, list `outputs_list.html`, Filter button text `outputs_summary.html`, and `output_macros.html` for showing each kind of output), the Monitor section and its pin button (`monitor.html`, `monitor_pin.html`), and the Activity list (`events.html`). |
| `agent/agent.py` | A demo agent, built on the same connector you download, for trying the dashboard out. |
| `connector/` | The two downloads offered by **Implement connector**: `dashboard_connector.py` (code) and `connector_prompt.md` (a prompt for an AI assistant). Both work with a dashboard anywhere. The address and key are placeholders, and the only thing filled in on download is a "downloaded from" hint. |
| `tests/` | Automated tests and the test report. |
| `render.yaml` | Tells Render how to deploy the site and its database. |

## Local setup

You need Python 3.10 or newer. Run these from this folder (the one containing `main.py`).

1. **Create and activate a virtual environment**

   macOS/Linux:
   ```bash
   python3 -m venv .venv
   ```
   ```bash
   source .venv/bin/activate
   ```
   Windows (PowerShell):
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

2. **Install the requirements**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create your `.env` file** from the example:
   ```bash
   cp .env.example .env
   ```
   (On Windows: `copy .env.example .env`.)

4. **Choose your secrets** in `.env`:
   - a `DASHBOARD_USER` and a strong `DASHBOARD_PASSWORD`;
   - an `AGENT_EDIT_PASSWORD`. You'll type it to delete an agent, or to view or replace an agent's API key. Make it different from your dashboard password. If it's empty, those actions are turned off.
   - a `KEY_ENCRYPTION_SECRET`, used to encrypt agents' API keys. Generate it with the command below. **Don't change it later**: keys saved with an old secret can no longer be viewed, and you'd need to use **Replace key** on each agent.

   You don't need to make up agent API keys here. The dashboard's Add Agent card generates one for each agent (see below). If you'd rather make your own key, or need a `KEY_ENCRYPTION_SECRET`, this prints a strong random value:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   `.env` holds your real secrets. It's listed in `.gitignore`, so it never ends up on GitHub.

## Running the site

```bash
fastapi dev main.py
```

Then visit:

- <http://127.0.0.1:8000/>: the home page.
- <http://127.0.0.1:8000/dashboard>: the dashboard. It sends you to the login page first; sign in with your `DASHBOARD_USER` and `DASHBOARD_PASSWORD`.
- <http://127.0.0.1:8000/docs>: interactive API docs. Click **Authorize** and paste an agent's API key to try the API by hand.

`fastapi dev` restarts automatically when you edit a file. Locally, data is stored in `local.db` (a SQLite file).

## Connecting your own agent

The idea: your agents are separate programs, such as a news finder or a PDF maker, running wherever you like and saving their outputs where they always have. The dashboard is a window onto them:

1. **Build your agent** however you like.
2. On the dashboard, use **Add Agent** to create its slot and get its **API key**.
3. Click **Implement connector** (bottom-left of the sidebar) and choose a format:
   - **Code**: download `dashboard_connector.py` and put it next to your Python agent.
     - Fill in the two values marked **REPLACE THIS PLACEHOLDER**, or set them as environment variables (better for the key).
     - Then use the functions described under "The connector's functions" below.
   - **Prompt**: download a prompt and give it to an AI coding assistant. It asks you for the address and key, then adds the connector to your agent in whatever language the agent uses.
4. Run your agent. Its card turns **online** and starts showing what it does.

**The two values every connector needs:**

| Setting | What to use |
|---|---|
| `DASHBOARD_URL` | The dashboard's address, without `/dashboard` on the end: `http://127.0.0.1:8000` if it runs on the same computer as the agent, `https://your-service.onrender.com` on Render, or your own domain on any other host. |
| `DASHBOARD_API_KEY` | The agent's key, from **Add Agent** or **View key** on *that* dashboard. Local and deployed dashboards have separate databases, so each has its own agents and keys. |

The same connector works with all three; only these values change. After adding an agent, or viewing or replacing its key, the dashboard shows both values ready to copy. Some things to know:
- `127.0.0.1` only works for an agent running on the same computer as the dashboard.
- If you give an `http://` address for a site that uses `https://`, the connector tells you to switch.
- It warns if a key would be sent over plain `http` to a remote site.
- If the dashboard is down, asleep or misconfigured, it prints a one-line warning and your agent carries on.

### The connector's functions

| Function | What it does |
|---|---|
| `output(content, category)` | **The main one.** Like `print()`, but whatever you pass appears in the agent's **Outputs** section, sorted by `category`. `content` can be text, a number, a link, a list/dict, or a file (a `pathlib.Path`, an open file, or bytes; max 5 MB). |
| `report(message, kind)` | A status line for the **Activity** log, such as "online", "paused" or an error. |
| `start_check_ins(every)` | For agents that run all the time: check in automatically every `every` seconds, in the background. Start/Pause and messages arrive at each check-in, so shorter means quicker reactions. |
| `check_in(every)` | For agents that run on a schedule (hourly, daily…): check in once, at the start of each run. `every` tells the dashboard how often to expect it. |
| `listen(on_command)` | Optional: runs your own code when Start or Pause is pressed (e.g. to report "Paused"), at check-ins. |
| `wait_if_paused()` / `is_paused()` | Call `wait_if_paused()` at safe points in your agent's loop so **Pause stops its work**; it waits until Start. `is_paused()` just tells you the state. |
| `accept_messages(on_message)` | Switches on the dashboard's message box for this agent. `on_message(text)` gets each message, for example to pass it to the agent's LLM. |
| `flush()` / `pending()` | Send anything waiting in the offline buffer now / how many items are waiting. |
| `accept_inbox(on_file)` | Takes files you upload to this agent's **Inbox**. `on_file(item, path)` gets each one at check-ins (`path` is a temporary copy; `item["note"]` is your note). Store the data your own way; once it returns, the dashboard deletes its copy. Raise an error or return `False` to keep the file for next time. `inbox()`, `download_inbox(item)` and `confirm_inbox(item)` do the same by hand. |
| `set_monitor(link_or_pdf, label)` | Sets what the agent's **Monitor** shows (only the latest one is kept): a link to where its data lives, such as a Google Sheet, or a **PDF shown inside the page**, such as a daily summary or report the agent regenerates on a schedule. |

**Nothing is lost while the dashboard is unreachable.**
- If the dashboard can't be reached (no internet, a restart, a sleeping free site, a server error), `output()`, `report()` and `set_monitor()` save what they couldn't send. It goes in a `dashboard_buffer` folder next to the connector file (or wherever `DASHBOARD_BUFFER_DIR` points).
- Saved items are sent automatically, every 15 seconds, oldest first, once the dashboard is back. Each keeps its original time and is marked "(delivered late)" in the Activity log.
- The buffer survives the agent restarting.
- **Short scripts** (run on a schedule, then exit) should call `flush()` at the end; anything still waiting goes on the next run.
- Mistakes that retrying can't fix, such as a wrong key or a file over 5 MB, aren't saved; they're printed once instead.
- The buffer holds up to 1,000 items or 100 MB of files, then drops the oldest.

Note that the buffer only protects against the *dashboard* being unreachable. If the agent runs on a computer that's switched off, the agent isn't running either.

**How Start, Pause and messages work:**
- The dashboard never touches your agent's program directly. **Start** and **Pause** set a state that the agent picks up at its next check-in, and the card and agent page show a **running/paused** badge. An agent that checks in hourly therefore reacts within the hour; use `wait_if_paused()` (below) for an instant reaction while it's running.
- **While paused, logging pauses by itself.** `output()` and `set_monitor()` hold what they're given and send it, in order and at its original time, when you press Start. `report()` still goes through, so you still see status lines and errors. This needs no code in your agent.
- **To pause the work as well,** call `wait_if_paused()` at safe points in the agent's loop. Only the agent knows where it's safe to stop.
- **Messages are opt-in.** The message box stays switched off until the agent calls `accept_messages(on_message)`, which tells the dashboard it takes messages. A good fit is an agent with an LLM that can act on instructions like "focus on earnings news". The dashboard notices within 5 seconds and switches the box on.

**Choosing what to output:** only what you wrap in `output()` reaches the dashboard, so keep it to the results you care about. If an agent produces lots of data, send a short summary (counts, highlights, a link to the full data) instead of all of it.

Use a different `category` for each kind of result, for example `"articles"`, `"daily summary"` or `"reports"`.

### Reading other agents' data, and deleting your own

**Any agent can read every agent's data, but can only delete its own.** So agents can build on each other's work (one agent reads the articles another found), and each keeps its own corner tidy.

| Function | What it does |
|---|---|
| `agents()` | Every agent on the dashboard, A to Z: id, name, its description (what it does, in your words), whether it's you, folders, online, paused, check-in rhythm, and its monitor. |
| `read_agent(agent="me")` | One agent, plus its output categories with counts. |
| `read_outputs(agent="me", category=None, since=None, limit=50, offset=0)` | An agent's outputs, newest first, with `content` as it was sent (text, a number, or a list/dict). `category` can be one name or a list. |
| `read_activity(agent="me", kind=None, since=None, limit=50, offset=0)` | An agent's Activity log, newest first; `kind="error"` for just its errors. |
| `read_monitor(agent="me")` | What an agent's Monitor shows: a link, or a PDF. |
| `download(item, save_to=None)` | The bytes of a file output or a PDF monitor (and optionally saves them). |
| `delete_output(item)` / `delete_outputs(category=None, before=None, everything=False)` | Delete one or many of **this agent's** outputs, and their files. Deleting all of them needs `everything=True`. |
| `delete_event(item)` / `delete_activity(before=None, everything=False)` | Delete one or many of this agent's Activity lines. |
| `set_monitor(None)` | Remove this agent's Monitor. |

- `agent` is `"me"`, another agent's id, or its exact name (ids never change; names can be renamed).
- Trying to delete another agent's output or activity line is refused (`403`) and changes nothing. Bulk deletes only ever touch the calling agent's own data.
- Every delete leaves an orange **delete** line in that agent's Activity log (e.g. `Deleted 3 outputs in "drafts"`), so you can always see what an agent removed.
- Reads never include API keys, or the Start/Pause/messages you sent an agent.
- Reads and deletes go straight to the dashboard: they aren't held while paused, and aren't saved in the offline buffer. A delete only affects what the dashboard already has.
- A handy use: tidy up old data, e.g. `delete_outputs(before=datetime.now(timezone.utc) - timedelta(days=30))`, so the free database doesn't fill up.

## Using the dashboard

### The Inbox: giving an agent files

On an agent's page, the **Inbox** button (third in Controls) opens a window where you upload files for that agent, up to 50 MB each, with an optional note.
- The files wait in the dashboard's own database, where only that agent can see them.
- At its next check-in the agent downloads each one, stores the data its own way (its own database, a folder...), and confirms. The dashboard then deletes its copy, so the inbox is only a short stop.
- If the agent fails to store a file, it doesn't confirm, and the file is offered again at its next check-in. Nothing is lost.
- Until you remove it, a waiting file shows in the window: click its name to download it again, or **Remove** to take it back out.
- Activity shows each step: "Inbox: you uploaded…", then "Inbox: agent received…".
- Agents switch their inbox on with `accept_inbox(on_file)` (see the connector's functions). You can upload before that; the window warns that the files will wait.
- Waiting files on all agents together can take up to 200 MB, to protect the free database. Large files are stored in 1 MB pieces, so they never need much memory on the server.

- **Add an agent:** click the **Add Agent** card (the last cell of the grid).
  - Give the agent a name. Leave the key box blank to have a key generated, or paste a key of your own (at least 20 characters, no spaces).
  - The key is shown right away. You can see it again later with **View key** in the agent's settings.
  - If you add an agent while a folder is open, it goes into that folder.
- **Folders:** use **+ Add folder** in the sidebar to make a folder, then click it to see only its agents. Inside a folder you can rename it or delete it. Deleting a folder keeps its agents.
- **Sidebar:** on a wide screen, **«** folds the sidebar away and **☰ Folders** brings it back. Your browser remembers the choice. On a phone the sidebar slides in from **☰ Folders**. The **ⓘ** button in its bottom-left corner explains how the dashboard works.
- **Agent page:** click a card to open it. Under its name and folder tags (click a tag to open that folder), the page shows, top to bottom:
  - **Monitor**: the latest thing the agent set with `set_monitor()`, with its own **📌** to pin it to the grid card.
    - **A PDF** is shown right in the page with your browser's PDF viewer, so you can scroll, zoom and search it. When the agent sends a new PDF (say, each morning's summary), the page swaps it in within about 10 seconds. It doesn't reload while nothing has changed, so it won't jump while you read. Only the latest PDF is kept. Some phones only show the first page inside a page; use **Open ↗** there.
    - **A link** has **Show here** to try viewing it inside the page. Many sites, including normal Google Sheets links, refuse to be shown inside another page; use **Open ↗** for those, or Google Sheets' *File → Share → Publish to web* link.
  - **Outputs**: what the agent sent with `output()`. **Nothing is shown until you choose**, except that a pinned category starts ticked. Click **Filter** next to the heading:
    - **Show**: tick **All**, or any mix of categories.
    - Each category has **🔔**, which marks it for notifications. For now this only saves the setting; a future Discord bot will send the messages.
    - Each category also has **📌**, which pins it so its latest output shows on the agent's card in the grid. One thing per agent can be pinned (a category or the Monitor); pinning something else moves the pin, and clicking the pinned one again unpins it.
    - **Sort by** Date, Category name or Content, **Descending** (newest first / Z–A) or **Ascending**.
    - Your choices apply straight away. The list keeps refreshing every 3 seconds with them, and the Filter panel stays open while you choose.
    - Each visit starts fresh, with nothing chosen.

    Images (PNG, JPEG, GIF, WebP) appear in the page; other files are downloads.
  - **Activity**: the agent's status lines from `report()`, plus a timestamped line every time it sends an output (`output`) or its monitor changes (`monitor`).
  - **Controls** sit in a column on the right that stays in view while you scroll: icon buttons for Start (▷), Pause (‖) and the **Inbox** (a tray with an arrow, showing how many files are waiting), then a message box with a paper-plane Send button. Hover over a button to see its name. On a phone they're a bar fixed to the bottom of the screen; tap the speech bubble to type a message. The message box is greyed out until the agent says it accepts messages. The badge next to the name shows whether the agent is **running** or **paused**.

  Everything you can change is behind the **gear icon** next to the name, which opens **Agent settings**:
  - **Name**: rename the agent. It stays connected, because its key doesn't change.
  - **Description**: a few sentences on what the agent does (up to 1,000 characters), shown under its name. You can also write it on the **Add Agent** card. Every agent can read every description, so they know what the others are for. Save it empty to remove it.
  - **Folders**: **+ Add tag** puts the agent in a folder, and the × on a tag takes it out again.
  - **Monitor**: set, change or remove the monitor link. Saving a link replaces whatever the monitor showed, including a PDF. PDFs can only come from the agent (`set_monitor(Path("summary.pdf"))`). The most recent change wins.
  - **API key**:
    - **View key** shows the current key once you enter your `AGENT_EDIT_PASSWORD`.
    - **Replace key** gives the agent a new key, generated or one you type, also with that password. The old key stops working straight away, so restart the agent with the new key.
    - Closing settings clears any key shown on the page.
  - **Danger zone**: **Delete agent** first asks "are you sure", then needs your `AGENT_EDIT_PASSWORD`. Deleting removes the agent, its outputs (and their files), its activity log and its pending commands, and its key stops working.

**Several accounts on one device:** a device can be signed in as you and as Guest at the same time. **Login** uses the highest-ranked one it has (you, then Guest) and only asks for the password when it has none; "as guest?" uses Guest while keeping your sign-in for the next Login. Holding "sign out" on the root tech signs the device out of all of them.

**Guests:** "as guest?" on the home page signs a device in as `guest` without a password. For now guests can do everything you can, except what needs the agent editing password (viewing or replacing keys, deleting agents). On the live site that means anyone can Start/Pause your agents, message them, upload to their Inboxes, add agents (and so get an API key) and use "Sign out all devices". Restrict it before relying on the site.

**Signing in:** the dashboard has its own login page. Each device (each browser) signs in separately, so signing in on your laptop never lets your phone in.
- A sign-in lasts **one day**, then that device has to sign in again. An open page notices within a few seconds and goes to the login page, then back to where you were.
- **Log out** (top right of the dashboard) signs out this device straight away. **Sign out all devices** (in the ⓘ window) signs out every device, for example if you signed in on a borrowed one.
- Changing `DASHBOARD_USER` or `DASHBOARD_PASSWORD` (and restarting) also signs every device out.
- Each sign-in is a long random token in a cookie that page scripts can't read, that other websites' requests don't carry, and that only travels over https on the deployed site. The database stores only its fingerprint, in the `LoginSession` table.
- Browsers are told never to store dashboard pages, so Back after logging out shows the login page, not an old copy.
- Agents don't use this login at all: their API key is all they need.

**CSRF protection:** every dashboard page carries a secret token, and every button and form sends it back. This stops other websites from using your logged-in browser to press dashboard buttons for you. If you ever see "Missing or invalid CSRF token", reload the page. The token changes whenever `DASHBOARD_PASSWORD` changes.

Agents are listed A–Z, ignoring upper/lower case. Each page holds 9 cells, and the Add Agent card counts as one of them.

## Running the demo agent

`agent/agent.py` is a small demo, useful for trying the dashboard out. It uses the same connector as your own agents.
- It switches messages on and replies to each one.
- It switches its Inbox on, and keeps files you upload in `agent/received/`.
- It does a small piece of "work" every 20 seconds, sending a "ticks" output.
- Press **Pause** and its work stops at the next safe point. Anything it makes while paused is held until **Start**.

First add an agent on the dashboard and copy its key. Keep the site running, open a **second** terminal in this folder, activate the virtual environment there too, and start the agent with its key.

macOS/Linux:
```bash
DASHBOARD_API_KEY=paste-the-key-here python agent/agent.py
```

Windows (PowerShell):
```powershell
$env:DASHBOARD_API_KEY="paste-the-key-here"; python agent\agent.py
```

You can also put `DASHBOARD_API_KEY` in your `.env` file instead. Its card turns **online**, and "Agent online" appears in its activity. Click **Start**, or open its page and send a message, and the agent replies within a few seconds. Press `Ctrl+C` to stop it.

- **Several agents:** add each one on the dashboard, then run one terminal per agent, each with its own key.
- **A deployed dashboard:** the demo talks to `http://127.0.0.1:8000` unless you set `DASHBOARD_URL`, for example `DASHBOARD_URL=https://your-service.onrender.com`. Use a key from that dashboard.
- **Trying your own logic:** edit `handle()` in `agent/agent.py`, under the `YOUR AI LOGIC GOES HERE` banner, and call `report("...")` to send things to the dashboard.

## Running the tests

```bash
pytest -v
```

The tests use an in-memory database and fake secrets, so they never touch
`local.db` or your `.env`. See `tests/TEST_REPORT.md` for the latest results.

## Changing the styles

- **Colours, borders, animations:** edit `static/theme.css`. Nothing to rebuild.
- **Class names** in the templates, from Tailwind (like `grid-cols-3` or `text-sm`) or daisyUI (like `btn` or `card`): their styles live in `static/tailwind.css`, built ahead of time with only the parts the site uses (about 135 KB, instead of daisyUI's whole 1.1 MB). If you add a class name that isn't used anywhere yet, rebuild that file. It needs [Node.js](https://nodejs.org); in this folder, run:

  ```bash
  npm install --no-save tailwindcss@4 @tailwindcss/cli@4 daisyui@5
  npx tailwindcss -i tailwind.input.css -o static/tailwind.css --minify
  ```

  Then commit `static/tailwind.css` along with the template. (`node_modules/` is git-ignored, and Render doesn't need Node.js: it just serves the built file.) If a new class seems to have no effect, a missing rebuild is the likely reason.

## Deploying to Render

1. **Put the code on GitHub.** Create an empty repository on GitHub (it can be private), then run these from this folder:
   ```bash
   git add .
   ```
   ```bash
   git commit -m "First version of my homepage"
   ```
   ```bash
   git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
   ```
   ```bash
   git push -u origin main
   ```
   Before you commit, run `git status` and make sure `.env` and `local.db` are **not** listed.

2. **Create a free Postgres database on Supabase.** Render's own free database is deleted after 30 days; Supabase's free one isn't.
   - Sign up at [supabase.com](https://supabase.com) and create a new project. Choose the region nearest your Render service (Render's default, Oregon, matches **West US (Oregon)**). Generate a database password and save it.
   - Click **Connect** and copy the **Session pooler** connection string. Supabase's "direct" connection needs IPv6, which Render doesn't use.
   - Replace `[YOUR-PASSWORD]` in it with your password, and add `?sslmode=require` to the end. That full string is your `DATABASE_URL`. Treat it like a password.
   - If the password contains symbols such as `@ : / ? # %`, they break the string. Either reset the database password to one with only letters and numbers, or URL-encode those symbols.

3. **Create the Blueprint.** In the [Render dashboard](https://dashboard.render.com), choose **New → Blueprint**, connect your GitHub account, and pick the repository. Render reads `render.yaml` and plans to create a web service called `homepage`.

4. **Enter your secrets.** Render asks for `DATABASE_URL` (from step 2), `DASHBOARD_USER`, `DASHBOARD_PASSWORD`, `AGENT_EDIT_PASSWORD` and `KEY_ENCRYPTION_SECRET`. For production, choose **new** values rather than reusing your local ones. Then click **Apply**.

   Agents you added locally live in your local database, not on Render. Add them again on the live dashboard, then give each agent's connector the Render address (`DASHBOARD_URL=https://your-service.onrender.com`) and its new key.

5. **Wait for the deploy** to finish, then open the `https://....onrender.com` URL Render shows you. Check that `/` and `/dashboard` both work.

From now on, every `git push` to `main` redeploys automatically. To change a secret later, go to the service's **Environment** tab in Render.

### Hosting somewhere other than Render

The app doesn't depend on Render. Any host that can run Python works, such as another platform, a VPS, or a home server:
1. Install the requirements.
2. Set the same environment variables: `DASHBOARD_USER`, `DASHBOARD_PASSWORD`, `AGENT_EDIT_PASSWORD`, `KEY_ENCRYPTION_SECRET`, and `DATABASE_URL`.
3. Run `fastapi run main.py --port <port>`.

Things to get right:
- **Database:** use Postgres via `DATABASE_URL` (`postgres://` and `postgresql://` addresses are converted automatically). SQLite also works, but only if the host keeps files between restarts.
- **HTTPS:** put HTTPS in front of the app, as most hosts or a reverse proxy like Caddy or nginx will. The connector downloads show the right `https://` address if the proxy sends the standard `X-Forwarded-Proto` header.
- **Serve it at the root:** the app's pages use links starting with `/`, so serve it at the root of a domain or subdomain (`https://dashboard.example.com`), not under a sub-folder like `https://example.com/dashboard-app/`.

### Connecting a custom domain

1. In Render, open the `homepage` service, then **Settings → Custom Domains → Add Custom Domain**, and enter your domain (for example `www.yourname.com`).
2. Render shows you one or more DNS records (usually a `CNAME`, or an `A` record for a bare domain like `yourname.com`).
3. Log in to the company you bought the domain from (your registrar) and add exactly those records in its DNS settings.
4. Back in Render, click **Verify**. DNS changes can take anywhere from a few minutes to a few hours. Render sets up HTTPS for you automatically.

### ⚠️ Free-tier warnings

- **The site sleeps.** A free web service shuts down after a period with no visitors. The next visit wakes it up, which can take about a minute. The agent is built to cope with this: it just prints a message and retries.
- **Files take up database space.** Output files are stored in the database, and Supabase's free database is small (500 MB at the time of writing). Text outputs take little room; keep files small, or send links to files stored elsewhere.
- **The free database pauses after a week of no activity.** Supabase pauses free projects that see no activity for a week (no agents running, no visits). Your data is kept; restore the project from Supabase's dashboard. Free projects have no automatic backups. Check [Supabase's current terms](https://supabase.com/pricing).
- **Why not Render's free database?** Render deletes free Postgres databases 30 days after creation (after a 14-day grace period to upgrade). It's fine for a trial, but not for keeping data.

### Changing tables later

Tables are created automatically on startup. **New columns** added to the code are also added to existing tables at startup (`add_missing_columns()` in `db.py`), using each field's default, so a live database keeps working after you push. That's how the check-in interval column reached the live database. **Renaming, removing or changing** a column isn't handled; for that you'll need a migration tool such as [Alembic](https://alembic.sqlalchemy.org).

If you ran an earlier version of this project and have an old `local.db`, delete it once so the current tables (agents with their own keys and encrypted key copies, and folders) are created. It only holds test data.

## Suggested next steps

- **Instant updates:** replace the 3-second refresh with Server-Sent Events. HTMX has an SSE extension for this.
- **Limit login attempts:** the login page doesn't slow down repeated wrong passwords yet, so use a long, unique `DASHBOARD_PASSWORD`.
- **Tidy up old outputs:** agents can already delete their own old outputs (see "Reading other agents' data, and deleting your own"). A dashboard-side automatic clean-up, such as keeping only the last 30 days, would cover agents that don't.
- **Limit request rates:** an agent (or a leaked key) can send unlimited requests; a per-agent rate limit would stop one from flooding the database.
- **Discord notifications:** a bot that reads the `CategoryNotification` table and posts when a marked category gets a new output.
- **Limit password guesses:** slow down or block repeated wrong agent editing passwords.
- **Migrations:** add Alembic before you change your tables (see above).
- **Hide `/docs` in production:** for example, create the app with `FastAPI(docs_url=None, redoc_url=None)` when running on Render.
- **Build out the portfolio:** replace the placeholder in `templates/home.html` with your projects, about section and contact links.

# Homepage

Your personal website, version 1:

- **`/`**: a public home page (a placeholder for your future portfolio).
- **`/dashboard`**: a password-protected dashboard for your AI agents.
  - Agents appear as cards in a 3 × 3 grid, with page buttons when they don't all fit.
  - Each card has Start and Pause buttons, and the last cell is an **Add Agent** card.
  - A folder sidebar shows **All Agents** or just the agents tagged with one folder. It can be folded out of the way, and its corner has an ⓘ guide and **Implement connector** downloads.
  - Click a card to open that agent's page: rename it, tag it with folders, send commands, read its activity log, or delete it.
- **`/api/...`**: a small API your agent uses to talk to the site.

Everything is written in Python. The pages use HTML attributes from
[HTMX](https://htmx.org) and [Alpine.js](https://alpinejs.dev) instead of
hand-written JavaScript, and [daisyUI](https://daisyui.com) for styling.

## How the pieces connect

```text
 agents ──POST /api/outputs───────▶ ┌──────────┐ ◀──GET /dashboard (grid)──── your browser
 (each   ──POST /api/events───────▶ │ database │ ◀──GET /dashboard/agents/N─
 with its◀─GET /api/commands──────── │ (owned by│ ◀──POST .../agents/N/command
 own key)──PUT /api/monitor───────▶ │ the site)│
                                     └──────────┘
```

**One shared database, reached only through the API.** The database belongs to the dashboard website: a SQLite file (`local.db`) on your computer, or the Postgres database Render creates. Agents never connect to it themselves and never need its password. They read and write through the website's API, using their own key, and the website stores everything. This means:
- an agent can run anywhere that can reach the website;
- a leaked agent key only gives access to that one agent's data;
- moving the dashboard to another host or database never requires changing an agent.

These are the tables. Each side reads what the other writes:

- **Agent**: one row per agent, added with the dashboard's **Add Agent** card.
  - It stores a display name, which you can rename at any time.
  - It also stores the agent's API key in two forms, never as plain text: a *fingerprint* (SHA-256 hash), used to recognise the agent, and an *encrypted copy*, so **View key** can show it again. The encryption secret (`KEY_ENCRYPTION_SECRET`) lives in `.env`, not in the database, so a copied database doesn't reveal any keys.
- **Event**: messages from an agent to you, such as "Agent online" or "Error: ...".
- **Command**: messages from you to one agent (`start`, `pause`, or `message` with some text).
- **Folder** and **AgentFolderLink**: your folders, and which agents are tagged with which folder. An agent can be in several folders.
- **Output** and **OutputFile**: results an agent chose to share with `output(content, category)`. Files are stored in the database itself, up to 5 MB each, so they survive restarts on any host.
- **CategoryNotification**: which output categories have the bell turned on.

**Each agent has its own API key.** The agent sends it in the `X-API-Key` header, and the site uses it to work out which agent is calling. That's why renaming an agent never disconnects it.

A card shows **online** if its agent has contacted the site in the last 15 seconds, and **never connected** if it hasn't contacted the site yet.

Here's the flow:

1. An agent posts an event, and the dashboard shows it (the grid and the Activity list reload every 3 seconds).
2. You click **Start** on a card, or type a message on an agent's page, and a pending command is saved for that agent.
3. Each agent checks for its own pending commands every 3 seconds, handles each one, and marks it `done`.

| File | What it does |
|---|---|
| `main.py` | All the routes (pages, dashboard, API). |
| `db.py` | Database connection and the tables (`Agent`, `Folder`, `AgentFolderLink`, `Event`, `Command`, `Output`, `OutputFile`, `CategoryNotification`). |
| `security.py` | The dashboard login check, CSRF protection, the per-agent API-key check, key encryption, and the agent editing password check. |
| `templates/` | The HTML pages (Jinja2). |
| `templates/dashboard.html` | The grid page, with the folder sidebar and the Add Agent window. |
| `templates/agent.html` | One agent's page. |
| `templates/partials/` | Pieces the pages reuse or refresh: the grid (`agent_grid.html`), the Add Agent form and its result (`add_agent_form.html`, `agent_created.html`), the agent's name, tags and settings pop-up (`agent_header.html`), its running/paused badge (`run_state.html`), a shown or replaced API key (`api_key.html`), the two connection values (`connection_values.html`), the Outputs section (`outputs.html`, with its Filter rows `outputs_options.html`, list `outputs_list.html`, Filter button text `outputs_summary.html`, and `output_macros.html` for showing each kind of output), the Monitor section and its pin button (`monitor.html`, `monitor_pin.html`), and the Activity list (`events.html`). |
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
- <http://127.0.0.1:8000/dashboard>: the dashboard. Your browser will ask for your `DASHBOARD_USER` and `DASHBOARD_PASSWORD`.
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
| `listen(on_command)` | Optional: runs your own code when Start or Pause is pressed (e.g. to report "Paused"). |
| `wait_if_paused()` / `is_paused()` | Call `wait_if_paused()` at safe points in your agent's loop so **Pause stops its work**; it waits until Start. `is_paused()` just tells you the state. |
| `accept_messages(on_message)` | Switches on the dashboard's message box for this agent. `on_message(text)` gets each message, for example to pass it to the agent's LLM. |
| `flush()` / `pending()` | Send anything waiting in the offline buffer now / how many items are waiting. |
| `set_monitor(link_or_pdf, label)` | Sets what the agent's **Monitor** shows (only the latest one is kept): a link to where its data lives, such as a Google Sheet, or a **PDF shown inside the page**, such as a daily summary or report the agent regenerates on a schedule. |

**Nothing is lost while the dashboard is unreachable.**
- If the dashboard can't be reached (no internet, a restart, a sleeping free site, a server error), `output()`, `report()` and `set_monitor()` save what they couldn't send. It goes in a `dashboard_buffer` folder next to the connector file (or wherever `DASHBOARD_BUFFER_DIR` points).
- Saved items are sent automatically, every 15 seconds, oldest first, once the dashboard is back. Each keeps its original time and is marked "(sent late, after reconnecting)" in the Activity log.
- The buffer survives the agent restarting.
- **Short scripts** (run on a schedule, then exit) should call `flush()` at the end; anything still waiting goes on the next run.
- Mistakes that retrying can't fix, such as a wrong key or a file over 5 MB, aren't saved; they're printed once instead.
- The buffer holds up to 1,000 items or 100 MB of files, then drops the oldest.

Note that the buffer only protects against the *dashboard* being unreachable. If the agent runs on a computer that's switched off, the agent isn't running either.

**How Start, Pause and messages work:**
- The dashboard never touches your agent's program directly. **Start** and **Pause** set a state that the connector checks every 3 seconds, and the card and agent page show a **running/paused** badge.
- **While paused, logging pauses by itself.** `output()` and `set_monitor()` hold what they're given and send it, in order and at its original time, when you press Start. `report()` still goes through, so you still see status lines and errors. This needs no code in your agent.
- **To pause the work as well,** call `wait_if_paused()` at safe points in the agent's loop. Only the agent knows where it's safe to stop.
- **Messages are opt-in.** The message box stays switched off until the agent calls `accept_messages(on_message)`, which tells the dashboard it takes messages. A good fit is an agent with an LLM that can act on instructions like "focus on earnings news". The dashboard notices within 5 seconds and switches the box on.

**Choosing what to output:** only what you wrap in `output()` reaches the dashboard, so keep it to the results you care about. If an agent produces lots of data, send a short summary (counts, highlights, a link to the full data) instead of all of it.

Use a different `category` for each kind of result, for example `"articles"`, `"daily summary"` or `"reports"`.

## Using the dashboard

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
  - **Controls** (Start, Pause, and a message box) sit in a column on the right that stays in view while you scroll. On a phone they're a bar fixed to the bottom of the screen; tap **Message** to type one. The message box is greyed out until the agent says it accepts messages. The badge next to the name shows whether the agent is **running** or **paused**.

  Everything you can change is behind the **gear icon** next to the name, which opens **Agent settings**:
  - **Name**: rename the agent. It stays connected, because its key doesn't change.
  - **Folders**: **+ Add tag** puts the agent in a folder, and the × on a tag takes it out again.
  - **Monitor**: set, change or remove the monitor link. Saving a link replaces whatever the monitor showed, including a PDF. PDFs can only come from the agent (`set_monitor(Path("summary.pdf"))`). The most recent change wins.
  - **API key**:
    - **View key** shows the current key once you enter your `AGENT_EDIT_PASSWORD`.
    - **Replace key** gives the agent a new key, generated or one you type, also with that password. The old key stops working straight away, so restart the agent with the new key.
    - Closing settings clears any key shown on the page.
  - **Danger zone**: **Delete agent** first asks "are you sure", then needs your `AGENT_EDIT_PASSWORD`. Deleting removes the agent, its outputs (and their files), its activity log and its pending commands, and its key stops working.

**CSRF protection:** every dashboard page carries a secret token, and every button and form sends it back. This stops other websites from using your logged-in browser to press dashboard buttons for you. If you ever see "Missing or invalid CSRF token", reload the page. The token changes whenever `DASHBOARD_PASSWORD` changes.

Agents are listed A–Z, ignoring upper/lower case. Each page holds 9 cells, and the Add Agent card counts as one of them.

## Running the demo agent

`agent/agent.py` is a small demo, useful for trying the dashboard out. It uses the same connector as your own agents.
- It switches messages on and replies to each one.
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

2. **Create the Blueprint.** In the [Render dashboard](https://dashboard.render.com), choose **New → Blueprint**, connect your GitHub account, and pick the repository. Render reads `render.yaml` and plans to create:
   - a web service called `homepage`, and
   - a Postgres database called `homepage-db`.

   It also links the two by setting `DATABASE_URL` for you.

3. **Enter your secrets.** Render asks for `DASHBOARD_USER`, `DASHBOARD_PASSWORD`, `AGENT_EDIT_PASSWORD` and `KEY_ENCRYPTION_SECRET`. For production, choose **new** values rather than reusing your local ones. Then click **Apply**.

   Agents you added locally live in your local database, not on Render. Add them again on the live dashboard, then give each agent's connector the Render address (`DASHBOARD_URL=https://your-service.onrender.com`) and its new key.

4. **Wait for the deploy** to finish, then open the `https://....onrender.com` URL Render shows you. Check that `/` and `/dashboard` both work.

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
- **Files take up database space.** Output files are stored in the database, and Render's free Postgres is small (1 GB at the time of writing). Keep files small, or send links to files stored elsewhere.
- **The free database may expire.** Render's free Postgres databases have historically been deleted after a limited time (with an email warning first). Check [Render's current free-tier terms](https://render.com/docs/free), and upgrade to a paid plan before you store anything you'd mind losing.

### Changing tables later

Tables are created automatically on startup (`SQLModel.metadata.create_all`), but this **only creates missing tables**. It never changes existing ones. If you add, rename or remove a column later, you'll need a migration tool such as [Alembic](https://alembic.sqlalchemy.org).

If you ran an earlier version of this project and have an old `local.db`, delete it once so the current tables (agents with their own keys and encrypted key copies, and folders) are created. It only holds test data.

## Suggested next steps

- **Instant updates:** replace the 3-second refresh with Server-Sent Events. HTMX has an SSE extension for this.
- **Production CSS:** the Tailwind browser build is great for getting started, but it runs in every visitor's browser. Build a small CSS file ahead of time instead with [`pytailwindcss`](https://github.com/timonweb/pytailwindcss).
- **A real login page:** swap the browser's Basic Auth popup for a proper login form with sessions and a logout button.
- **Tidy up old outputs:** add automatic clean-up, such as keeping only the last 30 days or the last 500 outputs per category, so the database doesn't fill up.
- **Discord notifications:** a bot that reads the `CategoryNotification` table and posts when a marked category gets a new output.
- **Limit password guesses:** slow down or block repeated wrong agent editing passwords.
- **Migrations:** add Alembic before you change your tables (see above).
- **Hide `/docs` in production:** for example, create the app with `FastAPI(docs_url=None, redoc_url=None)` when running on Render.
- **Build out the portfolio:** replace the placeholder in `templates/home.html` with your projects, about section and contact links.

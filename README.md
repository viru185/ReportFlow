# ReportFlow

Windows desktop automation for Excel-based reporting. ReportFlow opens a workbook template,
refreshes its data, freezes formulas to values, exports a PDF per sheet using the workbook's
own print layout, saves the outputs, logs the run, and can email the results — on a schedule
or on demand.

It ships as **one installer** but runs as **three separate executables** so responsibilities
stay isolated at runtime:

| Executable | Role |
|---|---|
| **UI** (`reportflow-ui`) | Local desktop app (PySide6): manage jobs and their workbooks, run, move to production, view logs. |
| **Service** (`reportflow-service`) | Background control plane: localhost API + scheduler; launches workers. Runs as a Windows service (via NSSM). |
| **Excel Worker** (`reportflow-worker`) | Short-lived process that does the Excel automation for one run, then exits. |

The **workbook template owns all print layout and PDF appearance** — the app never redesigns
report layout in code.

---

## Table of contents

- [User guide](#user-guide)
  - [Install](#install)
  - [First run](#first-run)
  - [Working in the app](#working-in-the-app)
  - [Create a job](#create-a-job)
  - [Job lifecycle: Testing → Production](#job-lifecycle-testing--production)
  - [Recipients & email template](#recipients--email-template)
  - [Run and schedule](#run-and-schedule)
  - [Logs & diagnostics](#logs--diagnostics)
  - [Settings (SMTP, support email, application)](#settings-smtp-support-email-application)
  - [Import, export & updates](#import-export--updates)
  - [Workbooks using PI DataLink](#workbooks-using-pi-datalink-or-other-excel-add-ins)
  - [Where data lives](#where-data-lives)
- [Developer guide](#developer-guide)
  - [Prerequisites](#prerequisites)
  - [Setup](#setup)
  - [Run in development](#run-in-development)
  - [Testing](#testing)
  - [Lint, format, type-check](#lint-format-type-check)
  - [Build the executables](#build-the-executables)
  - [Build the installer](#build-the-installer)
  - [Project layout](#project-layout)
  - [Configuration reference](#configuration-reference)
  - [HTTP API](#http-api)
  - [Design notes](#design-notes)
  - [CI/CD & releases](#cicd--releases)

---

## User guide

### Install

Run **`ReportFlow-Setup-<version>.exe`** (requires administrator rights). The installer:

- installs the three executables under `C:\Program Files\ReportFlow\`,
- creates the data folder `C:\ProgramData\ReportFlow\` (config, logs, run history),
- registers and starts the **ReportFlow** Windows service (auto-starts on boot),
- adds **Start-menu and desktop shortcuts** for the UI (desktop optional at install time),
- stops any stray ReportFlow processes so the service can bind its port cleanly.

> **Requirement:** Microsoft Excel must be installed on the machine — the worker automates the
> real Excel application.

Upgrading is the same installer: it stops the service, replaces the program files, **preserves
your configuration, logs, and run history**, and restarts the service.

### First run

1. Confirm the **ReportFlow** service is running (Services app, or the header pill in the app
   shows *● Connected*).
2. Launch **ReportFlow** from the Start menu. The dashboard shows summary cards (jobs, active
   runs, recent failures) and one card per job with Run / Test / Edit / Logs buttons.

The service creates a default configuration and email template on first start — you don't need
to hand-create anything. The in-app **user guide** (**F1**, or Help → Help guide) walks through
everything below for everyday users, with a section list and search; **F1** in a dialog opens it
at the part for the current tab. Its source is
[`src/reportflow/ui/help/user_guide.md`](src/reportflow/ui/help/user_guide.md), so it also reads
well on GitHub. Every field has a tooltip.

### Working in the app

- **Enter never closes a window.** In a recipient box it adds what you typed; elsewhere it does
  nothing. **Ctrl+S** saves the job editor, Settings and the template editor; **Esc** cancels.
- **Unsaved changes are never lost by accident** — closing an edited window asks *Discard
  changes* / *Keep editing*. Opening and closing without editing asks nothing.
- **Problems are shown where they are.** When Save finds a problem, the field gets a red outline
  with the reason underneath and its tab gets a red dot; the editor jumps to the first one. The
  mark clears as soon as it's fixed — no OK pop-ups.
- **Short messages fade on their own** ("Saved", "Logs sent", "Removed X — Undo") at the top of
  the window; hover keeps one visible. Real decisions (delete? discard? move to production?) still
  ask.
- Dialogs **reopen at the size you left them**.

### Create a job

Click **+ New Job**. The editor is organized in sections:

**General**
- **Job name** — unique; also used in output filenames. You can **rename** a job later — its
  run history and email template follow the new name.
- **Workbooks** — the job's Excel files are listed on the left; the selected one's details and
  sheets are on the right (below 720 px of width the list sits above the details). **+ Add
  workbooks…** picks one or several `.xlsx`/`.xlsm` files at once, or **drag them from Explorer**
  and drop them anywhere on the General tab. A file already in the job is skipped (its row
  flashes and a notice says which); folders, lock files and non-Excel files are refused with one
  notice. Each row shows its status — *3 of 5 sheets*, *Reading sheets…*, *⚠ File not found*,
  *⚠ Can't open*, or *Service not reachable* — and, on hover or selection, **Replace…** (keeps the
  sheet choices) and **Remove** (with **Undo**; the **Delete** key works too). Every run builds
  all the workbooks and sends **one** email with every file attached.
- **Sheets are read automatically** — when the editor opens, when a file is added or replaced,
  when you select a workbook and when you come back to the window — so the list is always
  current; there is no Browse or Discover button. A new workbook has every sheet ticked; sheets
  that appear later in a job's workbook arrive unticked. An included sheet that is **no longer in
  the file** stays in its place marked *⚠ not in the file any more*, and the job can't be saved
  until it is unticked or the file replaced (it used to fail every run). A missing or unreadable
  file never blocks Save. (Sheets are stored by *name*, so reordering sheets is safe.)
- **Sheets** — one row per sheet: **Include** (refresh, check and freeze it), **PDF** (also
  export it as its own PDF) and **Hidden** (keep it in the Excel file but hidden — recipients
  can unhide it; it can still get a PDF). At least one included sheet must stay visible. Click
  a column title to tick the whole column.
- **Sheets not included** — *Remove them from the file* / *Keep them, hidden* (very-hidden,
  references stay intact) / *Keep them, visible*.

**Output**
- **Output folder** — browse to where results are saved, or leave empty to save **next to the
  input file**.
- **Filename** — optional stem; empty means `{job}_{datetime}` (e.g. `Sales_20261007_061500`),
  so a job that runs twice in one day never overwrites its earlier report. Placeholders
  (**{ } Insert placeholder** beside the field lists them with examples):
  `{job}`, `{date}`, `{time}`, `{datetime}`, `{run_id}`, `{workbook}`. With several workbooks
  `_{workbook}` is added automatically. A live example shows the resulting names (and warns
  when a custom name has no time). Each run writes `<name>.xlsx` per workbook plus one
  `<name>_<sheet>.pdf` per sheet with PDF ticked.
- **Freeze formulas to values**.
- **If a workbook fails** (several workbooks only) — fail the whole run and send nothing
  (default), or send the workbooks that worked with a warning naming the failed one.

**Schedule** — no schedule = manual. **+ Add schedule** adds a compact card for a **Daily**,
**Weekly**, **Monthly** or **Custom (cron)** rule; add several to combine them — e.g. daily at
06:00 *and* every Sunday at 10:00. A card's **Runs at** row shows each time as a small pill
with its own ×; **+ Add time** opens a small picker — press **Add** (or Enter) and the time
appears as a pill straight away, so every time shown is a time that will run (a time already in
the rule is refused in the picker). Weekly rules pick days with **Mon … Sun** toggles. Each card
has a quiet **Remove**. The summary above the cards says when the job runs, and turns amber with
the reason when a rule can't be used — e.g. two rules that would fire at the same moment (the
job would run twice).

**Email** — subject (placeholders work here too, e.g. `Daily report — {{ today }}`; **{ }
Insert placeholder** beside it), recipients, and the template editor (next section).

**Advanced** — **Time limit** (minutes; the run is stopped and marked *Timed out* after
this — raise it for big PI reports that need 20+ minutes), **Wait for add-in data** (keep
waiting up to N seconds while PI DataLink fills cells; moves on as soon as the data stops
changing), **Concurrency group** (groups other jobs use are suggested as you type), the
empty/error-cell checks, **Blank out values**, notes.
Each setting has a one-line explanation right under it.

Only a workbook, at least one sheet, and the **To** addresses are required. Everything
optional can be left blank.

### Job lifecycle: Testing → Production

Every job starts in **Testing**: every run — manual **and scheduled** — emails only the
**Test** recipients (subject prefixed `[TEST]`), so the report is verified internally first.
When you're happy with it, click **✓ Move to production** on the job card (the confirmation
names the production recipients); from then on runs email the **client**. A job in Production
can be moved back to Testing from the job editor's Email tab. The card shows an amber
**Testing** / green **Production** pill so the state is always visible. (The config file still
stores the promoted stage as `stage = "live"`.)

### Recipients & email template

Each job has two recipient sets — **production** and **test** — each with **To** (required),
**Cc** (optional), and **Bcc** (optional). Each box holds addresses and **email groups** as
chips: type to search the groups and every address the app already knows (all jobs, group
members, Settings addresses); Enter, Tab, `,` or `;` adds it, and a pasted list is split. Only a
chip's **×** removes it; Backspace in an empty box removes the last chip. Suggestions leave out
whoever is already in the set (directly or through a group).

- **Email groups** (File → Settings → Email groups) — name a list of addresses once and use the
  name in any job. Renaming a group keeps its jobs pointing at it; a group a job still uses
  can't be deleted.
- **Each person is added once.** Adding an address or group that is already in the set — or an
  address a group in the set already covers — is refused, the existing chip flashes, and a note
  under the boxes says where it already is (no pop-up). Adding a group removes the chips it now
  covers, with **Undo**, but never moves anyone down from To to Cc or Bcc.
- **Each address is emailed once** — if a set still names someone twice (an older job, or an
  address in two groups), they go out once (To before Cc before Bcc).
- **Testing-stage** runs email the **test** recipients only — they can never reach production.
- **Production** runs email the **production** recipients. Failures never send an automatic
  email.
- Report emails attach the **output Excel** plus **all per-sheet PDFs**, and show the run's
  real **duration**.

The email **body** is authored in-app: click **Edit email template…** in the job editor. The
editor opens large (and remembers its size) with your message on the left — **Simple** mode
(plain text) or **HTML** mode — and the **preview** on the right, updated as you type; there is
no Preview button. **Show the email as Testing | Production** switches the preview between the
emails each stage sends — subject (with `[TEST]` on Testing), To/Cc and body — for this job. A
mistake in a placeholder shows above the preview in plain words, with its line number, while the
last good preview stays visible. The template is stored per job; leave it untouched to use the
built-in default.

- **Placeholders** — **{ } Insert placeholder** (in the template editor, beside the Subject and
  beside the output file name) opens a searchable list with an example of each; double-click,
  Enter or **Insert** puts one at the cursor and the list stays open for the next. Dates
  (`{{ today }}`, `{{ yesterday }}`, `{{ now }}`, `{{ weekday }}`,
  `{{ month }}`, `{{ previous_month }}`, `{{ week_number }}`, or any format via
  `{{ run_date.strftime('%d/%m/%Y') }}`), run facts (job, status, stage, timings, warnings) and
  files (attachments, workbooks, sheets). They work in the **Subject** too. **Help → Email
  placeholders** has the full table and recipes.
- **Load from file…** — use an `.html` file made elsewhere. By default a copy is saved with the
  job; tick **Keep linked to this file** to have every run re-read it (the service must be able
  to read it — the editor checks; if it later goes missing, the email uses the default template
  and the run shows a warning).

### Run and schedule

Two single-click actions on each job card — the job's stage answers "who gets the email":

- **▶ Run** — builds the report and emails per the stage (testers while Testing, the client
  once in Production).
- **👁 Build only** — builds and verifies the report (checks the data) but emails no one.
- **Schedule** — the service runs enabled jobs on their configured times automatically; each
  configured time registers its own trigger, honouring the job's stage. Scheduled cards show
  **when the next run fires** ("next: tomorrow 06:00").

While a job is **running**, its card shows a live elapsed counter and the run buttons lock so
it can't be double-fired. Multiple jobs run in parallel, each in its own disposable worker
process. A failed run is never retried automatically — it's recorded and visible in history.

Each card's **coloured left edge** tells the last run's outcome at a glance — green =
success, red = failed, amber = running, grey = never ran (or paused) — and the detail line
reads `next: tomorrow 06:00 · last: success 2h ago · 4 sheet(s)`.

Everything occasional lives behind the card's **⋯** menu (so daily actions stay one click):

- **📂 Open last report** — Explorer opens with the last successful report pre-selected.
- **✎ Edit** and **Logs** — the job editor (including rename) / that job's run history.
- **⧉ Duplicate** — a new job with *everything* copied — workbooks, sheet choices, schedules,
  recipients, advanced options and the email template; only the name (new) and the stage
  (Testing) differ.
- **⏸ Pause** — pause scheduling. A paused job's whole card is dimmed — muted name, grey
  stage pill and edge, no extra pill — and a one-click **▸ Resume** button takes the promote
  button's slot. Manual runs still work while paused.
- **🗑 Delete** — remove the job (with confirmation).

### Logs & diagnostics

- **Logs** on a job card — that job's run history: status, timings, output paths, error
  summary, and the worker log tail. It refreshes live while a run is in progress.
- **Logs → Application logs** — the full rolling logs of the Service, Worker, and UI, with a
  one-click Service/Worker/UI switcher and per-token colour (timestamp, level, message).
- **Logs → Send logs to support** / **Export logs to zip** — bundle the logs + sanitized
  settings (never passwords); you can type a short **problem description** that rides along in
  the bundle (and the email) so the developer knows what to look for.
- **Logs → Delete old logs… / Delete ALL logs…** — free disk space on demand. "Old" uses the
  retention setting; "ALL" wipes every run folder, log, bundle, and history row (strong
  confirm; active runs always survive). The service also purges automatically at startup and
  nightly per **Log retention** — the setting now genuinely controls disk usage.
- **File → Open data folder** — opens `C:\ProgramData\ReportFlow` in Explorer.

### Settings (SMTP, support email, application)

**File → Settings** configures everything in-app (one compact two-column dialog — email on
the left, application & service on the right):

- **SMTP** — host, port, STARTTLS/SSL, from-address, username, and the **password** (stored
  encrypted via Windows DPAPI, machine scope — never in the config file). An eye icon shows
  the password while typing, and **Test connection** verifies the settings against the mail
  server without sending anything.
- **Support** — the address that receives "Send logs to support" bundles (test runs email each job's own Test recipients; there is no global fallback)
  that receives diagnostic bundles.
- **Application** — max parallel runs, default time limit (minutes), log retention, and the
  startup update-check toggle (off by default).

### Import, export & updates

- **File → Export/Import jobs…** — back up or move jobs between machines as JSON. Pick
  which jobs to include (some or all); on import, name clashes prompt per job:
  Overwrite / Skip / Import as copy.
- **File → Export/Import settings…** — the same for application settings. The SMTP
  password never travels; re-enter it after importing.
- **Updates** — **Help → Check for updates…** looks for a newer release on GitHub; tick the
  startup check in Settings to have the app look on every start (off by default; skipped when
  offline). Nothing installs until you click **Update now**; the download shows progress and
  the installer upgrades automatically, preserving jobs, settings, and logs. **Beta**
  pre-releases are never offered — install one by hand from the GitHub releases page.

### Workbooks using PI DataLink (or other Excel add-ins)

**PI DataLink is a VSTO add-in that uses Windows-integrated security, and it cannot load
when the service runs as LocalSystem** (the default). With no user profile / VSTO cache / PI
identity, `.Connect` fails with *"the add-in could not be installed"*, its worksheet
functions are unregistered, and every PI cell comes out as **`#NAME?`** — a broken report,
not an empty one. The legacy Task Scheduler script worked only because it ran **as the
desktop user**.

**Fix — run the service as a PI-enabled Windows user** (one that has PI DataLink installed
and PI access):

- **In the app (easiest):** **File → Settings → Service account** → **Use current Windows
  user** → enter the password → **Validate & apply**. ReportFlow checks the credentials with
  Windows, reconfigures the service to run as that user, and restarts it — no admin prompt, no
  reinstall; the dialog waits until the service is back as that account. The dashboard's red
  banner has a **Set account…** button that jumps straight here. (Once the service runs as an
  ordinary user, changing the account again needs an administrator: rerun the installer or the
  script below.)
- **Then trust PI DataLink for that account:** Windows only loads PI DataLink for an account
  that has accepted its one-time trust prompt, which a service account never sees — PI DataLink
  then stays off and every PI cell keeps its last-saved value (the report still goes out, with
  stale data). **File → Settings → Service account** shows whether it is trusted; **Trust PI
  DataLink for this account** records that trust for the service account (only for PI add-ins
  an administrator installed). A run whose PI DataLink isn't trusted says so in its warnings.
- **Fresh install:** the installer asks for an optional **service account** and validates the
  credentials before continuing — enter the PI-enabled user there.
- **Admin PowerShell (alternative):** `scripts\set-service-account.ps1 -User "DOMAIN\your_pi_user"`.
- **Verify:** **File → Settings → Service account** shows the current account (and warns in red
  if it is LocalSystem); the dashboard shows a warning banner too. Then click **👁 Build only**
  on the job — the worker log should read `Executing as DOMAIN\your_pi_user` (no trailing `$`)
  and `COM add-in 'PI DataLink': connected=True`, with real values.

**Error cells are reported, not fatal.** Pre-existing errors like `#REF!` no longer block
delivery — the report is sent and the errors show as a *warning* on the run. Strip them with
the **Blank out values** list (e.g. `#REF!, #N/A`), or tick *"Fail the run if a sheet has
error cells (strict)"* to fail instead. If a sheet is only partly filled, the add-in's data
was still arriving at freeze time — raise **Wait for add-in data** (ReportFlow waits
adaptively up to that budget and logs when data is still changing at the end). If the run
instead ends as *Timed out*, raise the **Time limit**.

**"Cannot be opened" output.** Removing non-selected sheets can break a chart/defined name that
referenced them, and Office File Validation then blocks the file. ReportFlow purges broken
`#REF!` defined names automatically; if a report still won't open, set that workbook's **Sheets
not included** option (General tab) to **Keep them, hidden** — the others become very-hidden,
references stay intact, and the file always opens. If the *input* file won't open by hand, it carries a
Mark-of-the-Web: right-click → Properties → **Unblock** (or add its folder as a Trusted
Location); reports still generate because the service opens files via automation.

**Build only** (👁 on each job card) builds the full report and runs the checks but never emails
— use it to confirm PI data before relying on scheduled delivery.

**Email failures no longer pass silently:** when a run builds but the email cannot be sent,
the run history shows a warning banner for that run, the card shows a red **Email failed** tag, and the run history's
**email:** line gives the reason. When SMTP is down and you need to hand logs to support,
use **File → Export logs to zip…** to save the diagnostic bundle locally.

### Where data lives

Everything runtime lives under **`C:\ProgramData\ReportFlow\`**:

```
config\reportflow.toml     application + SMTP + job definitions
templates\email\default.html   default email body
templates\jobs\<job>.html  per-job email templates authored in-app (or imported)
logs\                      rolling per-process logs (ui, service, worker)
state\runs.db              run history (SQLite)
state\secrets\             encrypted secrets (DPAPI)
runs\<run_id>\             per-run request/result/log artifacts
```

---

## Developer guide

### Prerequisites

- **Windows** (the product targets Windows; `pywin32`/`PySide6`/`xlwings` are Windows-native).
- **Python 3.11+** (the repo pins 3.12 via `.python-version`).
- **[uv](https://docs.astral.sh/uv/)** for dependency and environment management.
- **Microsoft Excel** installed — required only to run the Excel-marked tests and the real worker.

### Setup

```powershell
uv sync --all-extras
```

This creates `.venv/` and installs the base package plus the `service`, `ui`, `worker`, and
`dev` extras. `uv` provisions Python 3.12 automatically if needed.

### Run in development

```powershell
# Service (localhost API + scheduler) — http://127.0.0.1:8787
uv run python -m reportflow.service        # or: uv run reportflow-service

# UI (talks to the running service)
uv run python -m reportflow.ui             # or: uv run reportflow-ui

# Generate a sample workbook, then drive the worker end-to-end (needs Excel)
uv run python scripts/make_sample.py
uv run python scripts/dev_run_worker.py            # in-process
uv run python scripts/dev_run_worker.py --subprocess --runs 3   # parallel, ghost-check
```

Set **`REPORTFLOW_DATA_DIR`** to redirect the data root (config/logs/state) away from
`C:\ProgramData\ReportFlow` — useful for local runs and tests:

```powershell
$env:REPORTFLOW_DATA_DIR = "C:\temp\reportflow-dev"
```

### Test the installed app with local email capture

Install ReportFlow on your laptop and open it from the Start menu. From the repository
root, start the SMTP capture server in PowerShell.

```powershell
uv sync --all-extras
uv run smtpserver
```

Keep the terminal open while running reports in the installed app. Captures are saved to
`build/local-test/outbox/*.eml`, relative to the directory where you started the command.
You can choose another folder or port.

```powershell
uv run smtpserver --port 2526 --outbox build/local-test/outbox
```

In the installed app, open **File → Settings → Email** and enter these values.

| Field | Value |
|---|---|
| Host | `127.0.0.1` |
| Port | `2525` (or the port passed to the command) |
| Use STARTTLS | Unchecked |
| Use SSL | Unchecked |
| From address | `reportflow@example.com` |
| Username | Empty |
| Password | Leave unchanged or empty, the empty username skips authentication |

Put `tester@example.com` in a job's **Test: To** to catch its test emails.

Click **Test connection**, then **Save**. These settings apply to emails sent by this
installed instance, including scheduled reports. Use them on your testing laptop.

Create or edit a job. Set its stage to **Testing**, Test To to `tester@example.com`, and
Production To to `production@example.com`. Leave **Run on schedule** unchecked for manual
testing. Select your workbook, sheets and Excel/PDF attachments, and choose a local output
folder. Click **Run** on the job card.

The installed service launches its Excel worker, builds the actual reports, then submits
an email to the local capture server. The terminal prints the subject, attachment names
and envelope recipients, including Bcc. Run history shows report and email status.
**Build only** creates reports without email. **Test connection** checks SMTP connectivity.

Open the latest captured email from the repository root.

```powershell
$latestEmail = Get-ChildItem -LiteralPath build/local-test/outbox -Filter *.eml |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latestEmail) { Invoke-Item -LiteralPath $latestEmail.FullName }
```

Use Outlook or another `.eml` reader to inspect the body and open the actual Excel/PDF
attachments. The captures are ignored by Git. Press **Ctrl+C** in the capture terminal to
stop the server. Keep your previous SMTP values if you need to restore delivery later.
Local SMTP acceptance verifies the application flow. External mailbox delivery, spam
filtering and authenticated/TLS SMTP require separate tests.

For source development, the service and UI commands above can also use this capture server.
The command is provided by the development-only workspace package in `tools/smtpserver`.

Worker-only quick loop (no service/UI):

```powershell
uv run python scripts/dev_run_worker.py --template "D:\path\to\MyReport.xlsx" --sheets "Sheet A" "Sheet B"
```

### Build & test the executables locally

```powershell
uv run reportflow-build                         # dist\worker, dist\service, dist\ui
dist\ui\reportflow-ui.exe --selftest             # exit 0 => UI bundle OK

# Run the FROZEN service + UI against the isolated data dir:
$env:REPORTFLOW_DATA_DIR = "C:\temp\reportflow-dev"
dist\service\reportflow-service.exe              # terminal 1
dist\ui\reportflow-ui.exe                        # terminal 2 (same env var)
```

`dist\` mirrors the installed layout, so the frozen service finds the frozen worker the
same way it does under `C:\Program Files\ReportFlow`. When this passes, push/tag with
confidence — the CI installer wraps the very same artifacts.

### Testing

Excel-dependent tests are marked `excel` and skipped by default (and in CI).

```powershell
uv run pytest -m "not excel"      # fast suite, no Excel required
uv run pytest -m excel            # real-Excel suite (local, needs Excel)
uv run pytest                     # everything
```

Qt tests run headless via `QT_QPA_PLATFORM=offscreen` (set automatically in `tests/ui/`).

The Excel suite includes a **ghost-process assertion** — it fails if any `EXCEL.EXE` survives a
run (including 3 parallel worker processes).

### Lint, format, type-check

```powershell
uv run ruff check .
uv run ruff format .            # or --check in CI
uv run mypy
```

### Build the executables

`reportflow-build` builds any of the three executables and the installer, like
`reportflow-service` / `-worker` / `-ui` run them (run `uv sync --all-extras` once first):

```powershell
uv run reportflow-build                    # all three executables
uv run reportflow-build worker             # just one
uv run reportflow-build worker service     # several
uv run reportflow-build installer          # the installer, from the exes in dist\
uv run reportflow-build all                # all three executables, then the installer
```

Targets combine (`ui installer` rebuilds the UI, then the installer). The version always comes
from `pyproject.toml`. Output (onedir bundles): `dist/worker`, `dist/service`, `dist/ui`.
Validate the frozen UI's Qt platform plugin without a visible window:

```powershell
dist\ui\reportflow-ui.exe --selftest    # exits 0 if qwindows.dll loaded
```

### Build the installer

Requires [Inno Setup 7 or 6](https://jrsoftware.org/isdl.php) and
`packaging/nssm/nssm.exe` (download the 64-bit binary from [nssm.cc](https://nssm.cc/download)).

```powershell
uv run reportflow-build all          # exes + installer
uv run reportflow-build installer    # installer only, from the exes already in dist\
# -> packaging\innosetup\Output\ReportFlow-Setup-<version>.exe
```

It finds `ISCC.exe` on `PATH`, in the registry (per-user installs included) or in the
usual folders; `--iscc <path>` overrides it. It passes the version from `pyproject.toml`, plus
the numeric part a beta needs for the Windows file version (`0.12.0-beta` → `0.12.0`), and it
refuses to package executables in `dist\` that were built from another version.

### Project layout

```
src/reportflow/
  core/            shared library (no PySide6, no xlwings)
    paths.py       ProgramData/install-dir resolution
    config/        Pydantic models + TOML loader + defaults
    logging_setup.py   loguru sinks with secret redaction
    secrets.py     DPAPI machine-scope secret store
    email/         Jinja2 render + SMTP sender + redaction/bundle
    state/         SQLite run history
    ipc/           WorkerRequest / WorkerResult contract
  worker/          xlwings automation (the only xlwings importer)
  service/         FastAPI app, launcher, scheduler, bootstrap, workbook discovery
  ui/              PySide6 app: api_client + windows
    feedback.py    toasts, field errors + tab dots, FormDialog (Enter/Ctrl+S/F1/Esc, sizes)
    sheet_loader.py  background sheet reading for the workbook list
    help/user_guide.md  the in-app user guide (Markdown, bundled with the UI)
  build.py         reportflow-build: the exes + installer (dev tool, never frozen)
packaging/         PyInstaller specs, Inno Setup, NSSM
scripts/           sample workbook generator + dev worker runner
tests/             core / worker / service / ui suites
```

### Configuration reference

`config/reportflow.toml` (seeded on first service start):

```toml
config_version = 1

[app]
api_host = "127.0.0.1"        # local-only; do not bind 0.0.0.0
api_port = 8787
max_global_concurrency = 4
default_timeout_seconds = 900
log_retention_days = 30

[smtp]
host = "smtp.corp.example.com"
port = 587
use_starttls = true
from_address = "reportflow@corp.example.com"
username = "reportflow@corp.example.com"
# password is NOT here — stored via DPAPI under state\secrets

[ui]
api_base_url = "http://127.0.0.1:8787"
check_updates_on_startup = false

[email]
default_template_path = "email/default.html"   # relative to templates\

  [[email.groups]]                        # Settings → Email groups
  name = "Plant managers"
  members = ["pm1@corp.example.com", "pm2@corp.example.com"]

[test]
recipients = ["dev-team@corp.example.com"]
developer_bundle_recipients = ["dev-team@corp.example.com"]

[[job]]
name = "daily_sales"
enabled = true
email_template_path = 'C:/ProgramData/ReportFlow/templates/jobs/daily_sales.html'  # optional
output_dir = "C:/Reports/daily_sales"     # optional; empty -> next to each input file
output_name = "{job}_{datetime}"          # optional filename stem; PDFs get _<sheet> suffix
on_workbook_failure = "fail_run"          # or "send_partial" (several workbooks)
freeze_values = true
schedule_crons = ["0 6 * * *", "0 10 * * SUN"]   # one trigger per entry (daily + Sunday)
timeout_seconds = 2700                    # the editor shows minutes
post_refresh_wait_seconds = 120
concurrency_group = "reports"
subject = "Daily Sales — {{ today }}"     # placeholders work in the subject
stage = "live"                            # "testing" (default) emails testers; "live" = Production

  [[job.workbooks]]                       # one or more; all go out in one email
  input_excel_path = "C:/Templates/daily_sales.xlsx"
  unselected_sheets = "remove"            # sheets not listed: "remove" | "hide" | "keep"
  sheets = [                              # names, not indexes
    { name = "Summary", pdf = true, hidden = false },
    { name = "Detail",  pdf = false, hidden = true },
  ]

  [job.prod]
  to  = ["managers@corp.example.com"]
  to_groups = ["Plant managers"]          # email groups; To needs an address or a group
  cc  = ["ops@corp.example.com"]          # optional
  # bcc = [...] / cc_groups / bcc_groups  # optional

  [job.test]
  to  = ["dev-team@corp.example.com"]
```

The SMTP password is provisioned from the app (**File → Settings**), which stores it via
machine-scope DPAPI. Dev-environment alternative:

```powershell
uv run python -c "from reportflow.core import secrets; secrets.set_secret('smtp_password', 'YOUR_PASSWORD')"
```

### HTTP API

Bound to `127.0.0.1` only.

| Method & path | Purpose |
|---|---|
| `GET /health` · `GET /system/status` | Liveness and runtime status. |
| `GET /config` | Sanitized config snapshot (no secrets). |
| `POST /config/reload` | Reload config from disk and re-schedule. |
| `PUT /settings` | Update app/smtp/ui/email/test sections (jobs untouched). |
| `GET/POST/DELETE /system/smtp-password` | Status / store / clear the DPAPI SMTP password. |
| `GET /system/logs?process=&tail=` | Tail the Service/Worker/UI rolling log. |
| `GET /jobs` · `GET/POST/PUT/DELETE /jobs/{name}` | Job CRUD (a PUT with a new name renames the job; history + template follow). |
| `POST /jobs/{name}/run` · `POST /jobs/{name}/dry-run` | Run per the job's stage / build only. |
| `POST /jobs/{name}/stage` | Promote to production (`live`) / demote to testing. |
| `PUT /email-groups` | Replace the email groups (`renamed_from` carries jobs; in-use deletes refused). |
| `GET/POST /system/pi-trust` | Is PI DataLink trusted for the service account / trust it. |
| `POST /system/purge-logs` | Delete old (or all) run folders, logs, bundles. |
| `GET/PUT /jobs/{name}/email-template` | Read / write the job's per-job email template. |
| `GET /runs` · `GET /runs/{id}` · `GET /runs/{id}/log` | Run history and logs. |
| `POST /workbook/sheets` | Read sheet names (openpyxl, no COM); 404 when the service can't find the file. |
| `POST /email/preview` | Render the email template with sample data. |
| `POST /email/template-check` | Can the service read + render a template file (for linked templates)? |
| `POST /system/send-dev-logs` | Email the redacted diagnostic bundle. |

### Design notes

- **Excel isolation.** Only the worker imports `xlwings`. The service launches one worker
  subprocess per run and communicates via a request/result JSON file + exit code — never stdout.
- **No ghost Excel.** Each worker uses a dedicated hidden Excel instance whose PID is captured
  and force-reaped in `finally` (`quit` → `kill` → psutil verify). The service tree-kills a hung
  worker on timeout.
- **Parallel-safe startup.** Concurrent Excel activations can raise transient COM errors
  (`RPC server unavailable`), so worker startup is serialized with a session-local named mutex
  and the whole session is retried on transient COM errors (idempotent output). Deterministic
  failures (missing sheet/template) are not retried.
- **Test-recipient guard** lives in exactly one function; a test run cannot reach production
  addresses. BCC is passed only in the SMTP envelope, never as a header.
- **Config vs. state** are physically separate: TOML for configuration, SQLite for run history.
- **Secrets** use machine-scope DPAPI so the LocalSystem service can read what the interactive
  user wrote.
- **The UI never waits on a workbook.** Sheet lists are read through the service on a small
  thread pool (`ui/sheet_loader.py`); the newest read of a workbook wins and a stopped service
  shows as *not reachable*, never as *file not found*.

### CI/CD & releases

- **`.github/workflows/ci.yml`** (push/PR, `windows-latest`): `ruff check`, `ruff format
  --check`, `mypy`, `pytest -m "not excel"`, and Conventional-Commits linting on PRs.
- **`.github/workflows/release.yml`** (tag `v*`): checks the tag matches `pyproject.toml`,
  builds the three exes, fetches NSSM, compiles the Inno Setup installer, writes release notes
  with git-cliff (everything since the last stable tag), and publishes a GitHub Release with
  the installer + zipped executables.

**Beta first.** A new feature ships as a beta: set `version = "X.Y.Z-beta"` in
`pyproject.toml` and push tag `vX.Y.Z-beta` (from any branch). Betas are **not numbered** — if a
beta needs a fix, bump the version (`v0.11.0-beta` → `v0.11.1-beta`), never `-beta.2`. It is published as a GitHub
**pre-release**, never marked latest, so the in-app updater ignores it and testers install it
by hand. When it's verified, set `version = "X.Y.Z"`, merge to `main` and push tag `vX.Y.Z`:
that release is offered to everyone, its notes include the beta's changes, and the workflow
commits the regenerated `CHANGELOG.md` to `main` (betas skip that step and get no changelog
section of their own).

Commits follow [Conventional Commits](https://www.conventionalcommits.org/); the changelog is
generated from history by [git-cliff](https://git-cliff.org/).
```


### Sheet-level email attachments

Each included sheet has independent **Excel attachment** and **PDF** choices. One emailed
Excel file per workbook contains exactly the Excel-selected sheets. The regular local
Excel copy is retained even for PDF-only emails and follows the workbook's existing
keep/hide/remove setting for other sheets. Local **Open report** still opens that copy.
**Combine selected sheets into one PDF** produces one PDF per workbook in the listed
sheet order, preserving each sheet's print settings. No selected attachments means a
local build without email.

### Diagnosing PI activation under the service account

Enable **Edit → Advanced → Require PI DataLink** for reports that depend on PI. Run
**Build only** through the existing service account, then **Logs → Export logs to zip…**.
The run's `pi_diagnostics/activation.json` records the actual Windows identity, session,
Excel version/bitness, add-in registration and activation errors. New PI-related VSTO
logs and relevant Application events are collected there too. Diagnostics enable
`VSTO_LOGALERTS=1` and suppress VSTO dialogs within the worker process only. No login
as the service account or account change is needed.

Retain the configured service account while investigating. If a log contains only
VSTO's outer “The add-in could not be installed” error, inspect the detailed deployment
exception to determine the repair (manifest access, runtime dependencies, registration,
trust, disabled add-ins or profile access). Pasted values do not establish recovery.
Excel startup access denial (`0x80070005`) is reported separately.

Recovery requires an original-formula test workbook to retrieve a controlled recent-data
query through the service, match an independently checked reference, and repeat after a
service restart. Add-in connection alone, cached values, and manually pasted reports do
not establish fresh PI data. Local tests do not establish recovery on the affected server.

### Investigating VSTO publisher-trust failures

If diagnostic events identify `System.Security.SecurityException` in `VerifyAddInTrust`,
inspect the installed vendor certificate and the executing account's inclusion list.
Use the detailed exception to establish the cause before choosing an approved repair.
The helper below is an inspection tool by default, not an automatic repair.

From a PowerShell terminal on the server, inspect the installed public certificates first:

```powershell
$piManifests = @(
    "$env:ProgramFiles\PIPC\Excel\OSIsoft.PIDataLink.UI.vsto"
    "${env:ProgramFiles(x86)}\PIPC\AF\PIAFBuilder.vsto"
)
.\scripts\repair-pi-publisher-trust.ps1 -ManifestPath $piManifests
```

The helper defaults to inspection only. IT must independently verify the actual vendor
signing certificate SHA-256 fingerprints against an approved package or certificate.
After approval, an administrator can run the helper with `-ApprovedSha256` and `-Apply`
to import only those certificates into `LocalMachine\TrustedPublisher`. This grants
publisher trust to all code signed by those certificates on the device. The helper requires
valid code-signing certificates and a valid Windows certificate chain, and never installs
root certificates or changes Office policy. Expired certificates or invalid chains require
vendor/IT repair instead. IT can deploy the same approved certificates through Group Policy.

Once current runs finish, restart ReportFlow, enable **Require PI DataLink** on PI jobs,
and use **Build only** with the original formulas. Verify both connection and fresh PI
results before normal delivery. If a template's sheet names have changed, use
**Discover sheets** and select the intended sheets explicitly. ReportFlow must not
silently substitute renamed sheets.

Microsoft references: [VSTO trust](https://learn.microsoft.com/en-us/visualstudio/vsto/granting-trust-to-office-solutions),
[machine-scope ClickOnce publisher deployment](https://learn.microsoft.com/en-us/visualstudio/deployment/how-to-add-a-trusted-publisher-to-a-client-computer-for-clickonce-applications).

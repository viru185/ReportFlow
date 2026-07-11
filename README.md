# ReportFlow

Windows desktop automation for Excel-based reporting. ReportFlow opens a workbook template,
refreshes its data, freezes formulas to values, exports a PDF per sheet using the workbook's
own print layout, saves the outputs, logs the run, and can email the results — on a schedule
or on demand.

It ships as **one installer** but runs as **three separate executables** so responsibilities
stay isolated at runtime:

| Executable | Role |
|---|---|
| **UI** (`reportflow-ui`) | Local desktop app (PySide6): manage jobs, discover sheets, run/test, view logs. |
| **Service** (`reportflow-service`) | Background control plane: localhost API + scheduler; launches workers. Runs as a Windows service (via NSSM). |
| **Excel Worker** (`reportflow-worker`) | Short-lived process that does the Excel automation for one run, then exits. |

The **workbook template owns all print layout and PDF appearance** — the app never redesigns
report layout in code.

---

## Table of contents

- [User guide](#user-guide)
  - [Install](#install)
  - [First run](#first-run)
  - [Create a job](#create-a-job)
  - [Recipients & email template](#recipients--email-template)
  - [Run, test, and schedule](#run-test-and-schedule)
  - [Logs & diagnostics](#logs--diagnostics)
  - [SMTP settings](#smtp-settings)
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
to hand-create anything. An in-app **Help guide** (menu → Help) walks through everything below,
and every field has a tooltip.

### Create a job

Click **+ New Job**. The editor is organized in sections:

**Input**
- **Job name** — unique; also used in output filenames.
- **Input Excel file** — browse to the `.xlsx`/`.xlsm`. The app **discovers the sheet names**
  automatically; tick the sheets to process. (Stored by *name*, so reordering sheets is safe.)

**Output**
- **Output folder** — browse to where results are saved, or leave empty to save **next to the
  input file**.
- **Filename** — optional stem; empty means `{job}_{date}`. Placeholders: `{job}`, `{date}`,
  `{datetime}`, `{run_id}`. A live example shows the resulting names. Each run writes
  `<name>.xlsx` plus one `<name>_<sheet>.pdf` per selected sheet.
- **Freeze formulas to values** / **Generate PDF** toggles.

**Schedule** — visual builder: **Manual**, **Daily**, **Weekly** (weekday picker),
**Monthly** (day-of-month picker), or **Advanced (cron)**. Add **multiple run times per day**
(e.g. 06:00 and 18:00) in any preset mode.

**Email** — subject, recipients, and the in-app template editor (next section).

**Advanced** (collapsed by default) — **Timeout** (max seconds before a hung run is killed)
and **Concurrency group** (jobs sharing a group run one-at-a-time), plus notes.

Only the input file, at least one sheet, and the **To** addresses are required. Everything
optional can be left blank.

### Recipients & email template

Each job has two recipient sets — **production** and **test** — each with **To** (required),
**Cc** (optional), and **Bcc** (optional).

- **Test runs** email the **test** recipients only — they can never reach production addresses.
- **Real runs** email the **production** recipients only if **"Email report … on real runs"**
  is enabled. Failures never send an automatic email.
- Report emails attach the **output Excel** plus **all per-sheet PDFs**.

The email **body** is authored in-app: click **Edit email template…** in the job editor and
write it in **Simple** mode (plain text + placeholder-insert buttons) or **HTML** mode, with a
live **Preview** against sample data. The template is stored per job; leave it untouched to use
the built-in default.

### Run, test, and schedule

- **▶ Run** (on the job card) — a real run (production recipients, if enabled).
- **🧪 Test** — a test run to the test recipients, subject prefixed `[TEST]`.
- **Schedule** — the service runs enabled jobs on their configured times automatically; each
  configured time registers its own trigger.

Multiple jobs run in parallel, each in its own disposable worker process. A failed run is never
retried automatically — it's recorded and visible in the history.

### Logs & diagnostics

- **Logs** on a job card — that job's run history: status, timings, output paths, error
  summary, and the worker log tail. It refreshes live while a run is in progress.
- **File → Application logs** — the full rolling logs of the Service, Worker, and UI.
- **File → Send logs to support** — emails a diagnostic bundle (logs + sanitized settings,
  never passwords) to the configured support email.
- **File → Open data folder** — opens `C:\ProgramData\ReportFlow` in Explorer.

### Settings (SMTP, support email, application)

**File → Settings** configures everything in-app:

- **SMTP** — host, port, STARTTLS/SSL, from-address, username, and the **password** (stored
  encrypted via Windows DPAPI, machine scope — never in the config file). An eye icon shows
  the password while typing, and **Test connection** verifies the settings against the mail
  server without sending anything.
- **Test & support email** — global test-run fallback recipients and the support address
  that receives diagnostic bundles.
- **Application** — max parallel runs, default timeout, log retention, and the startup
  update-check toggle.

### Import, export & updates

- **File → Export/Import jobs…** — back up or move jobs between machines as JSON. Pick
  which jobs to include (some or all); on import, name clashes prompt per job:
  Overwrite / Skip / Import as copy.
- **File → Export/Import settings…** — the same for application settings. The SMTP
  password never travels; re-enter it after importing.
- **Updates** — the app checks GitHub for a newer release at startup (skipped when
  offline; toggleable in Settings) and via **Help → Check for updates…**. Nothing installs
  until you click **Update now**; the download shows progress and the installer upgrades
  automatically, preserving jobs, settings, and logs.

### Workbooks using PI DataLink (or other Excel add-ins)

**PI DataLink is a VSTO add-in that uses Windows-integrated security, and it cannot load
when the service runs as LocalSystem** (the default). With no user profile / VSTO cache / PI
identity, `.Connect` fails with *"the add-in could not be installed"*, its worksheet
functions are unregistered, and every PI cell comes out as **`#NAME?`** — a broken report,
not an empty one. The legacy Task Scheduler script worked only because it ran **as the
desktop user**.

**Fix — run the service as a PI-enabled Windows user** (one that has PI DataLink installed
and PI access):

- **Existing install, no reinstall:** in an **elevated** PowerShell run
  `scripts\set-service-account.ps1 -User "DOMAIN\your_pi_user"`. It sets the service log-on
  account (NSSM grants the log-on-as-a-service right), restarts the service, and prints the
  resulting identity.
- **Fresh install:** the installer asks for an optional **service account** — enter the
  PI-enabled user there.
- **Verify:** **File → Settings → Application → "Service runs as"** shows the account (and
  warns in red if it is LocalSystem); the dashboard shows a warning banner too. Then click
  **🔍 Dry run** on the job — the worker log should read `Executing as DOMAIN\your_pi_user`
  (no trailing `$`) and `COM add-in 'PI DataLink': connected=True`, with real values.

**Error cells are reported, not fatal.** Pre-existing errors like `#REF!` no longer block
delivery — the report is sent and the errors show as a *warning* on the run. Strip them with
the **Blank out values** list (e.g. `#REF!, #N/A`), or tick *"Fail the run if a sheet has
error cells (strict)"* to fail instead. If a sheet is only partly filled, the add-in's data
was still arriving at freeze time — raise **Extra wait after refresh** (ReportFlow waits
adaptively up to that budget and logs when data is still changing at the end).

**"Cannot be opened" output.** Removing unselected sheets can break a chart/defined name that
referenced them, and Office File Validation then blocks the file. ReportFlow purges broken
`#REF!` defined names automatically; if a report still won't open, set that job's **Unselected
sheets** option (Advanced) to **Hide** — the others become very-hidden, references stay
intact, and the file always opens. If the *input* file won't open by hand, it carries a
Mark-of-the-Web: right-click → Properties → **Unblock** (or add its folder as a Trusted
Location); reports still generate because the service opens files via automation.

**Dry run** (🔍 on each job card) builds the full report and runs the checks but never emails
— use it to confirm PI data before relying on scheduled delivery.

**Email failures no longer pass silently:** when a run builds but the email cannot be sent,
the app pops a warning, the card shows a **✉ failed** marker, and the run history's
**email:** line gives the reason. When SMTP is down and you need to hand logs to support,
use **File → Export logs to zip…** to save the diagnostic bundle locally.

### Where data lives

Everything runtime lives under **`C:\ProgramData\ReportFlow\`**:

```
config\reportflow.toml     application + SMTP + job definitions
templates\email\default.html   default email body
templates\jobs\<job>.html  per-job email templates authored in-app
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

### Test the full app locally — no build, no installer

Goal: exercise the real service + UI + worker against a real workbook (e.g. a PI DataLink
file) on your dev machine before pushing anything.

```powershell
# 1) Isolated data dir so your real ProgramData isn't touched (per terminal!)
$env:REPORTFLOW_DATA_DIR = "C:\temp\reportflow-dev"

# 2) Start the service (terminal 1)
uv run python -m reportflow.service

# 3) Start the UI (terminal 2 — set REPORTFLOW_DATA_DIR here too)
uv run python -m reportflow.ui
```

Create the job in the UI exactly as on the server (pick your workbook, tick the report
sheets), hit **🧪 Test**, and inspect the run log + output files.

**Fake the email sending** (nothing leaves your machine): in a third terminal run

```powershell
uv run python scripts/dev_smtp_server.py        # listens on 127.0.0.1:2525
```

then in the UI set Settings → SMTP to host `127.0.0.1`, port `2525`, no TLS, empty
username/password. Every email ReportFlow "sends" is printed by that terminal and saved
under `scripts\sample\outbox\*.eml` (double-click opens in Outlook). **Test connection**
also works against it.

Worker-only quick loop (no service/UI):

```powershell
uv run python scripts/dev_run_worker.py --template "D:\path\to\MyReport.xlsx" --sheets "Sheet A" "Sheet B"
```

### Build & test the executables locally

```powershell
uv run python packaging/build_all.py            # dist\worker, dist\service, dist\ui
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

```powershell
uv run python packaging/build_all.py            # all three
uv run python packaging/build_all.py worker     # just one
```

Output (onedir bundles): `dist/worker`, `dist/service`, `dist/ui`. Validate the frozen UI's Qt
platform plugin without a visible window:

```powershell
dist\ui\reportflow-ui.exe --selftest    # exits 0 if qwindows.dll loaded
```

### Build the installer

Requires [Inno Setup 6](https://jrsoftware.org/isdl.php) and `packaging/nssm/nssm.exe`
(download the 64-bit binary from [nssm.cc](https://nssm.cc/download)).

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=0.1.0 packaging\innosetup\reportflow.iss
# -> packaging\innosetup\Output\ReportFlow-Setup-0.1.0.exe
```

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
packaging/         PyInstaller specs, build_all.py, Inno Setup, NSSM
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

[email]
default_template_path = "email/default.html"   # relative to templates\

[test]
recipients = ["dev-team@corp.example.com"]
developer_bundle_recipients = ["dev-team@corp.example.com"]

[[job]]
name = "daily_sales"
enabled = true
input_excel_path = "C:/Templates/daily_sales.xlsx"
email_template_path = 'C:/ProgramData/ReportFlow/templates/jobs/daily_sales.html'  # optional
output_dir = "C:/Reports/daily_sales"     # optional; empty -> next to the input file
output_name = "{job}_{date}"              # optional filename stem; PDFs get _<sheet> suffix
sheet_names = ["Summary", "Detail"]       # names, not indexes
freeze_values = true
generate_pdf = true
schedule_crons = ["0 6 * * MON-FRI", "0 18 * * MON-FRI"]   # one trigger per entry
timeout_seconds = 1200
concurrency_group = "reports"
subject = "Daily Sales — {date}"
send_report_email = true                  # real runs email prod only if true

  [job.prod]
  to  = ["managers@corp.example.com"]
  cc  = ["ops@corp.example.com"]          # optional
  # bcc = [...]                           # optional

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
| `GET /jobs` · `GET/POST/PUT/DELETE /jobs/{name}` | Job CRUD. |
| `POST /jobs/{name}/run` · `POST /jobs/{name}/test` | Trigger a real / test run. |
| `GET/PUT /jobs/{name}/email-template` | Read / write the job's per-job email template. |
| `GET /runs` · `GET /runs/{id}` · `GET /runs/{id}/log` | Run history and logs. |
| `POST /workbook/sheets` | Discover sheet names (openpyxl, no COM). |
| `POST /email/preview` | Render the email template with sample data. |
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

### CI/CD & releases

- **`.github/workflows/ci.yml`** (push/PR, `windows-latest`): `ruff check`, `ruff format
  --check`, `mypy`, `pytest -m "not excel"`, and Conventional-Commits linting on PRs.
- **`.github/workflows/release.yml`** (tag `v*`): builds the three exes, fetches NSSM, compiles
  the Inno Setup installer, generates the changelog with git-cliff, and publishes a GitHub
  Release with the installer + zipped executables.

Commits follow [Conventional Commits](https://www.conventionalcommits.org/); the changelog is
generated from history by [git-cliff](https://git-cliff.org/).
```

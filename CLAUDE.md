# ReportFlow — project guide for Claude

Windows desktop automation for Excel-based reporting, deployed at Aditya Birla / Hindalco.
A job = "open this workbook, refresh its data, freeze formulas to values, export per-sheet
PDFs, email the result — on a schedule".

## Architecture: three executables, one package

Single `src`-layout package `reportflow`, three entry points (see `pyproject.toml`):

| Exe | Module | Stack | Runs as |
|---|---|---|---|
| UI | `reportflow.ui` | PySide6, dark theme only | interactive user |
| Service | `reportflow.service` | FastAPI + APScheduler, hosted by **NSSM** | a Windows service account |
| Worker | `reportflow.worker` | xlwings / pywin32 COM | spawned per run by the service |

Flow: **UI → HTTP (localhost:8787) → Service → spawns one disposable Worker per run.**
The UI never touches Excel or config directly — everything goes through `ui/api_client.py`.
The service writes `request.json`, the worker writes `result.json` (`core/ipc/contract.py`
is the schema; it is the contract between the two processes).

- Data root: `%ProgramData%\ReportFlow` (config / logs / state / runs / templates) so the
  service and the interactive user resolve to the **same** dir — never `%APPDATA%`.
  Override with `REPORTFLOW_DATA_DIR` (tests/dev use this). See `core/paths.py`.
- Version is single-sourced from `pyproject.toml`, read at runtime via
  `importlib.metadata.version("reportflow")` (`src/reportflow/__init__.py`). PyInstaller
  specs bundle it with `copy_metadata("reportflow")`. **Never hardcode a version.**

## Hard rules (do not break these)

1. **Never modify or save the SOURCE workbook.** The output is always a copy. There is a
   deliberate guard in `worker/excel.py::save_output` — keep it.
2. **Secrets never touch the config file.** SMTP + service-account passwords go through
   DPAPI/keyring (`core/secrets.py`). Never log a password; never return one from the API.
3. **A test run can never email production.** The guard lives in exactly one place
   (`core/email/sender.py::resolve_recipients`). Keep it that way.
4. **Non-mandatory settings stay optional.** `To` is required; `Cc`/`Bcc` optional. Don't
   make a new setting mandatory without asking.

## Field-proven gotchas (each cost real debugging — don't regress them)

- **PI DataLink returns `#NAME?` under LocalSystem.** It's a *VSTO* add-in using
  Windows-integrated security: it cannot load with no user profile (the account shows as
  `COMPUTERNAME$`). Every PI cell becomes `#NAME?` — **broken, not empty**, which is why an
  empty-sheet check never caught it. Fix = run the service as a real PI-enabled user
  (in-app: Settings → Service account; or NSSM `ObjectName`). See
  `service/service_account.py`.
- **Version looked stale after an in-place upgrade.** Each frozen app bundles a
  *version-stamped* `reportflow-<ver>.dist-info`; Inno's `[Files]` only adds/overwrites and
  never deleted the old folder, so `importlib.metadata` could return the older one. Fixed by
  `[InstallDelete]` in `packaging/innosetup/reportflow.iss`. If you add a new frozen dir,
  add its dist-info to that section.
- **Error cells are delivered, not fatal.** `fail_if_sheet_has_errors` defaults **False**:
  pre-existing `#REF!` etc. are reported as run *warnings* and the report still goes out.
  Strict failing is opt-in. (Real jobs have permanent `#REF!` cells; failing blocked
  delivery.)
- **"Office has detected a problem with this file."** Removing non-selected sheets orphans
  defined names/charts → broken `#REF!` → Office File Validation blocks the file. We purge
  broken `#REF!` defined names after removal; the per-job **Hide** mode (very-hidden sheets)
  is the guaranteed-openable fallback. On the *input* side the same message means
  Mark-of-the-Web → Unblock / Trusted Location (automation still opens it).
- **PI data arrives AFTER Excel says calculation is done.** A fixed sleep froze sheets
  half-populated. `refresh_and_wait` settles *adaptively* — recalculate until the populated
  cell count stops growing, bounded by the job's `post_refresh_wait_seconds` budget — and
  logs a warning if data is still changing when the budget runs out.
- **Email policy is counter-intuitive; state it explicitly.** A scheduled/manual **Run**
  with `send_report_email` unticked emails **no one** — not even test recipients. Only an
  explicit **Test email** run mails the test recipients. (`service/launcher.py::_maybe_email`)
- **Inno Setup / ISPP:** a `{code:Fn}` scripted constant *must* be
  `function Fn(Param: String): String`. Any line whose first non-whitespace char is `#` is
  read as a preprocessor directive — never start a continuation line with `#13#10`.

## Dev workflow

```bash
uv sync                      # deps
uv run reportflow-service    # run service locally
uv run reportflow-ui         # run the UI
```

**The gate — all four must pass before committing:**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not excel"
```

- `-m "not excel"` is the CI/default suite. The `excel` marker means "needs a real local
  Excel install"; run `uv run pytest -m excel` locally when touching `worker/excel.py`
  (~2 min, spawns real Excel).
- UI tests are pytest-qt offscreen with a `FakeApi` stub (`tests/ui/test_ui.py`) — no
  service, no Excel. Service tests use `tests/service/fake_worker.py` (modes:
  success/fail/crash/hang/warn) and `aiosmtpd` for SMTP.
- Line length 100. Ruff lint: `E,F,I,UP,B,W`.

## Release

1. Bump `version` in `pyproject.toml` (single source).
2. Gate green + `uv run pytest -m excel`.
3. Validate the installer compiles:
   `"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=X.Y.Z packaging\innosetup\reportflow.iss`
4. Commit to `main`, tag `vX.Y.Z`, push both → GitHub Actions builds the installer and
   publishes the release. The in-app updater reads the latest GitHub release and runs the
   setup exe with `/SILENT` (so installer wizard pages, incl. the welcome page, never show
   on that path).

Repo: `github.com/viru185/ReportFlow` · Inno AppId `{7F3C6A20-9B4E-4E2A-9C1D-REPORTFLOW01}`
(the uninstall registry key is that AppId + `_is1`).

## Conventions

- Comments explain *why* / non-obvious constraints, not what the next line does. Match the
  surrounding density — this codebase comments the reasoning behind field fixes.
- Docstrings on modules explain the module's role and the reasoning behind its design.
- User-facing copy avoids jargon: prefer "Build only" over "Dry run", say exactly what will
  and won't happen (see the email hint in `ui/windows/job_editor.py`).
- UI principle (from the product owner): simple, functional, minimum wasted space, any level
  of user should manage. **If one click can do the job, don't make it two** — no dropdown
  menus for primary actions.

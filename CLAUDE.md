# ReportFlow — project guide for Claude

Windows desktop automation for Excel-based reporting, deployed at Aditya Birla / Hindalco.
A job = "open these workbooks, refresh their data, freeze formulas to values, export per-sheet
PDFs, email the result — on a schedule". A job has one or more workbooks
(`JobConfig.workbooks`), each with per-sheet options (`SheetOptions`: pdf / hidden) and what
happens to the sheets it doesn't include (`unselected_sheets`: remove / hide / keep). One run
builds every workbook in ONE Excel session and sends ONE email.

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
is the schema; it is the contract between the two processes — `WorkerRequest.workbooks`
in, `WorkerResult.output_xlsx_paths` out). Service and worker ship in one installer, so the
contract can change freely; the CONFIG cannot — old job shapes must keep loading.

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
3. **A testing-stage/test-flagged run can never email production.** The recipient guard
   lives in exactly one place (`core/email/sender.py::resolve_recipients`). Keep it that
   way. Jobs have a lifecycle `stage` ("testing" → "live", `JobConfig.stage`): testing
   jobs email ONLY the Test recipients on every run (manual and scheduled); promotion to
   live (card "Go live" / `POST /jobs/{name}/stage`) switches runs to production. The
   launcher resolves `is_test` from the stage at fire time (`Launcher._resolve_is_test`).
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
- **PI data arrives AFTER Excel says calculation is done — and a spill can COLLAPSE
  mid-recalc.** A fixed sleep froze sheets half-populated (0.6.2 added adaptive settle);
  then the Equipment/Sensor report shipped one sheet empty because the settle judged
  stability with `sig <= prev` over a SUMMED count — a collapsed `PINCompDat` dynamic-array
  spill (count *drops*) read as "stable". The settle now tracks counts **per sheet**
  against **opening baselines** (the template's cached values, captured in
  `open_workbook`): stable = exactly unchanged everywhere, a decrease resets, no sheet may
  sit below its baseline, one bounded 30 s grace past the budget, then a deliver-anyway
  warning naming the lagging sheet. Pure predicate: `worker/excel.py::_settle_verdict`.
- **PasteSpecial leaves the whole used range selected and Excel persists it into the
  file** — recipients opened reports with everything highlighted. `collapse_selection`
  selects A1 per sheet and leaves the first selected sheet active before every save.
- **The old `send_report_email` checkbox is gone (0.8.0).** Legacy configs migrate via a
  `JobConfig` before-validator: `send_report_email=True` → `stage="live"`, else testing.
  Never re-add the key; never persist it.
- **Pre-0.11 jobs are single-workbook** (`input_excel_path`, `sheet_names`, job-wide
  `generate_pdf`, `keep_only_selected_sheets`/`unselected_sheets_mode`).
  `core/config/models.py::migrate_legacy_job` turns them into `workbooks[0]` — used by the
  JobConfig validator (config files, imports) and by the editor's `_load`. Never write the old
  keys back.
- **PDF before hiding.** Excel cannot export a hidden sheet, so per workbook the worker runs:
  freeze → empty-check → drop/hide not-included sheets → PDFs → `collapse_selection` over the
  VISIBLE included sheets → hide the included sheets marked Hidden → save
  (`worker/runner.py::_build_workbook`). At least one included sheet must stay visible
  (validated in the model and the editor).
- **Overlapping schedule rules double-fire.** Each cron is its own APScheduler trigger, so
  "daily 06:00" + "Sunday 06:00" would start two runs (two emails). `ui/schedule_compile.py::
  compile_rules` refuses that; keep the check when touching schedules.
- **Duplicate / editor round-trip guard.** `tests/ui/test_ui.py::_every_field_job` sets every
  `JobConfig` field and asserts Duplicate and an open-and-save round trip lose nothing. A new
  JobConfig field must be added there (the test fails until it is) — that's the point.
- **Log/dir growth is bounded by `core/maintenance.py::purge_logs`** — startup + nightly
  (03:30) via APScheduler. `SchedulerService.rebuild()` wipes ALL jobs, so the maintenance
  job is re-registered inside `rebuild`; keep that invariant. Live per-process log files
  and active runs are never deleted.
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

New features ship as a **beta first** (owner's workflow since 0.11):

1. Bump `version` in `pyproject.toml` (single source) — `X.Y.Z-beta` for a beta, `X.Y.Z`
   for the final release. `release.yml` fails if the tag disagrees
   (`scripts/check_release_tag.py`).
2. Gate green + `uv run pytest -m excel`.
3. Validate the installer compiles:
   `"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=X.Y.Z packaging\innosetup\reportflow.iss`
   (a beta also needs `/DMyAppNumericVersion=X.Y.Z` — Windows file versions are numeric).
4. **Beta:** tag `vX.Y.Z-beta` (any branch) and push it → published as a GitHub
   **pre-release**, never "latest", no CHANGELOG commit. **Final:** merge to `main`, tag
   `vX.Y.Z`, push both → normal release. The in-app updater reads the LATEST release (betas
   are invisible to it) and runs the setup exe with `/SILENT` (so installer wizard pages,
   incl. the welcome page, never show on that path). Release notes cover everything since
   the last stable tag; beta tags are `ignore_tags` in `cliff.toml`. A final release
   regenerates `CHANGELOG.md` and commits it to `main` as the actions bot (`[skip ci]`) —
   don't edit that file by hand.

Betas are **never numbered** (owner's rule): a fix to `v0.11.0-beta` ships as
`v0.11.1-beta` — bump the version, don't use `-beta.2`.

Commits: author Viren Hirpara, **no co-author trailer**.

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
  menus for primary actions. Owner-approved amendment (2026-07-23): *occasional* job-card
  actions (Open report / Edit / Logs / Duplicate / Pause / Delete) live behind the card's ⋯
  menu; only daily actions (Run, Build only, Go live/Resume) stay as visible buttons. Don't
  "fix" that back to a button row — 9+ visible buttons per card was the problem.

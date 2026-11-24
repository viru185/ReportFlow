# ReportFlow — project guide for Claude

Windows desktop automation for Excel-based reporting.

Public-repository privacy: use fictional identities and generic examples only. Never
commit customer names, domains, accounts, server names, identifying paths, or diagnostic
output. Keep operational evidence outside tracked files and release artifacts.
A job = "open these workbooks, refresh their data, freeze formulas to values, export per-sheet
PDFs, email the result — on a schedule". A job has one or more workbooks
(`JobConfig.workbooks`), each with per-sheet options (`SheetOptions`: excel / pdf / hidden) and what
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
in, `WorkerResult.output_xlsx_paths` for local reports and `attachment_paths` for email out). Service and worker ship in one installer, so the
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
   live (card "Move to production" / `POST /jobs/{name}/stage`) switches runs to production.
   The launcher resolves `is_test` from the stage at fire time (`Launcher._resolve_is_test`).
   Users see the stage through `core/config/models.py::STAGE_LABELS` — "live" is shown as
   **Production** (0.12; "Live" read as "running now" on a paused job). Never show "Live".
4. **Non-mandatory settings stay optional.** `To` is required (an address or an email group);
   `Cc`/`Bcc` optional. Don't make a new setting mandatory without asking.
5. **Every address is emailed once.** Email groups are expanded in exactly one place,
   `core/email/recipients.py::resolve` (To > Cc > Bcc, case-insensitive). The sender and the
   template preview follow that rule; the editor additionally refuses overlaps as they are
   typed (`RecipientSet`, below), with `resolve` as the safety net for old jobs. **Order is
   kept** (0.15): `Recipients.to/cc/bcc` are ONE ordered list each — an address is a string, a
   group `{group = "..."}` (`GroupRef`) — and the email lists people in that order, a group's
   members at its place. Pre-0.15 `to_groups`/`cc_groups`/`bcc_groups` fold in after the
   addresses (`Recipients._fold_legacy_groups`), which is how they were sent. Likewise the
   subject (`[TEST] ` prefix included) comes only from `core/email/render.py::final_subject`,
   which the sender and the template preview share — don't build a subject anywhere else.

## Field-proven gotchas (each cost real debugging — don't regress them)

- **PI DataLink returns `#NAME?` under LocalSystem.** It's a *VSTO* add-in using
  Windows-integrated security: it cannot load with no user profile (the account shows as
  `COMPUTERNAME$`). Every PI cell becomes `#NAME?` — **broken, not empty**, which is why an
  empty-sheet check never caught it. Fix = run the service as a real PI-enabled user
  (in-app: Settings → Service account; or NSSM `ObjectName`). See
  `service/service_account.py`.
- **A real service account is not enough for PI DataLink: VSTO must TRUST it for that
  account** (Merian, Oct–Nov 2026). VSTO refused the add-in — "has not been granted trust …
  not on the inclusion list" — because trust is per account and a service never sees the
  one-time prompt. Every "successful" run then emailed the workbook's last-saved PI values.
  `core/vsto_trust.py` (Settings → Service account → Fix PI DataLink) writes the same
  `HKCU\Software\Microsoft\VSTO\Security\Inclusion\<guid>` entry (`Url`, `PublicKey`) the
  prompt would — verified against Microsoft's `UserInclusionList` — only for HKLM-registered
  PI add-ins, and only inside the service process (its HKCU is the service account's).
- **Trusted is not enough either: Excel can switch PI DataLink off for good (HIL, Sep–Nov
  2026).** Excel crashed (busy 3-job starts, a startup retry killing a hung Excel) while loading
  PI DataLink, so it put PI DataLink on the account's `HKCU\Software\Microsoft\Office\<ver>\
  Excel\Resiliency\DisabledItems` and never loaded it again: `COMAddIn.Connect = True` →
  E_ABORT `0x80004004`, no VSTO message, two months of stale PI reports; clicking Trust fixed
  only PIAFBuilder. `core/excel_disabled.py` removes PI entries (and their `StartupItems` crash
  markers) — never others: the list also holds documents. Matched by text, not by the
  REG_BINARY layout. Same button as trust ("Fix PI DataLink", in the service process). Stop and
  timeouts kill Excel too — a run warning names this cause first.
- **The service can't restart itself from inside its own process tree.** NSSM kills the
  tree on stop, so the 0.11 `cmd /c timeout … & nssm restart` helper never restarted it
  after an account change. Now `service_account.schedule_restart` exits with code 75; the
  installer maps that to a stop with an error (`nssm set ReportFlow AppExit 75 Exit`) and
  enables recovery for it (`sc failure` + `sc failureflag 1`), so Windows starts the
  service again under the new logon. Keep those three installer lines with the code.
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
  then a report shipped one sheet empty because the settle judged
  stability with `sig <= prev` over a SUMMED count — a collapsed `PINCompDat` dynamic-array
  spill (count *drops*) read as "stable". The settle now tracks counts **per sheet**
  against **opening baselines** (the template's cached values, captured in
  `open_workbook`): stable = exactly unchanged everywhere, a decrease resets, no sheet may
  sit below its baseline, one bounded 30 s grace past the budget, then a deliver-anyway
  warning naming the lagging sheet. Pure predicate: `worker/excel.py::_settle_verdict`.
- **Never freeze through the clipboard (0.16).** Copy → PasteSpecial hung inside the service
  (session 0: Office's clipboard use is unsupported; every run shares one clipboard, so two
  runs could also paste each other's data) — the 2026-11-24 server hangs all sat in it.
  `worker/freeze.py` reads the used range first (bulk `Formula` + `Value2`; replacing a spill
  anchor clears its children), writes formula results back as values in rectangles, quotes any
  text Excel would re-read when written (a digit, `= + - @ ' #`, TRUE/FALSE — "1-2" became a
  date AND got a date format), and freezes leftovers one by one (a write overlapping part of a
  legacy array is ignored WITHOUT an error). A sheet without formulas is never written.
  Calculation is manual while freezing and always restored (the mode is saved in the file).
- **Stopping a run: kill the worker FIRST, then its Excel — by verified PID (0.16).** Excel is
  started by COM (DCOM launches it), not as the worker's child, so a process-tree kill of the
  worker never reached it: a timed-out run left EXCEL.EXE holding the workbook, and the next run
  opened it read-only. Kill Excel first and the worker's COM retry just starts a new one. The
  worker records itself and every Excel it starts (a retry starts another) in
  `runs/<id>/progress.json`; `core/procs.py::kill_verified` kills one only if PID + image name +
  create time all match (PIDs are reused). Same path for Stop, timeout, service shutdown and
  restart recovery (`Launcher.recover_interrupted`: RUNNING rows the new service doesn't own →
  *interrupted*). Shutdown needs NSSM `AppStopMethodConsole 15000` (installer) to get its time.
- **One admission queue (0.16).** `service/launcher.py` admits a run only when it can take ALL
  its resources at once — its input files (normalised paths), its concurrency group, a global
  slot (cap read live) — first come first served with reservations, so two jobs never open the
  same workbook together (field: both hung) and nothing deadlocks. One run per job
  (`JobBusyError` → 409; the scheduler logs a skip). A waiting run's `waiting_for` is what the
  card shows. Purge must spare `inflight_run_ids()` — queued runs too.
- **Each run opens a PRIVATE COPY of its workbook (0.16).** A workbook open on someone's PC
  made runs open it read-only (133 runs on the customer server). `worker/private_copy.py`
  copies the last saved file to `runs/<id>/inputs/<n>/<same name>` (share-read works while it
  is open) and rewrites same-folder external links in `xl/externalLinks/_rels/*.rels` to the
  original folder BEFORE opening (no `ChangeLink`: it refreshes and can prompt). The save guard
  protects original and copy. `inputs/` is deleted after the run and by the launcher after
  stop/timeout/recovery, and "Export logs" never includes it (customer data). Opt-out per job
  (`private_copy`) for macros that use `ThisWorkbook.Path`.
- **Old reports are deleted only from `report_files` (0.16).** "Delete this job's reports
  after N days" deletes nothing it didn't record: each run's outputs go into `runs.db`'s
  `report_files` (path NOCASE, mtime, size), kept apart from the run history so the log purge
  can't lose them. A file whose mtime/size changed is someone's — kept and forgotten; the
  newest run's and newest successful run's files are always kept. `core/report_cleanup.py`.
- **Excel persists each sheet's selection into the file** — recipients once opened reports
  with everything highlighted. `collapse_selection` selects A1 per sheet and leaves the first
  selected sheet active before every save.
- **Real-Excel tests: assert after the Excel session ends.** A failing assert inside it keeps
  COM proxies alive in the traceback past CoUninitialize and breaks the next test with RPC
  faults (`tests/worker/test_freeze_excel.py::_freeze_and_measure`). A run's teardown calls
  CoUninitialize on the TEST thread too, so a second Excel the test itself opened is cut off —
  hold a workbook "open elsewhere" from a subprocess (`test_private_copy_excel.py`).
- **A wrapped QLabel next to a nested layout in a form is too tall.** Its size hint assumes a
  narrow width, and a QFormLayout row whose field is a box layout is laid out at that hint —
  a 2-line hint got room for 5 (gap, page scrolling for nothing). Use `kit.WrapLabel` for
  wrapped help text: its hint is its height at its real width.
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
uv sync --all-extras         # deps (plain `uv sync` removes ruff/mypy/pytest/PyInstaller)
uv run reportflow-service    # run service locally
uv run reportflow-ui         # run the UI
uv run reportflow-build [worker|service|ui|installer|all ...]   # local build
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
2. Write the version's section at the top of `src/reportflow/ui/help/whats_new.md`
   (Help → What's new; New / Fixed / Faster, for users). `uv run python scripts/whats_new.py
   X.Y.Z` drafts it from the feat/fix/perf commits — rewrite it. A test fails when the file's
   newest section is older than `pyproject.toml`, and when `ui.spec` misses a help file.
3. Gate green + `uv run pytest -m excel`.
4. Validate the installer builds: `uv run reportflow-build all` (exes + installer;
   finds Inno Setup 7/6 itself, passes the version and the numeric file version a beta
   needs, and refuses `dist\` exes from another version). CI still calls ISCC directly
   (`release.yml`, the runner's preinstalled Inno Setup 6).
5. **Beta:** tag `vX.Y.Z-beta` (any branch) and push it → published as a GitHub
   **pre-release**, never "latest", no CHANGELOG commit. **Final:** merge to `main`, tag
   `vX.Y.Z`, push both → normal release. The in-app updater reads the LATEST release (betas
   are invisible to it) and runs the setup exe with `/SILENT` (so installer wizard pages,
   incl. the welcome page, never show on that path). Beta release notes cover changes since the previous release tag. Final release notes cover
   changes since the previous stable tag. `scripts/release_notes.py` generates one version
   section and omits internal commit categories. A final release
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
  menu; only daily actions (Run, Build only, Move to production/Resume) stay as visible
  buttons. Don't
  "fix" that back to a button row — 9+ visible buttons per card was the problem.
- **The owner is very sensitive to unpolished UI.** After ANY UI change: run the full gate,
  then render the changed screens (offscreen `QWidget.grab()` with the real Windows fonts) in
  their empty / typical / many-items / error states at the editor default 900×680, 1280×800
  and the dialog's minimum size, check them (8/12/16 spacing, no clipping or sideways scroll,
  no overlapping corners, colours only from `style.py` tokens), fix, and only then move on.
  When there are several reasonable designs, ask; suggest extra UX improvements for the owner
  to decide rather than slipping them in. Use REALISTIC data (8+ long-named workbooks, a long or
  UNC path, 15 sheets, long addresses) and also render at 150% (`QT_SCALE_FACTOR=1.5`, the
  owner's laptop) — 0.13 passed QC on `C:/a.xlsx` fixtures and broke on real names. Grab the
  popups too (menus, tooltips, dropdown / completer lists, popovers).

## UI building blocks (0.13, kit in 0.14)

- **Build UI from `ui/kit`, never raw widgets.** `Button(variant=primary|secondary|quiet|danger|
  quiet-danger|dashed)`, `SegmentButton`+`segmented`, `IconButton(variant=icon|icon-danger|close|
  dismiss|tool)`, `ComboBox` (rounded drop-below list, middle-elided text, wheel only when
  focused), `SpinBox`/`TimeEdit`, `ListWidget`/`TableWidget`/`ScrollArea` (pixel + smooth
  scroll, never sideways), `Menu`, `Popover` (frameless Qt.Popup panel under its anchor: Esc or
  a click outside closes it — the app's replacement for small dialogs), `ElidedLabel`,
  `PathLabel`, `Tag`, `breakable()`, `Reorder` (0.15, below). The look stays in `style.py`, keyed by the `variant` /
  `tag` / `badge` / `tone` / `banner` properties — colours only from its tokens.
  `tests/ui/test_kit_usage.py` fails on raw `QPushButton(`, `QComboBox(`, `QMenu(`… or
  `setStyleSheet(` outside `kit/` and `style.py` (an inline stylesheet also restyles that
  widget's tooltip — the 0.13 amber square tooltip).
- **Rounded popups need translucent windows, set BEFORE the first show** (`kit.popups.
  round_popup`); `kit.chrome.install_chrome` (run by `apply_theme`) does it for Qt's own menus
  and tooltips at Polish time. A translucent top-level QAbstractScrollArea paints NO stylesheet
  background — so a QCompleter gets `kit.views.PopupList`, which paints its own panel
  (`styled_completer`). QCompleter.setPopup replaces the item delegate: set yours after it.
- **Never let QCompleter handle Enter in a field that rebuilds its model on change.** It
  forwards Return to the line edit (editingFinished) and then completes a remembered row number
  — after the first add rebuilt the list, the next address had moved into that row (0.13: one
  Enter added two people). `RecipientField` filters the popup's Return/Enter/Tab itself (picks
  the highlighted row, or row 0), and commits typed text on FocusOut, not editingFinished.

- **Feedback, `ui/feedback.py`.** Information and success → `toast()` (fades, stacks, optional
  Undo action). Validation → `set_field_error(widget, message, help_anchor)` under the field
  (with a "Learn more" link to that Help section) + `mark_tab_errors()` dots; the dialog switches
  to the first bad tab. `field_error()` returns the plain message. Decisions (delete / discard / move to production) and
  errors with long details stay `QMessageBox`. Don't add OK pop-ups for good news.
- **`FormDialog`** (job editor, Settings, template editor): Enter is swallowed (it never closes
  a form — the owner's bug report), Ctrl+S saves, F1 opens Help at `help_anchor()`, Esc / Cancel
  / × go through `confirm_discard` when the canonical `_dirty_key()` changed, and geometry is
  remembered (QSettings, IniFormat). `tests/ui/conftest.py` isolates QSettings and auto-answers
  the discard prompt so qtbot teardown never blocks.
- **Recipients, `ui/recipient_field.py::RecipientSet`.** One coordinator per To/Cc/Bcc set:
  `vet()` refuses duplicates and addresses a group in the set already covers, a new group
  removes the chips it covers (with Undo, back in place) but never demotes from a higher field,
  and the completers leave out everything already included. `set_entries()` NEVER applies these
  rules — loading a job must not change it (or fire the unsaved-changes prompt). Chips (0.15):
  drag within / between boxes of one set, double-click or F2 edits an address in place, a
  right-click menu, ←/→/Alt+←/→/Delete. A move or an edit goes through `vet(..., ignore=chip)`;
  chips are rebuilt only AFTER `QDrag.exec` / `Menu.exec` return (never inside the nested
  loop). The in-place editor's QSS `min-height` must keep it at the chip's 24 px — a min above
  its fixed height broke the box's height-for-width (rows clipped). Double-clicking a group
  chip opens `ui/group_editor.py::EmailGroupDialog` (saves to Settings at once; the editor renames
  its chips); `group_name_problem` is the one name rule, shared with Settings. There is no global
  test-recipient fallback (removed 0.14; `TestSettings` drops an old `recipients` key on load).
- **Workbooks.** `_WorkbookState` is the single source of truth: table edits write straight
  into the current workbook's state (no commit-on-switch — a background result merged into the
  visible workbook would be overwritten). Sheets are read by `ui/sheet_loader.py`: `PoolExecutor`
  (2 threads, one short-lived `ApiClient` per read, results via an app-lifetime bridge — never a
  QThread per request: destroying a running QThread aborts the process); the newest request per
  workbook wins; mark "reading" BEFORE requesting (an inline result can arrive first). 404 =
  missing, other errors = unreadable, no response = offline (a stopped service must never mark
  files missing). `merge_sheets` keeps included sheets that vanished as `missing` rows and only
  auto-ticks a fresh workbook. Tests use `InlineExecutor` / `ManualExecutor`.
- **Output card** (`ui/windows/output_preview.py`): `plan_outputs()` mirrors the service's
  naming (the `_{workbook}` suffix, `_email.xlsx`, `_<sheet>.pdf` or one combined `.pdf`) for the
  workbook chosen on the card — change both together.
- **Reordering lists, `ui/kit/reorder.py::Reorder`** (0.15: workbooks, schedules, job cards):
  the host gives `rows()` and handles `moved(from, to)`; `attach(row, inset=…)` puts the grip
  in the row's left margin (rows keep a 16 px left margin for it), `keys()` adds Alt+↑/↓.
  `moved` is emitted on the next loop turn, so a host may rebuild the rows (and their
  shortcuts) safely; while `dragging`, don't rebuild (the dashboard defers its refresh). Show
  shortcut keys in menus as text after a tab (`"Move up	Alt+↑"`), never `setShortcut` — the
  same key on every card's menu is ambiguous and Qt then runs none of them. The dashboard order
  is saved by `POST /jobs/reorder` (all names once, else 409 → reload).
- **Schedules:** `schedule_compile.find_conflicts()` is the one clash rule (same rule twice,
  daily vs any dated rule at that time, same weekday/day-of-month, identical crons); the card
  shows it and Save refuses. Weekly-vs-monthly dates that only sometimes meet are allowed — the
  service's `SchedulerService._fire` starts a job at most once per minute.
- **Send test email:** `POST /email/send-test` → `core.email.sender.send_template_test` (sample
  context like the preview, `[TEST]` subject, no attachments). The UI sends on a parentless
  QThread kept in a module set (closing the editor must not destroy a running thread).
- **Placeholders** come from `core/email/render.py::PLACEHOLDERS` and
  `core/output_names.py::OUTPUT_NAME_TOKENS`; the picker (`ui/placeholder_picker.py`), the Help
  tables and the tooltips all read them — add a placeholder there, nowhere else.
- **Help** is `ui/help/user_guide.md` (bundled via `ui.spec` datas). Headings carry ids
  (`## Schedules {#schedule}`) used by F1 and `#links`; `<!-- placeholders -->`,
  `<!-- recipes -->`, `<!-- output-tokens -->` are filled at load. `tests/ui/test_help.py`
  guards every anchor and a list of facts the old guide taught — keep both when editing it.


## Attachment and PI activation invariants (0.11.1 beta)

- Email uses only the worker's explicit `attachment_paths`, never local `output_xlsx_paths`.
  The local `.xlsx` is retained; the `_email.xlsx` contains exactly Excel-ticked sheets.
  Removal is verified before delivery. PDF exports run before sheet pruning/hiding so
  formula dependencies and print layout are intact. Combined PDFs are per workbook.
- `require_pi_datalink` is optional and separate from ordinary error-cell strictness.
  Failure to activate PI can never be considered successful when this setting is enabled,
  including workbooks containing cached or manually pasted values.
- VSTO diagnostics run under the existing worker token, use process-local environment
  settings, suppress dialogs, and capture only current PI-related, redacted evidence.
  A real service-account identity alone is not proof that VSTO activation works.
- Keep the original input path across SaveAs operations; every save must preserve it.
  Historical run records have `attachment_paths=None`; a new empty list means explicitly
  no attachments. Never fall back from an empty delivery manifest to local Excel files.

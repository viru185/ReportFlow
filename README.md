# ReportFlow

Windows desktop automation for Excel-based reporting. One codebase, one installer, three
executables with isolated runtime roles:

- **UI** (`reportflow-ui`, PySide6) — configure/manage jobs, discover sheets, view status &
  logs, trigger run/test, send developer logs.
- **Service** (`reportflow-service`, FastAPI + APScheduler, hosted by NSSM) — localhost API +
  scheduler; launches one worker per job run; tracks history.
- **Excel Worker** (`reportflow-worker`, xlwings) — short-lived, disposable process that does
  the Excel automation for exactly one run, then exits.

The workbook template owns all print layout / PDF appearance. The app only orchestrates:
refresh data → freeze formulas to values → export one PDF per selected sheet → save output
Excel → log → optionally email.

## Development

```powershell
uv sync --all-extras          # create venv + install everything
uv run pytest -m "not excel"  # unit tests (no Excel required)
uv run ruff check .
uv run mypy
```

Run a worker against a sample workbook (requires local Excel):

```powershell
uv run python scripts/dev_run_worker.py --template scripts/sample/template.xlsx
```

See `C:\ProgramData\ReportFlow\` for config, logs, state, and per-run artifacts at runtime.

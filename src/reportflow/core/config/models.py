"""Pydantic v2 models for the ReportFlow static configuration.

Design rules encoded here:

* Any non-mandatory setting is Optional / has a default so it can be omitted from the TOML.
* Recipients: ``to`` is required (non-empty); ``cc`` and ``bcc`` are optional.
* Runtime state is NEVER stored in this config (see ``core.state``).
* This module imports only pydantic + stdlib so it stays importable from every process.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

CONFIG_VERSION = 1


class _Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class Recipients(_Base):
    """Email recipient set. ``to`` is required; ``cc``/``bcc`` are optional."""

    to: list[EmailStr] = Field(min_length=1)
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)

    def all_addresses(self) -> list[str]:
        """Every envelope recipient (To + CC + BCC), de-duplicated, order preserved."""
        seen: dict[str, None] = {}
        for addr in [*self.to, *self.cc, *self.bcc]:
            seen.setdefault(str(addr), None)
        return list(seen)


class AppSettings(_Base):
    api_host: str = "127.0.0.1"  # local-only by default; do not bind 0.0.0.0
    api_port: int = Field(default=8787, ge=1, le=65535)
    max_global_concurrency: int = Field(default=4, ge=1)
    default_timeout_seconds: int = Field(default=900, gt=0)
    log_retention_days: int = Field(default=30, ge=1)
    # Verbose (DEBUG-level) logging for service, workers, and UI.
    debug_logging: bool = False


class SmtpConfig(_Base):
    """SMTP transport. The password is NOT stored here — it lives in the secret store."""

    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    use_starttls: bool = True
    use_ssl: bool = False
    from_address: str = ""
    username: str | None = None


class UiSettings(_Base):
    api_base_url: str = "http://127.0.0.1:8787"
    # Check GitHub for a newer release when the UI starts (skipped silently when offline).
    # Off by default (owner's call, 0.11): updates are looked for on request (Help menu).
    check_updates_on_startup: bool = False


class EmailSettings(_Base):
    # Relative to the templates dir, or an absolute path.
    default_template_path: str = "email/default.html"


class TestSettings(_Base):
    """Global test-mode fallbacks and developer-bundle recipients."""

    recipients: list[EmailStr] = Field(default_factory=list)
    developer_bundle_recipients: list[EmailStr] = Field(default_factory=list)


UnselectedSheets = Literal["remove", "hide", "keep"]


class SheetOptions(_Base):
    """One INCLUDED sheet: refreshed, checked, frozen — and optionally PDF'd / hidden."""

    name: str
    pdf: bool = True
    # Hidden in the OUTPUT workbook (normal hidden — recipients can unhide it). The sheet is
    # still refreshed and frozen, and can still get a PDF: export runs before hiding.
    hidden: bool = False


class WorkbookConfig(_Base):
    """One input workbook of a job and what its output copy keeps."""

    input_excel_path: Path
    sheets: list[SheetOptions] = Field(min_length=1)
    # The sheets NOT included: "remove" deletes them (smaller file, but can break defined
    # names/charts that referenced them -> Office may refuse to open it); "hide" makes them
    # very-hidden (references intact, always openable); "keep" leaves them visible.
    unselected_sheets: UnselectedSheets = "remove"

    @property
    def sheet_names(self) -> list[str]:
        return [s.name for s in self.sheets]

    @model_validator(mode="after")
    def _sheets_make_sense(self) -> WorkbookConfig:
        label = Path(self.input_excel_path).name
        names = [s.name.casefold() for s in self.sheets]
        if len(set(names)) != len(names):
            raise ValueError(f"{label}: a sheet is listed twice")
        # Excel cannot save a workbook with no visible sheet — and a report nobody can see
        # is pointless. Not-included sheets may be removed, so only included ones count.
        if all(s.hidden for s in self.sheets):
            raise ValueError(
                f"{label}: at least one included sheet must stay visible (untick Hidden on one)"
            )
        return self


def migrate_legacy_job(data: dict) -> dict:
    """Pre-0.11 single-workbook job keys -> one ``workbooks`` entry (returns a new dict).

    Legacy: ``input_excel_path`` + ``sheet_names`` + job-wide ``generate_pdf`` +
    ``keep_only_selected_sheets``/``unselected_sheets_mode``. Used by the JobConfig
    validator (config files, imports) and by the UI when loading an old-shaped job.
    """
    if "workbooks" in data or "input_excel_path" not in data:
        return data
    data = dict(data)
    pdf = bool(data.pop("generate_pdf", True))
    keep_only = bool(data.pop("keep_only_selected_sheets", True))
    mode = data.pop("unselected_sheets_mode", "remove")
    data["workbooks"] = [
        {
            "input_excel_path": data.pop("input_excel_path"),
            "sheets": [{"name": n, "pdf": pdf} for n in data.pop("sheet_names", None) or []],
            "unselected_sheets": mode if keep_only else "keep",
        }
    ]
    return data


class JobConfig(_Base):
    name: str
    enabled: bool = True

    # One or more input workbooks; a run builds all of them and sends ONE email.
    workbooks: list[WorkbookConfig] = Field(min_length=1)
    # With several workbooks: "fail_run" = any failure fails the run and nothing is sent;
    # "send_partial" = email what succeeded, with a warning naming the failed workbook(s).
    on_workbook_failure: Literal["fail_run", "send_partial"] = "fail_run"

    email_template_path: Path | None = None

    # Output location: a folder (empty -> next to each input file) plus an optional filename
    # stem (empty -> the launcher's default). Concrete .xlsx/.pdf paths are derived at launch
    # time; PDFs get an automatic per-sheet suffix.
    output_dir: Path | None = None
    output_name: str | None = None

    freeze_values: bool = True

    # Zero or more 5-field cron expressions; empty = manual-only. Multiple entries support
    # e.g. several run-times per day (one APScheduler trigger is registered per entry).
    schedule_crons: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = Field(default=None, gt=0)
    concurrency_group: str | None = None
    # Extra settle time after calculation completes, for add-ins (e.g. PI DataLink) that
    # fill cells asynchronously. Default 10s matches the proven field recipe.
    post_refresh_wait_seconds: int = Field(default=10, ge=0, le=3600)
    # Fail the run when a selected sheet's used range is entirely empty after refresh —
    # an empty report must never masquerade as success.
    fail_if_sheet_empty: bool = True
    # STRICT (opt-in): fail the run when a selected sheet contains Excel error cells
    # (#REF!, #NAME?, …). Off by default — error cells are reported as a warning and the
    # report is delivered anyway; use "Blank out values" below to strip specific error
    # strings from the output.
    fail_if_sheet_has_errors: bool = False
    # Cell values blanked out of the OUTPUT after saving (e.g. PI DataLink error strings
    # like "Tag not found", "No Data", "#REF!").
    blank_out_values: list[str] = Field(default_factory=list)

    subject: str | None = None
    prod: Recipients
    test: Recipients
    # Job lifecycle: a new job starts in "testing" — EVERY run (manual or scheduled) emails
    # only the Test recipients, so the report is verified internally first. Promoting to
    # "live" switches runs to the Production recipients. Replaces the old
    # send_report_email opt-in checkbox (accepted on input for migration, never written).
    stage: Literal["testing", "live"] = "testing"

    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = migrate_legacy_job(data)  # pre-0.11 single workbook -> workbooks[0]
        # Pre-0.8 configs have send_report_email instead of stage: True meant "emails
        # production on real runs", which maps to live; False/absent maps to testing.
        if "send_report_email" in data:
            data = dict(data)
            legacy = data.pop("send_report_email")
            data.setdefault("stage", "live" if legacy else "testing")
        return data

    @property
    def sheet_names(self) -> list[str]:
        """Every included sheet across all workbooks (email context, summaries)."""
        return [name for wb in self.workbooks for name in wb.sheet_names]

    @model_validator(mode="after")
    def _distinct_workbooks(self) -> JobConfig:
        seen: set[str] = set()
        for wb in self.workbooks:
            key = str(wb.input_excel_path).casefold()
            if key in seen:
                raise ValueError(f"the same workbook is added twice: {wb.input_excel_path}")
            seen.add(key)
        return self

    @field_validator("name")
    @classmethod
    def _name_is_safe(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("job name must not be empty")
        if any(c in v for c in '\\/:*?"<>|'):
            raise ValueError(f"job name contains invalid characters: {v!r}")
        return v

    @field_validator("schedule_crons")
    @classmethod
    def _cron_shapes(cls, v: list[str]) -> list[str]:
        # Light structural check only; the service does full validation via APScheduler.
        cleaned: list[str] = []
        for expr in v:
            expr = expr.strip()
            if not expr:
                continue
            if len(expr.split()) != 5:
                raise ValueError(f"cron expression must have 5 fields, got {expr!r}")
            cleaned.append(expr)
        return cleaned


class AppConfig(_Base):
    config_version: int = CONFIG_VERSION
    app: AppSettings = Field(default_factory=AppSettings)
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)
    ui: UiSettings = Field(default_factory=UiSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    test: TestSettings = Field(default_factory=TestSettings)
    # TOML uses `[[job]]` array-of-tables; expose it as `jobs` in Python.
    jobs: list[JobConfig] = Field(default_factory=list, alias="job")

    @model_validator(mode="after")
    def _unique_job_names(self) -> AppConfig:
        seen: set[str] = set()
        for job in self.jobs:
            key = job.name.casefold()
            if key in seen:
                raise ValueError(f"duplicate job name: {job.name!r}")
            seen.add(key)
        return self

    def job(self, name: str) -> JobConfig | None:
        for j in self.jobs:
            if j.name.casefold() == name.casefold():
                return j
        return None

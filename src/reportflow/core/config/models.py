"""Pydantic v2 models for the ReportFlow static configuration.

Design rules encoded here:

* Any non-mandatory setting is Optional / has a default so it can be omitted from the TOML.
* Recipients: ``to`` is required (non-empty); ``cc`` and ``bcc`` are optional.
* Runtime state is NEVER stored in this config (see ``core.state``).
* This module imports only pydantic + stdlib so it stays importable from every process.
"""

from __future__ import annotations

from pathlib import Path

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
    check_updates_on_startup: bool = True


class EmailSettings(_Base):
    # Relative to the templates dir, or an absolute path.
    default_template_path: str = "email/default.html"


class TestSettings(_Base):
    """Global test-mode fallbacks and developer-bundle recipients."""

    recipients: list[EmailStr] = Field(default_factory=list)
    developer_bundle_recipients: list[EmailStr] = Field(default_factory=list)


class JobConfig(_Base):
    name: str
    enabled: bool = True

    input_excel_path: Path
    email_template_path: Path | None = None

    # Output location: a folder (empty -> next to the input file) plus an optional filename
    # stem (empty -> "{job}_{date}"). Concrete .xlsx/.pdf paths are derived at launch time;
    # PDFs get an automatic per-sheet suffix.
    output_dir: Path | None = None
    output_name: str | None = None

    sheet_names: list[str] = Field(min_length=1)

    freeze_values: bool = True
    generate_pdf: bool = True

    # Zero or more 5-field cron expressions; empty = manual-only. Multiple entries support
    # e.g. several run-times per day (one APScheduler trigger is registered per entry).
    schedule_crons: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = Field(default=None, gt=0)
    concurrency_group: str | None = None
    # Extra settle time after calculation completes, for add-ins (e.g. PI DataLink) that
    # fill cells asynchronously. 0 = none.
    post_refresh_wait_seconds: int = Field(default=10, ge=0, le=3600)
    fail_if_sheet_empty: bool = True

    subject: str | None = None
    prod: Recipients
    test: Recipients
    # Real (non-test) runs email prod recipients only when this is explicitly enabled.
    # Test runs always email the test recipients regardless of this flag.
    send_report_email: bool = False

    notes: str = ""

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

"""Default seed configuration and the default HTML email template.

Used by the installer / first-run bootstrap to seed ``%ProgramData%\\ReportFlow`` when no
config exists yet. Never overwrites an existing file.
"""

from __future__ import annotations

from reportflow.core.config.models import (
    AppConfig,
    AppSettings,
    EmailSettings,
    SmtpConfig,
    TestSettings,
    UiSettings,
)

DEFAULT_EMAIL_TEMPLATE = """\
<!doctype html>
<html>
  <body style="font-family: Segoe UI, Arial, sans-serif; color: #1a1a1a;">
    <h2 style="margin-bottom: 4px;">{{ job_name }}</h2>
    <p style="color: #666; margin-top: 0;">{{ subject }}</p>
    <table cellpadding="6" style="border-collapse: collapse; font-size: 14px;">
      <tr><td><b>Status</b></td><td>{{ status }}</td></tr>
      <tr><td><b>Run ID</b></td><td>{{ run_id }}</td></tr>
      <tr><td><b>Started</b></td><td>{{ started_at }}</td></tr>
      <tr><td><b>Finished</b></td><td>{{ finished_at }}</td></tr>
      <tr><td><b>Duration</b></td><td>{{ duration_seconds }} s</td></tr>
      <tr><td><b>Sheets</b></td><td>{{ sheet_names | join(", ") }}</td></tr>
      <tr><td><b>Host</b></td><td>{{ hostname }}</td></tr>
    </table>
    {% if is_test %}
    <p style="color: #b00; font-weight: bold;">*** TEST RUN — internal recipients only ***</p>
    {% endif %}
    <p style="color: #999; font-size: 12px;">Generated automatically by ReportFlow.</p>
  </body>
</html>
"""


# Where 'Send developer logs' bundles go unless the operator changes it in Settings.
DEFAULT_DEVELOPER_EMAIL = "viren.hirpara@cerebulb.com"


def default_config() -> AppConfig:
    """A minimal, valid config with no jobs. SMTP/test fields are left blank for the operator."""
    return AppConfig(
        app=AppSettings(),
        smtp=SmtpConfig(),
        ui=UiSettings(),
        email=EmailSettings(),
        test=TestSettings(developer_bundle_recipients=[DEFAULT_DEVELOPER_EMAIL]),
        jobs=[],
    )

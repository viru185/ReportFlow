"""Pure-logic tests for jobs/settings import-export (no Qt)."""

from __future__ import annotations

import pytest

from reportflow.ui.transfer import (
    TransferError,
    copy_name,
    export_jobs,
    export_settings,
    parse_jobs_file,
    parse_settings_file,
)


def _job_dict(name="daily"):
    return {
        "name": name,
        "input_excel_path": "C:/t.xlsx",
        "output_dir": "C:/out",
        "sheet_names": ["Summary"],
        "schedule_crons": ["0 6 * * *"],
        "prod": {"to": ["boss@corp.example.com"]},
        "test": {"to": ["dev@corp.example.com"]},
    }


def test_jobs_round_trip():
    payload = export_jobs([_job_dict("a"), _job_dict("b")])
    jobs = parse_jobs_file(payload)
    assert [j.name for j in jobs] == ["a", "b"]
    assert jobs[0].sheet_names == ["Summary"]


def test_parse_rejects_wrong_kind():
    with pytest.raises(TransferError, match="not a ReportFlow jobs export"):
        parse_jobs_file(export_settings({"app": {}}))
    with pytest.raises(TransferError):
        parse_jobs_file({"jobs": []})
    with pytest.raises(TransferError, match="no jobs"):
        parse_jobs_file({"reportflow_export": "jobs", "jobs": []})


def test_parse_reports_invalid_entry_index():
    bad = export_jobs([_job_dict(), {"name": "broken"}])
    with pytest.raises(TransferError, match="job #2"):
        parse_jobs_file(bad)


def test_copy_name_skips_taken_names():
    existing = {"daily", "daily-2", "DAILY-3"}
    assert copy_name("daily", existing) == "daily-4"
    assert copy_name("weekly", existing) == "weekly-2"


def test_settings_round_trip():
    config = {
        "app": {"api_port": 8787},
        "smtp": {"host": "smtp.x.com"},
        "ui": {"check_updates_on_startup": True},
        "email": {"default_template_path": "email/default.html"},
        "test": {"recipients": []},
        "job": [{"name": "ignored"}],  # jobs must NOT travel with settings
        "config_version": 1,
    }
    payload = export_settings(config)
    sections = parse_settings_file(payload)
    assert set(sections) == {"app", "smtp", "ui", "email", "test"}
    assert "job" not in sections and "config_version" not in sections


def test_settings_parse_rejects_unknown_sections():
    with pytest.raises(TransferError, match="unknown settings section"):
        parse_settings_file({"reportflow_export": "settings", "settings": {"hack": {}}})
    with pytest.raises(TransferError):
        parse_settings_file({"reportflow_export": "jobs", "jobs": []})

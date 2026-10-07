from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from reportflow.core.config import (
    AppConfig,
    JobConfig,
    Recipients,
    load_config,
    save_config,
)
from reportflow.core.config.defaults import default_config
from reportflow.core.config.loader import ConfigError


def _sample_job(**overrides) -> JobConfig:
    base = dict(
        name="daily_sales",
        input_excel_path="C:/Templates/daily_sales.xlsx",
        output_dir="C:/Reports/daily_sales",
        output_name="{job}_{date}",
        sheet_names=["Summary", "Detail"],
        schedule_crons=["0 6 * * 1-5", "0 18 * * 1-5"],
        prod=Recipients(to=["managers@corp.example.com"], cc=["ops@corp.example.com"]),
        test=Recipients(to=["dev-team@corp.example.com"]),
    )
    base.update(overrides)
    return JobConfig(**{k: v for k, v in base.items() if v is not None})


def test_config_round_trips_through_toml():
    cfg = default_config()
    cfg.jobs.append(_sample_job())

    save_config(cfg)
    loaded = load_config()

    assert loaded == cfg
    assert loaded.jobs[0].prod.to == ["managers@corp.example.com"]
    assert loaded.jobs[0].prod.cc == ["ops@corp.example.com"]
    assert loaded.jobs[0].prod.bcc == []


def test_optional_fields_are_omitted_from_file(tmp_path):
    cfg = default_config()
    cfg.jobs.append(_sample_job())
    path = save_config(cfg)

    text = path.read_text(encoding="utf-8")
    # bcc was never set -> should not appear; cc was set -> should appear.
    assert "bcc" not in text
    assert "cc" in text


def test_load_missing_file_raises():
    with pytest.raises(ConfigError):
        load_config()


def test_duplicate_job_names_rejected():
    with pytest.raises(ValidationError):
        AppConfig(job=[_sample_job(), _sample_job()])


def test_empty_to_rejected():
    with pytest.raises(ValidationError):
        Recipients(to=[])


def test_output_dir_and_name_are_optional():
    job = _sample_job(output_dir=None, output_name=None)
    assert job.output_dir is None
    assert job.output_name is None


def test_bad_cron_rejected():
    with pytest.raises(ValidationError):
        _sample_job(schedule_crons=["not a cron"])


def test_blank_cron_entries_dropped():
    job = _sample_job(schedule_crons=["0 6 * * *", "  ", ""])
    assert job.schedule_crons == ["0 6 * * *"]


def test_post_refresh_wait_defaults_to_ten_and_round_trips():
    assert _sample_job().post_refresh_wait_seconds == 10  # proven field recipe default

    cfg = default_config()
    cfg.jobs.append(_sample_job(post_refresh_wait_seconds=90))
    save_config(cfg)
    assert load_config().jobs[0].post_refresh_wait_seconds == 90

    with pytest.raises(ValidationError):
        _sample_job(post_refresh_wait_seconds=-5)


def test_new_output_safety_options_default_and_round_trip():
    job = _sample_job()
    assert job.fail_if_sheet_empty is True
    assert job.workbooks[0].unselected_sheets == "remove"
    assert job.blank_out_values == []

    cfg = default_config()
    cfg.jobs.append(
        _sample_job(
            fail_if_sheet_empty=False,
            keep_only_selected_sheets=False,  # legacy key -> unselected "keep"
            blank_out_values=["Tag not found", "#REF!"],
        )
    )
    save_config(cfg)
    loaded = load_config().jobs[0]
    assert loaded.fail_if_sheet_empty is False
    assert loaded.workbooks[0].unselected_sheets == "keep"
    assert loaded.blank_out_values == ["Tag not found", "#REF!"]


def test_error_and_unselected_mode_defaults_and_round_trip():
    job = _sample_job()
    assert job.fail_if_sheet_has_errors is False  # deliver by default; strict is opt-in

    cfg = default_config()
    cfg.jobs.append(_sample_job(fail_if_sheet_has_errors=True, unselected_sheets_mode="hide"))
    save_config(cfg)
    loaded = load_config().jobs[0]
    assert loaded.fail_if_sheet_has_errors is True
    assert loaded.workbooks[0].unselected_sheets == "hide"


def test_legacy_single_workbook_job_migrates():
    """A pre-0.11 job (one input file, job-wide PDF switch) loads as one workbook with the
    same behaviour, and is written back in the new shape."""
    legacy = {
        "name": "old",
        "input_excel_path": "C:/t.xlsx",
        "sheet_names": ["Summary", "Detail"],
        "generate_pdf": False,
        "keep_only_selected_sheets": True,
        "unselected_sheets_mode": "hide",
        "send_report_email": True,
        "prod": {"to": ["boss@corp.example.com"]},
        "test": {"to": ["dev@corp.example.com"]},
    }
    job = JobConfig.model_validate(legacy)
    assert "input_excel_path" in legacy  # the caller's dict is not mutated
    [wb] = job.workbooks
    assert wb.input_excel_path == Path("C:/t.xlsx")
    assert [(s.name, s.pdf, s.hidden) for s in wb.sheets] == [
        ("Summary", False, False),
        ("Detail", False, False),
    ]
    assert wb.unselected_sheets == "hide"
    assert job.stage == "live"  # the 0.8 migration still applies alongside
    assert job.sheet_names == ["Summary", "Detail"]

    dumped = job.model_dump(mode="json")
    assert "input_excel_path" not in dumped and "sheet_names" not in dumped
    assert JobConfig.model_validate(dumped) == job


def test_per_sheet_options_and_visibility_rule():
    workbook = {
        "input_excel_path": "C:/t.xlsx",
        "sheets": [{"name": "Summary", "pdf": True}, {"name": "Raw", "pdf": False, "hidden": True}],
    }
    job = _sample_job(input_excel_path=None, sheet_names=None, workbooks=[workbook])
    assert [(s.pdf, s.hidden) for s in job.workbooks[0].sheets] == [(True, False), (False, True)]

    all_hidden = {**workbook, "sheets": [{"name": "Raw", "hidden": True}]}
    with pytest.raises(ValidationError, match="must stay visible"):
        _sample_job(input_excel_path=None, sheet_names=None, workbooks=[all_hidden])


def test_same_workbook_twice_is_rejected():
    workbook = {"input_excel_path": "C:/t.xlsx", "sheets": [{"name": "Summary"}]}
    with pytest.raises(ValidationError, match="added twice"):
        _sample_job(input_excel_path=None, sheet_names=None, workbooks=[workbook, workbook])


def test_stage_defaults_to_testing_and_round_trips():
    assert _sample_job().stage == "testing"  # new jobs verify internally first

    cfg = default_config()
    cfg.jobs.append(_sample_job(stage="live"))
    save_config(cfg)
    assert load_config().jobs[0].stage == "live"

    with pytest.raises(ValidationError):
        _sample_job(stage="production")  # only testing|live


def test_legacy_send_report_email_migrates_to_stage():
    # Pre-0.8 configs stored send_report_email; True meant "emails production" -> live.
    assert _sample_job(send_report_email=True).stage == "live"
    assert _sample_job(send_report_email=False).stage == "testing"
    # An explicit stage wins over the legacy flag, and the flag is never persisted.
    job = _sample_job(send_report_email=True, stage="testing")
    assert job.stage == "testing"
    assert "send_report_email" not in job.model_dump()


def test_debug_logging_setting_round_trips():
    cfg = default_config()
    assert cfg.app.debug_logging is False
    cfg.app.debug_logging = True
    save_config(cfg)
    assert load_config().app.debug_logging is True


def test_job_lookup_is_case_insensitive():
    cfg = default_config()
    cfg.jobs.append(_sample_job())
    assert cfg.job("DAILY_SALES") is not None
    assert cfg.job("nope") is None


def test_all_addresses_dedupes():
    r = Recipients(
        to=["a@x.com", "b@x.com"],
        cc=["a@x.com"],
        bcc=["c@x.com"],
    )
    assert r.all_addresses() == ["a@x.com", "b@x.com", "c@x.com"]


def test_update_check_on_startup_is_off_by_default():
    from reportflow.core.config.models import UiSettings

    assert UiSettings().check_updates_on_startup is False

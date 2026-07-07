from __future__ import annotations

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
    return JobConfig(**base)


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


def test_post_refresh_wait_defaults_to_zero_and_round_trips():
    assert _sample_job().post_refresh_wait_seconds == 0

    cfg = default_config()
    cfg.jobs.append(_sample_job(post_refresh_wait_seconds=90))
    save_config(cfg)
    assert load_config().jobs[0].post_refresh_wait_seconds == 90

    with pytest.raises(ValidationError):
        _sample_job(post_refresh_wait_seconds=-5)


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

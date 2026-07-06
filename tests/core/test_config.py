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
        workbook_template_path="C:/Templates/daily_sales.xlsx",
        output_xlsx_path="C:/Reports/daily_sales/out.xlsx",
        output_pdf_path="C:/Reports/daily_sales/{sheet}.pdf",
        sheet_names=["Summary", "Detail"],
        schedule_cron="0 6 * * 1-5",
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


def test_pdf_requires_sheet_token_for_multisheet():
    with pytest.raises(ValidationError):
        _sample_job(output_pdf_path="C:/Reports/daily.pdf")  # no {sheet}, two sheets


def test_single_sheet_pdf_without_token_ok():
    job = _sample_job(sheet_names=["Summary"], output_pdf_path="C:/Reports/daily.pdf")
    assert job.generate_pdf is True


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

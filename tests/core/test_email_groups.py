"""Email groups: config rules, de-duplicated expansion, and what actually gets emailed."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reportflow.core.config.models import (
    AppConfig,
    EmailGroup,
    EmailSettings,
    GroupRef,
    JobConfig,
    Recipients,
)
from reportflow.core.email.recipients import resolve
from reportflow.core.email.sender import resolve_recipients

LEADS = EmailGroup(name="Plant leads", members=["a@corp.example.com", "B@corp.example.com"])
ENERGY = EmailGroup(name="Energy team", members=["b@corp.example.com", "c@corp.example.com"])


def test_overlapping_groups_email_everyone_once_to_before_cc_before_bcc():
    recipients = Recipients(
        to=["boss@corp.example.com"],
        to_groups=["plant leads"],  # names match case-insensitively
        cc=["a@corp.example.com"],  # already in To via the group
        cc_groups=["Energy team"],  # b is in both groups
        bcc=["boss@corp.example.com", "audit@corp.example.com"],
    )
    resolved = resolve(recipients, [LEADS, ENERGY])
    assert resolved.to == ["boss@corp.example.com", "a@corp.example.com", "B@corp.example.com"]
    assert resolved.cc == ["c@corp.example.com"]
    assert resolved.bcc == ["audit@corp.example.com"]
    assert len(resolved.all_addresses()) == 5


def test_to_needs_an_address_or_a_group():
    assert Recipients(to=[{"group": "Plant leads"}]).groups("to") == ["Plant leads"]
    with pytest.raises(ValidationError, match="at least one address or email group"):
        Recipients(cc=["a@corp.example.com"])


def test_people_are_sent_in_the_order_the_job_lists_them():
    """0.15: order matters to corporate readers — a group goes out at its place in the
    list, its members in the group's own order."""
    recipients = Recipients(
        to=["boss@corp.example.com", {"group": "Plant leads"}, "mary@corp.example.com"],
        cc=[{"group": "Energy team"}, "audit@corp.example.com"],
    )
    resolved = resolve(recipients, [LEADS, ENERGY])
    assert resolved.to == [
        "boss@corp.example.com",
        "a@corp.example.com",
        "B@corp.example.com",
        "mary@corp.example.com",
    ]
    assert resolved.cc == ["c@corp.example.com", "audit@corp.example.com"]  # b@ is in To


def test_an_old_job_keeps_its_email_order():
    """Before 0.15 groups were stored apart and sent after the addresses: they load there,
    and are saved back in the new shape."""
    old = Recipients.model_validate(
        {"to": ["boss@corp.example.com"], "to_groups": ["Plant leads", "plant LEADS"]}
    )
    assert old.to == ["boss@corp.example.com", GroupRef(group="Plant leads")]
    dumped = old.model_dump(mode="json")
    assert dumped["to"] == ["boss@corp.example.com", {"group": "Plant leads"}]
    assert "to_groups" not in dumped
    assert Recipients.model_validate(dumped) == old


def test_a_bad_address_reports_only_the_address_problem():
    with pytest.raises(ValidationError) as info:
        Recipients(to=["boss@corp.example.com", "not-an-address"])
    errors = info.value.errors()
    assert len(errors) == 1 and "email" in errors[0]["msg"]


def test_group_names_must_be_usable_and_unique():
    with pytest.raises(ValidationError, match="can't contain"):
        EmailGroup(name="Leads; QA", members=["a@corp.example.com"])
    with pytest.raises(ValidationError):
        EmailGroup(name="Empty", members=[])
    with pytest.raises(ValidationError, match="two email groups"):
        EmailSettings(groups=[LEADS, EmailGroup(name="PLANT LEADS", members=["x@y.com"])])


def _job(**recipients) -> JobConfig:
    return JobConfig(
        name="daily",
        input_excel_path="C:/t.xlsx",
        sheet_names=["Summary"],
        prod=Recipients(**recipients),
        test=Recipients(to=["dev@corp.example.com"]),
    )


def test_a_job_cant_use_a_group_that_doesnt_exist():
    job = _job(to_groups=["Plant leads"])
    with pytest.raises(ValidationError, match="uses email group 'Plant leads', which doesn't"):
        AppConfig(jobs=[job])
    config = AppConfig(jobs=[job], email=EmailSettings(groups=[LEADS]))
    assert config.jobs_using_group("PLANT LEADS") == ["daily"]


def test_send_expands_groups_for_production_and_test():
    job = _job(to_groups=["Plant leads"], cc=["a@corp.example.com"])
    job = job.model_copy(update={"test": Recipients(to_groups=["Energy team"])})
    config = AppConfig(jobs=[job], email=EmailSettings(groups=[LEADS, ENERGY]))
    prod = resolve_recipients(job, config, is_test=False)
    assert prod.to == ["a@corp.example.com", "B@corp.example.com"] and prod.cc == []
    test = resolve_recipients(job, config, is_test=True)
    assert test.to == ["b@corp.example.com", "c@corp.example.com"]

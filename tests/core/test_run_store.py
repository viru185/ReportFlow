from __future__ import annotations

from reportflow.core.ipc.contract import RunStatus
from reportflow.core.state import RunRecord, RunStore, RunTrigger


def _rec(run_id="r1", job="daily", status=RunStatus.SUCCESS, started="2026-07-07T06:00:00"):
    return RunRecord(
        run_id=run_id,
        job_name=job,
        trigger=RunTrigger.MANUAL,
        status=status,
        started_at=started,
    )


def test_upsert_and_get(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    store.upsert(_rec())
    got = store.get("r1")
    assert got is not None
    assert got.job_name == "daily"
    assert got.status is RunStatus.SUCCESS


def test_upsert_updates_existing(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    store.upsert(_rec(status=RunStatus.SUCCESS))
    rec = _rec(status=RunStatus.FAILED)
    rec.error_summary = "boom"
    rec.finished_at = "2026-07-07T06:01:00"
    store.upsert(rec)
    got = store.get("r1")
    assert got.status is RunStatus.FAILED
    assert got.error_summary == "boom"


def test_list_orders_by_started_desc(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    store.upsert(_rec(run_id="a", started="2026-07-07T06:00:00"))
    store.upsert(_rec(run_id="b", started="2026-07-07T07:00:00"))
    runs = store.list(limit=10)
    assert [r.run_id for r in runs] == ["b", "a"]


def test_latest_and_latest_failure(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    store.upsert(_rec(run_id="f", status=RunStatus.FAILED, started="2026-07-07T06:00:00"))
    store.upsert(_rec(run_id="s", status=RunStatus.SUCCESS, started="2026-07-07T07:00:00"))
    assert store.latest_for_job("daily").run_id == "s"
    # The last failure is preserved for visibility even after a later success.
    assert store.latest_failure_for_job("daily").run_id == "f"


def test_pdf_paths_round_trip(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    rec = _rec()
    rec.pdf_paths = ["C:/out/Summary.pdf", "C:/out/Detail.pdf"]
    store.upsert(rec)
    assert store.get("r1").pdf_paths == ["C:/out/Summary.pdf", "C:/out/Detail.pdf"]

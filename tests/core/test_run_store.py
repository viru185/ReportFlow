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


def test_email_note_round_trip(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    rec = _rec()
    rec.email_note = "sent to 2 production recipient(s)"
    store.upsert(rec)
    assert store.get("r1").email_note == "sent to 2 production recipient(s)"


def test_duration_and_warnings_round_trip(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    rec = _rec()
    rec.duration_seconds = 42.5
    rec.warnings = ["sheet 'Detail': 12 error cell(s) (#REF!) — delivered anyway"]
    store.upsert(rec)
    got = store.get("r1")
    assert got.duration_seconds == 42.5
    assert got.warnings == rec.warnings  # was silently dropped before the warnings column


def test_migration_adds_email_note_to_old_db(tmp_path):
    """A database created before the email_note column existed gains it on open."""
    import sqlite3

    db = tmp_path / "runs.db"
    old_schema = """
    CREATE TABLE runs (
        run_id TEXT PRIMARY KEY, job_name TEXT NOT NULL, trigger TEXT NOT NULL,
        status TEXT NOT NULL, is_test INTEGER NOT NULL DEFAULT 0, started_at TEXT,
        finished_at TEXT, exit_code INTEGER, output_xlsx TEXT,
        pdf_paths TEXT NOT NULL DEFAULT '[]', error_summary TEXT,
        worker_log_path TEXT, email_sent INTEGER NOT NULL DEFAULT 0
    );
    """
    conn = sqlite3.connect(db)
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO runs (run_id, job_name, trigger, status) VALUES ('old', 'j', "
        "'manual', 'success')"
    )
    conn.commit()
    conn.close()

    store = RunStore(db)  # opening migrates
    old = store.get("old")
    assert old is not None and old.email_note is None
    old.email_note = "sent to 1 test recipient(s)"
    store.upsert(old)
    assert store.get("old").email_note == "sent to 1 test recipient(s)"

"""SQLite-backed run history. The Service is the only writer; the UI reads via the API.

Uses WAL mode and a fresh short-lived connection per operation so it is safe to use from
multiple scheduler threads and the API event loop concurrently.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from reportflow.core import paths
from reportflow.core.ipc.contract import RunStatus
from reportflow.core.state.models import RunRecord, RunTrigger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    job_name        TEXT NOT NULL,
    trigger         TEXT NOT NULL,
    status          TEXT NOT NULL,
    is_test         INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT,
    finished_at     TEXT,
    duration_seconds REAL,
    exit_code       INTEGER,
    output_xlsx     TEXT,
    pdf_paths       TEXT NOT NULL DEFAULT '[]',
    error_summary   TEXT,
    warnings        TEXT NOT NULL DEFAULT '[]',
    worker_log_path TEXT,
    email_sent      INTEGER NOT NULL DEFAULT 0,
    email_note      TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_job ON runs(job_name);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
"""

# Columns added after the first release; applied to pre-existing databases on open.
_MIGRATIONS = [
    "ALTER TABLE runs ADD COLUMN email_note TEXT",
    "ALTER TABLE runs ADD COLUMN duration_seconds REAL",
    # warnings existed on the model since 0.6.2 but was never persisted — run history read
    # back empty lists after a service restart. Backfilled as '[]'.
    "ALTER TABLE runs ADD COLUMN warnings TEXT NOT NULL DEFAULT '[]'",
]


class RunStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (paths.state_dir() / "runs.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            for migration in _MIGRATIONS:
                try:
                    conn.execute(migration)
                except sqlite3.OperationalError:
                    pass  # column already exists (fresh schema or migrated earlier)

    def upsert(self, record: RunRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, job_name, trigger, status, is_test, started_at,
                                  finished_at, duration_seconds, exit_code, output_xlsx,
                                  pdf_paths, error_summary, warnings, worker_log_path,
                                  email_sent, email_note)
                VALUES (:run_id, :job_name, :trigger, :status, :is_test, :started_at,
                        :finished_at, :duration_seconds, :exit_code, :output_xlsx,
                        :pdf_paths, :error_summary, :warnings, :worker_log_path,
                        :email_sent, :email_note)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    finished_at=excluded.finished_at,
                    duration_seconds=excluded.duration_seconds,
                    exit_code=excluded.exit_code,
                    output_xlsx=excluded.output_xlsx,
                    pdf_paths=excluded.pdf_paths,
                    error_summary=excluded.error_summary,
                    warnings=excluded.warnings,
                    worker_log_path=excluded.worker_log_path,
                    email_sent=excluded.email_sent,
                    email_note=excluded.email_note
                """,
                self._to_row(record),
            )

    @staticmethod
    def _to_row(r: RunRecord) -> dict:
        return {
            "run_id": r.run_id,
            "job_name": r.job_name,
            "trigger": str(r.trigger),
            "status": str(r.status),
            "is_test": int(r.is_test),
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "duration_seconds": r.duration_seconds,
            "exit_code": r.exit_code,
            "output_xlsx": r.output_xlsx,
            "pdf_paths": json.dumps(r.pdf_paths),
            "error_summary": r.error_summary,
            "warnings": json.dumps(r.warnings),
            "worker_log_path": r.worker_log_path,
            "email_sent": int(r.email_sent),
            "email_note": r.email_note,
        }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            job_name=row["job_name"],
            trigger=RunTrigger(row["trigger"]),
            status=RunStatus(row["status"]),
            is_test=bool(row["is_test"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            duration_seconds=row["duration_seconds"],
            exit_code=row["exit_code"],
            output_xlsx=row["output_xlsx"],
            pdf_paths=json.loads(row["pdf_paths"]),
            error_summary=row["error_summary"],
            warnings=json.loads(row["warnings"] or "[]"),
            worker_log_path=row["worker_log_path"],
            email_sent=bool(row["email_sent"]),
            email_note=row["email_note"],
        )

    def get(self, run_id: str) -> RunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(self, job_name: str | None = None, limit: int = 50) -> list[RunRecord]:
        query = "SELECT * FROM runs"
        args: list = []
        if job_name:
            query += " WHERE job_name=?"
            args.append(job_name)
        query += " ORDER BY COALESCE(started_at, '') DESC LIMIT ?"
        args.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [self._from_row(r) for r in rows]

    def latest_for_job(self, job_name: str) -> RunRecord | None:
        runs = self.list(job_name=job_name, limit=1)
        return runs[0] if runs else None

    def delete_before(self, cutoff_iso: str, *, keep_ids: set[str] | None = None) -> int:
        """Delete history rows started before ``cutoff_iso`` (ISO string; lexicographic
        compare matches chronological for our second-precision timestamps). Rows in
        ``keep_ids`` (active runs) survive regardless. Returns the number deleted."""
        keep = sorted(keep_ids or ())
        placeholders = ",".join("?" for _ in keep)
        query = "DELETE FROM runs WHERE COALESCE(started_at, '') < ?"
        if keep:
            query += f" AND run_id NOT IN ({placeholders})"
        with self._connect() as conn:
            cur = conn.execute(query, (cutoff_iso, *keep))
        return cur.rowcount

    def delete_all(self, *, keep_ids: set[str] | None = None) -> int:
        """Delete ALL history rows except ``keep_ids`` (active runs). Returns the count."""
        keep = sorted(keep_ids or ())
        placeholders = ",".join("?" for _ in keep)
        query = "DELETE FROM runs"
        if keep:
            query += f" WHERE run_id NOT IN ({placeholders})"
        with self._connect() as conn:
            cur = conn.execute(query, keep)
        return cur.rowcount

    def latest_failure_for_job(self, job_name: str) -> RunRecord | None:
        """The last failed run is preserved for visibility even after later successes."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM runs
                WHERE job_name=? AND status IN (?, ?, ?)
                ORDER BY COALESCE(started_at, '') DESC LIMIT 1
                """,
                (job_name, RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.CRASHED),
            ).fetchone()
        return self._from_row(row) if row else None

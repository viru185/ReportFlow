from __future__ import annotations

from reportflow.core.ipc import (
    RunStatus,
    WorkerRequest,
    WorkerResult,
    read_request,
    read_result,
    write_request,
    write_result,
)


def _request(run_dir) -> WorkerRequest:
    return WorkerRequest(
        run_id="run-123",
        job_name="daily_sales",
        input_excel_path="C:/Templates/daily_sales.xlsx",
        output_xlsx_path=str(run_dir / "out.xlsx"),
        output_pdf_path=str(run_dir / "{sheet}.pdf"),
        sheet_names=["Summary", "Detail"],
        timeout_seconds=600,
        is_test=True,
        result_path=str(run_dir / "result.json"),
        log_path=str(run_dir / "worker.log"),
    )


def test_request_round_trip(tmp_path):
    req = _request(tmp_path)
    path = write_request(req, tmp_path / "request.json")
    loaded = read_request(path)
    assert loaded == req


def test_result_round_trip(tmp_path):
    result = WorkerResult(
        run_id="run-123",
        status=RunStatus.SUCCESS,
        message="ok",
        output_xlsx=str(tmp_path / "out.xlsx"),
        pdf_paths=[str(tmp_path / "Summary.pdf"), str(tmp_path / "Detail.pdf")],
        started_at="2026-07-06T06:00:00",
        finished_at="2026-07-06T06:00:12",
        duration_seconds=12.0,
        excel_pid=4321,
        excel_pid_reaped=True,
    )
    path = write_result(result, tmp_path / "result.json")
    loaded = read_result(path)
    assert loaded == result
    assert loaded.ok is True


def test_failed_result_not_ok(tmp_path):
    result = WorkerResult(run_id="r", status=RunStatus.FAILED, error_detail="boom")
    path = write_result(result, tmp_path / "result.json")
    assert read_result(path).ok is False

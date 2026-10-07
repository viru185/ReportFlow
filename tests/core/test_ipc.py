from __future__ import annotations

from reportflow.core.ipc import (
    RunStatus,
    SheetTask,
    WorkbookTask,
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
        workbooks=[
            WorkbookTask(
                input_excel_path="C:/Templates/daily_sales.xlsx",
                output_xlsx_path=str(run_dir / "out.xlsx"),
                output_pdf_path=str(run_dir / "{sheet}.pdf"),
                sheets=[SheetTask(name="Summary"), SheetTask(name="Detail", pdf=False)],
            )
        ],
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
    assert loaded.workbooks[0].sheet_names == ["Summary", "Detail"]


def test_error_and_mode_defaults_and_round_trip(tmp_path):
    req0 = _request(tmp_path)
    assert req0.fail_if_sheet_has_errors is False  # deliver by default
    assert req0.continue_on_workbook_failure is False  # all-or-nothing by default
    assert req0.workbooks[0].unselected_sheets == "remove"
    hidden = req0.workbooks[0].model_copy(
        update={
            "unselected_sheets": "hide",
            "sheets": [SheetTask(name="Summary"), SheetTask(name="Raw", hidden=True)],
        }
    )
    req = req0.model_copy(update={"fail_if_sheet_has_errors": True, "workbooks": [hidden]})
    loaded = read_request(write_request(req, tmp_path / "request.json"))
    assert loaded.fail_if_sheet_has_errors is True
    assert loaded.workbooks[0].unselected_sheets == "hide"
    assert loaded.workbooks[0].sheets[1].hidden is True


def test_worker_result_warnings_round_trip(tmp_path):
    result = WorkerResult(
        run_id="r", status=RunStatus.SUCCESS, warnings=["sheet 'X': 3 error cell(s)"]
    )
    loaded = read_result(write_result(result, tmp_path / "result.json"))
    assert loaded.warnings == ["sheet 'X': 3 error cell(s)"]


def test_result_round_trip(tmp_path):
    result = WorkerResult(
        run_id="run-123",
        status=RunStatus.SUCCESS,
        message="ok",
        output_xlsx_paths=[str(tmp_path / "out.xlsx"), str(tmp_path / "out2.xlsx")],
        pdf_paths=[str(tmp_path / "Summary.pdf"), str(tmp_path / "Detail.pdf")],
        failed_workbooks=["Stock.xlsx"],
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

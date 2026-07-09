"""xlwings/COM automation for a single job run, with guaranteed teardown.

Reliability is the whole point of this module:

* A dedicated, hidden, isolated Excel instance is created per run; its PID is captured
  immediately so we can reap it no matter what goes wrong.
* Teardown runs in ``__exit__`` for every exit path: close books -> ``app.quit()`` ->
  ``app.kill()`` -> psutil verification that the PID is actually gone. Each step is isolated
  so one failing step cannot skip the others. This is what prevents ghost ``EXCEL.EXE``.
* The workbook template owns all print layout — we never touch PageSetup; PDF export goes
  through ``sheet.to_pdf`` which honors the sheet's stored print settings.
"""

from __future__ import annotations

import os
import re
import stat
import time
from pathlib import Path
from types import TracebackType
from typing import Literal

import psutil
import pythoncom
import win32api
import win32event
import xlwings as xw
from loguru import logger

# Excel COM constants (avoid importing the type library).
_XL_CALC_DONE = 0  # xlDone
_XL_PASTE_VALUES = -4163  # xlPasteValues
_CALC_POLL_SECONDS = 0.15

# Launching several Excel instances at the exact same moment races the COM/DCOM
# registration and yields "RPC server is unavailable". We serialize only the brief
# startup+open across worker processes with a named mutex, and retry the create a few
# times. Everything after open still runs fully in parallel.
#
# The name is session-local (unqualified), NOT "Global\\": a Global object needs
# SeCreateGlobalPrivilege which a normal user lacks. All workers the Service launches share
# session 0, and interactive dev runs share the interactive session, so a per-session mutex
# serializes exactly the processes that would otherwise collide.
_STARTUP_MUTEX_NAME = "ReportFlowExcelStartup"
_STARTUP_WAIT_MS = 120_000
_APP_START_ATTEMPTS = 4
_APP_START_BACKOFF_SECONDS = 0.75


class ExcelJobError(RuntimeError):
    """A DETERMINISTIC run failure (bad path, missing sheet). Not worth retrying."""


# HRESULTs that mean "Excel/COM was transiently unavailable" — safe to retry a fresh session.
_TRANSIENT_HRESULTS = frozenset(
    {
        -2147023174,  # 0x800706BA RPC_S_SERVER_UNAVAILABLE
        -2147023170,  # 0x800706BE RPC_S_CALL_FAILED
        -2146959355,  # 0x80080005 CO_E_SERVER_EXEC_FAILURE ("Server execution failed")
        -2147417846,  # 0x8001010A RPC_E_SERVERCALL_RETRYLATER
        -2147418111,  # 0x80010001 RPC_E_CALL_REJECTED
        -2147023169,  # 0x800706BF RPC_S_CALL_FAILED_DNE
    }
)


def is_transient_com_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like a transient Excel/COM activation failure worth retrying.

    Deterministic :class:`ExcelJobError` (missing sheet/template) is never transient.
    """
    if isinstance(exc, ExcelJobError):
        return False
    hresult = getattr(exc, "args", [None])
    if hresult and isinstance(hresult[0], int) and hresult[0] in _TRANSIENT_HRESULTS:
        return True
    text = str(exc).lower()
    return (
        "rpc server is unavailable" in text
        or "server execution failed" in text
        or ("remote procedure call failed" in text)
    )


def _has_any_value(values: object) -> bool:
    """True when a used-range payload contains at least one non-empty cell value."""
    if values is None:
        return False
    if isinstance(values, list):
        return any(_has_any_value(v) for v in values)
    if isinstance(values, str):
        return bool(values.strip())
    return True  # numbers, datetimes, bools — real data


def _sanitize_for_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "sheet"


def _pdf_path_for_sheet(template: Path, sheet_name: str, *, single: bool) -> Path:
    """Resolve the output PDF path for one sheet from the job's pattern."""
    text = str(template)
    safe = _sanitize_for_filename(sheet_name)
    if "{sheet}" in text:
        return Path(text.replace("{sheet}", safe))
    if single:
        return template
    # Multiple sheets but no token: put the sheet name before the suffix as a safety net.
    return template.with_name(f"{template.stem}_{safe}{template.suffix}")


class ExcelRun:
    """Context manager that owns a single disposable Excel instance for one run."""

    def __init__(self, *, deadline: float | None = None) -> None:
        self._deadline = deadline
        self._com_initialized = False
        self._startup_mutex: int | None = None
        self.app: xw.App | None = None
        self.excel_pid: int | None = None
        self.excel_pid_reaped: bool = False

    # -- lifecycle ---------------------------------------------------------------

    def __enter__(self) -> ExcelRun:
        pythoncom.CoInitialize()
        self._com_initialized = True
        self._acquire_startup_lock()
        try:
            self.app = self._create_app_with_retry()
            self.excel_pid = int(self.app.pid)
            logger.info("Excel session started (pid={})", self.excel_pid)
            self._harden(self.app)
            self._connect_com_addins(self.app)
        except Exception:
            # Entry failed: __exit__ will NOT be called, so clean up here.
            self._teardown()
            raise
        return self

    @staticmethod
    def _connect_com_addins(app: xw.App) -> None:
        """Connect COM add-ins (e.g. PI DataLink) in this automation instance.

        Excel does NOT load COM add-ins when started via automation, so add-in worksheet
        functions (PI DataLink, Bloomberg, …) silently return nothing and the output
        comes out empty. Best-effort: every failure is logged and skipped. The INFO log
        of names + states is deliberate — support bundles must show whether the add-in
        the workbook depends on actually loaded.
        """
        try:
            addins = app.api.COMAddIns
        except Exception as e:  # noqa: BLE001 — no COMAddIns collection: nothing to do
            logger.info("COM add-ins unavailable in this Excel instance: {}", e)
            return
        try:
            count = int(addins.Count)
        except Exception:  # noqa: BLE001
            count = 0
        if count == 0:
            logger.info("No COM add-ins registered for this account (COMAddIns is empty)")
            return
        for i in range(1, count + 1):
            name = f"#{i}"
            try:
                addin = addins.Item(i)
                name = str(addin.Description or addin.ProgId)
                if not addin.Connect:
                    addin.Connect = True
                logger.info("COM add-in {!r}: connected={}", name, bool(addin.Connect))
            except Exception as e:  # noqa: BLE001 — one bad add-in must not stop the rest
                logger.warning("COM add-in {!r} could not be connected: {}", name, e)

    def _acquire_startup_lock(self) -> None:
        try:
            self._startup_mutex = win32event.CreateMutex(None, False, _STARTUP_MUTEX_NAME)
            win32event.WaitForSingleObject(self._startup_mutex, _STARTUP_WAIT_MS)
        except Exception as e:  # noqa: BLE001 — never let locking failure abort a run
            logger.debug("Could not acquire Excel startup mutex: {}", e)
            self._startup_mutex = None

    def _release_startup_lock(self) -> None:
        handle = self._startup_mutex
        if handle is None:
            return
        self._startup_mutex = None
        try:
            win32event.ReleaseMutex(handle)
        except Exception as e:  # noqa: BLE001
            logger.debug("ReleaseMutex failed: {}", e)
        try:
            win32api.CloseHandle(handle)
        except Exception as e:  # noqa: BLE001
            logger.debug("CloseHandle(mutex) failed: {}", e)

    def _create_app_with_retry(self) -> xw.App:
        last_error: Exception | None = None
        for attempt in range(1, _APP_START_ATTEMPTS + 1):
            app: xw.App | None = None
            try:
                app = xw.App(visible=False, add_book=False)
                int(app.pid)  # force the COM attach now so a transient RPC error surfaces here
                return app
            except Exception as e:  # noqa: BLE001 — transient COM/RPC startup failure
                last_error = e
                logger.warning(
                    "Excel startup attempt {}/{} failed: {}", attempt, _APP_START_ATTEMPTS, e
                )
                if app is not None:
                    try:
                        app.kill()
                    except Exception:  # noqa: BLE001
                        pass
                time.sleep(_APP_START_BACKOFF_SECONDS * attempt)
        raise ExcelJobError(
            f"could not start Excel after {_APP_START_ATTEMPTS} attempts: {last_error}"
        )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        self._teardown()
        return False  # never suppress exceptions

    def _harden(self, app: xw.App) -> None:
        # Every set is best-effort and individually guarded: a transient COM hiccup on one
        # property must not abort the run or skip the others.
        #
        # DELIBERATELY NOT disabled: macros (AutomationSecurity) and EnableEvents. Data
        # workbooks in the field (PI DataLink & co.) rely on macros/event hooks to
        # populate their data; force-disabling them produced empty reports. Excel's
        # automation default (macros allowed) matches the customer's proven legacy script.
        for attr, value in (
            ("DisplayAlerts", False),
            ("ScreenUpdating", False),
            ("AskToUpdateLinks", False),
            ("AlertBeforeOverwriting", False),
        ):
            try:
                setattr(app.api, attr, value)
            except Exception as e:  # noqa: BLE001 — best-effort hardening
                logger.debug("Could not set Application.{} = {!r}: {}", attr, value, e)

    def _teardown(self) -> None:
        """Guaranteed cleanup. Every step isolated so one failure cannot skip the rest."""
        self._release_startup_lock()  # safety net: normally released after open_workbook
        app = self.app
        if app is not None:
            try:
                for book in list(app.books):
                    try:
                        book.close()
                    except Exception as e:  # noqa: BLE001
                        logger.debug("book.close failed: {}", e)
            except Exception as e:  # noqa: BLE001
                logger.debug("enumerating books failed: {}", e)

            try:
                app.quit()
            except Exception as e:  # noqa: BLE001
                logger.debug("app.quit failed: {}", e)

            try:
                app.kill()
            except Exception as e:  # noqa: BLE001
                logger.debug("app.kill failed: {}", e)

        self.excel_pid_reaped = self._reap_pid(self.excel_pid)

        if self._com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception as e:  # noqa: BLE001
                logger.debug("CoUninitialize failed: {}", e)
            self._com_initialized = False

        self.app = None
        logger.info(
            "Excel session torn down (pid={}, reaped={})",
            self.excel_pid,
            self.excel_pid_reaped,
        )

    @staticmethod
    def _reap_pid(pid: int | None) -> bool:
        """Return True if the Excel PID is gone. As a last resort, kill it if it is still a
        live EXCEL.EXE (guarding against PID reuse by checking the process name)."""
        if pid is None:
            return True
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return True
        try:
            if "excel" not in (proc.name() or "").lower():
                return True  # PID reused by an unrelated process; ours already gone
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            return True
        except psutil.NoSuchProcess:
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to reap Excel pid {}: {}", pid, e)
            return False

    # -- steps -------------------------------------------------------------------

    def _check_deadline(self, what: str) -> None:
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise ExcelJobError(f"timed out before completing: {what}")

    @staticmethod
    def _clear_read_only_attribute(path: Path) -> None:
        """Drop the filesystem read-only flag: Excel would open the file read-only and
        add-ins like PI DataLink then refuse to refresh their data into it."""
        try:
            if path.stat().st_mode & stat.S_IWRITE:
                return
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            logger.info("Cleared the read-only attribute on {}", path)
        except OSError as e:
            logger.warning("Could not clear read-only attribute on {}: {}", path, e)

    def open_workbook(self, template_path: Path, sheet_names: list[str]) -> xw.Book:
        assert self.app is not None
        if not template_path.exists():
            raise ExcelJobError(f"workbook template not found: {template_path}")
        self._clear_read_only_attribute(template_path)
        logger.info("Opening workbook: {}", template_path)
        book = self.app.books.open(
            str(template_path),
            update_links=False,
            read_only=False,
            ignore_read_only_recommended=True,
        )
        try:
            if bool(book.api.ReadOnly):
                logger.warning(
                    "Workbook opened READ-ONLY despite requesting write access — live "
                    "data refresh may not work (is the file open elsewhere?)"
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not query ReadOnly state: {}", e)

        existing = [s.name for s in book.sheets]
        missing = [n for n in sheet_names if n not in existing]
        if missing:
            raise ExcelJobError(
                f"selected sheet(s) not found in workbook: {missing} (available: {existing})"
            )
        # The fragile startup+open is done; let other worker processes start their Excel now.
        self._release_startup_lock()
        return book

    def refresh_and_wait(self, book: xw.Book, post_refresh_wait_seconds: int = 0) -> None:
        """Force a synchronous refresh of connections/Power Query, then wait for calc."""
        # Make every query synchronous so RefreshAll blocks instead of returning early.
        try:
            for conn in book.api.Connections:
                for sub in ("OLEDBConnection", "ODBCConnection"):
                    try:
                        getattr(conn, sub).BackgroundQuery = False
                    except Exception:  # noqa: BLE001 — connection type may lack this sub-object
                        pass
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not enumerate workbook connections: {}", e)

        logger.info("Refreshing external data / Power Query…")
        # Let any COM error propagate unwrapped so the runner can classify it as transient
        # (retryable) vs. deterministic.
        book.api.RefreshAll()

        assert self.app is not None
        try:
            self.app.api.CalculateUntilAsyncQueriesDone()
        except Exception as e:  # noqa: BLE001
            logger.debug("CalculateUntilAsyncQueriesDone unavailable: {}", e)

        # Full rebuild forces re-evaluation of EVERY formula — essential for add-in
        # functions (PI DataLink & co.) whose add-in was only just connected and whose
        # cached results are stale or empty.
        try:
            self.app.api.CalculateFullRebuild()
            logger.info("CalculateFullRebuild issued")
        except Exception as e:  # noqa: BLE001
            logger.debug("CalculateFullRebuild unavailable ({}); using normal calculate", e)
            self.app.calculate()
        self._wait_for_calc()

        if post_refresh_wait_seconds > 0:
            logger.info("Extra settle wait for slow add-ins: {}s", post_refresh_wait_seconds)
            waited = 0.0
            while waited < post_refresh_wait_seconds:
                self._check_deadline("post-refresh wait")
                step = min(1.0, post_refresh_wait_seconds - waited)
                time.sleep(step)
                waited += step
            # The add-in may have filled cells asynchronously — settle the calc chain.
            self.app.calculate()
            self._wait_for_calc()

    def _wait_for_calc(self) -> None:
        assert self.app is not None
        iterations = 0
        while True:
            self._check_deadline("waiting for calculation")
            try:
                state = int(self.app.api.CalculationState)
            except Exception as e:  # noqa: BLE001
                logger.debug("CalculationState unavailable ({}); assuming done", e)
                return
            if state == _XL_CALC_DONE:
                logger.info("Calculation complete after {} poll(s)", iterations)
                return
            iterations += 1
            time.sleep(_CALC_POLL_SECONDS)

    def freeze_sheets(self, book: xw.Book, sheet_names: list[str]) -> None:
        """Convert formulas to static values on the SELECTED sheets only.

        Uses COM ``Copy`` -> ``PasteSpecial(xlPasteValues)`` — the same mechanism as the
        customer's proven legacy script. It preserves formatting exactly and avoids
        round-tripping large ranges through Python.
        """
        assert self.app is not None
        for name in sheet_names:
            self._check_deadline(f"freezing sheet {name}")
            sheet = book.sheets[name]
            used = sheet.api.UsedRange
            cell_count = int(used.Cells.Count)
            used.Copy()
            used.PasteSpecial(Paste=_XL_PASTE_VALUES)
            try:
                self.app.api.CutCopyMode = False
            except Exception as e:  # noqa: BLE001 — cosmetic (clears the marching ants)
                logger.debug("Could not reset CutCopyMode: {}", e)
            logger.info("Froze formulas to values on sheet {!r} ({} cells)", name, cell_count)

    def validate_sheets_not_empty(self, book: xw.Book, sheet_names: list[str]) -> None:
        """Fail loudly when a selected sheet produced no data at all.

        An all-empty used range means the refresh silently yielded nothing (add-in not
        loaded, no data access for this account, …) — shipping a blank report as
        "success" is the one outcome the user must never see.
        """
        for name in sheet_names:
            self._check_deadline(f"validating sheet {name}")
            sheet = book.sheets[name]
            values = sheet.used_range.value
            if _has_any_value(values):
                continue
            raise ExcelJobError(
                f"sheet {name!r} came out EMPTY after refresh — the data source produced "
                "nothing. Check the worker log's COM add-in list and whether the service "
                "account has access to the data source (e.g. PI)."
            )

    def delete_unselected_sheets(self, book: xw.Book, sheet_names: list[str]) -> None:
        """Remove every sheet that is not part of the report before saving the output.

        Runs AFTER freeze, so selected sheets hold static values and no longer reference
        the sheets being deleted.
        """
        keep = set(sheet_names)
        for sheet in list(book.sheets):
            if sheet.name in keep:
                continue
            try:
                sheet.delete()
                logger.info("Deleted unselected sheet from output: {!r}", sheet.name)
            except Exception as e:  # noqa: BLE001 — a stubborn sheet must not fail the run
                logger.warning("Could not delete sheet {!r}: {}", sheet.name, e)

    def export_pdfs(
        self, book: xw.Book, sheet_names: list[str], output_pdf_path: Path
    ) -> list[Path]:
        """One PDF per selected sheet, honoring each sheet's own PageSetup."""
        single = len(sheet_names) == 1
        produced: list[Path] = []
        for name in sheet_names:
            self._check_deadline(f"exporting PDF for {name}")
            pdf_path = _pdf_path_for_sheet(output_pdf_path, name, single=single)
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            book.sheets[name].to_pdf(str(pdf_path))
            logger.info("Exported PDF: {}", pdf_path)
            produced.append(pdf_path)
        return produced

    def save_output(self, book: xw.Book, output_xlsx_path: Path) -> Path:
        """Save-as to the output path. The SOURCE file is never written.

        Hard guard: refuse to save onto the input file even if a job misconfiguration
        resolves the output to the same path.
        """
        source = Path(str(book.api.FullName))
        if output_xlsx_path.resolve() == source.resolve():
            raise ExcelJobError(
                f"output path equals the input workbook ({source}) — refusing to "
                "overwrite the source file. Choose a different output folder/filename."
            )
        output_xlsx_path.parent.mkdir(parents=True, exist_ok=True)
        book.save(str(output_xlsx_path))
        logger.info("Saved output workbook: {}", output_xlsx_path)
        return output_xlsx_path

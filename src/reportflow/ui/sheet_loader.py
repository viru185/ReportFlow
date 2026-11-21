"""Read workbooks' sheet names off the UI thread, so the job editor never freezes.

The editor asks :class:`SheetLoader` for each workbook (by its id) whenever the sheets could
have changed: when the editor opens, when a file is added or replaced, when a workbook is
selected and when the window comes back to the front. A newer request for the same workbook
supersedes an older one — a result that arrives late is dropped, never applied over newer
data — and a result for a workbook that was removed, or a dialog that closed, goes nowhere.

The work itself runs on an executor:

- :class:`PoolExecutor` (the app): a small private thread pool. Results come back through a
  bridge object owned by the application, so a late result can never touch a closed dialog
  and closing never has to wait. (A QThread per request would abort the process if a dialog
  were destroyed while one is still running.)
- :class:`InlineExecutor` / :class:`ManualExecutor` (tests): deterministic stand-ins.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, Signal

from reportflow.ui.api_client import ApiError

Reader = Callable[[str], list[str]]


@dataclass(frozen=True)
class SheetOutcome:
    """What reading a workbook gave: ``ok`` with its sheets, ``missing`` (the service can't
    find the file), ``unreadable`` (it can't open it) or ``offline`` (the service is down)."""

    state: str
    names: tuple[str, ...] = ()
    message: str = ""


def read_sheets(reader: Reader, path: str) -> SheetOutcome:
    try:
        names = reader(path)
    except ApiError as e:
        if e.status_code is None:
            return SheetOutcome("offline", message=str(e))
        if e.status_code == 404:
            return SheetOutcome("missing", message=str(e))
        return SheetOutcome("unreadable", message=str(e))
    except Exception as e:  # noqa: BLE001 — anything else is "couldn't read it", never a crash
        return SheetOutcome("unreadable", message=str(e))
    return SheetOutcome("ok", tuple(names))


# -- executors ------------------------------------------------------------------------

Job = Callable[[], Any]
Deliver = Callable[[Any], None]
Wanted = Callable[[], bool]


class InlineExecutor:
    """Runs the read immediately, on the calling thread (tests)."""

    def submit(self, job: Job, deliver: Deliver, wanted: Wanted) -> None:
        if wanted():
            deliver(job())


@dataclass
class ManualExecutor:
    """Queues reads; a test finishes them in whatever order it wants."""

    queue: list[tuple[Job, Deliver, Wanted]] = field(default_factory=list)

    def submit(self, job: Job, deliver: Deliver, wanted: Wanted) -> None:
        self.queue.append((job, deliver, wanted))

    def finish(self, index: int = 0) -> None:
        job, deliver, wanted = self.queue.pop(index)
        if wanted():
            deliver(job())

    def finish_all(self) -> None:
        while self.queue:
            self.finish(0)


class _Bridge(QObject):
    """Lives as long as the application; carries results back to the UI thread."""

    done = Signal(object, object)  # (deliver callback, result)

    def __init__(self, parent: QObject | None) -> None:
        super().__init__(parent)
        self.done.connect(lambda deliver, result: deliver(result))


class _Task(QRunnable):
    def __init__(self, bridge: _Bridge, job: Job, deliver: Deliver, wanted: Wanted) -> None:
        super().__init__()
        self._bridge, self._job, self._deliver, self._wanted = bridge, job, deliver, wanted

    def run(self) -> None:
        if not self._wanted():  # superseded while it waited in the queue
            return
        result = self._job()
        self._bridge.done.emit(self._deliver, result)


class PoolExecutor:
    """Two background threads shared by every editor."""

    _shared: PoolExecutor | None = None

    def __init__(self) -> None:
        app = QCoreApplication.instance()
        self._bridge = _Bridge(app)
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)
        if app is not None:
            app.aboutToQuit.connect(self._shutdown)

    @classmethod
    def shared(cls) -> PoolExecutor:
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def submit(self, job: Job, deliver: Deliver, wanted: Wanted) -> None:
        self._pool.start(_Task(self._bridge, job, deliver, wanted))

    def _shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(2000)


# -- the loader -------------------------------------------------------------------------


class SheetLoader(QObject):
    """Requests sheet names per workbook id; emits ``loaded`` with only the newest answer."""

    loaded = Signal(int, str, object)  # workbook id, path, SheetOutcome

    def __init__(self, reader: Reader, executor: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._reader = reader
        self._executor = executor
        self._latest: dict[int, int] = {}
        self._alive = True

    def request(self, uid: int, path: str) -> None:
        ticket = self._latest.get(uid, 0) + 1
        self._latest[uid] = ticket
        reader = self._reader

        def wanted() -> bool:
            return self._alive and self._latest.get(uid) == ticket

        def deliver(outcome: Any) -> None:
            try:
                if wanted():
                    self.loaded.emit(uid, path, outcome)
            except RuntimeError:
                pass  # the dialog (and this object) is already gone

        self._executor.submit(lambda: read_sheets(reader, path), deliver, wanted)

    def forget(self, uid: int) -> None:
        """The workbook was removed: whatever is still on its way for it is dropped."""
        self._latest.pop(uid, None)

    def close(self) -> None:
        self._alive = False

"""Drag to reorder (0.15): the kit's grip + drop line, and the three lists that use it — a job's
workbooks, a job's schedules, and the dashboard's job cards."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget

from reportflow.ui.kit import Menu
from reportflow.ui.kit.reorder import ROW_MIME, DragHandle, Reorder

from .test_ui import FakeApi, _sample_job_dict
from .test_workbooks import SheetApi, _editor


def _settle(qtbot) -> None:
    """Moves are reported after the event that asked for them has returned."""
    qtbot.wait(5)


class Rows(QWidget):
    def __init__(self, n: int) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        self.rows: list[QFrame] = []
        for i in range(n):
            row = QFrame()
            row.setObjectName(f"row{i}")
            row.setFixedHeight(40)
            self.rows.append(row)
            lay.addWidget(row)
        self.reorder = Reorder(self, lambda: self.rows)
        self.moves: list[tuple[int, int]] = []
        self.reorder.moved.connect(lambda a, b: self.moves.append((a, b)))
        self.handles = [self.reorder.attach(row, inset=2) for row in self.rows]


@pytest.fixture
def rows(qtbot):
    w = Rows(4)
    qtbot.addWidget(w)
    w.resize(400, 260)
    w.show()
    qtbot.waitExposed(w)
    return w


_KEEP: list[QMimeData] = []  # an event only points at its data: keep the data alive


def _drag_event(cls, at: QPoint, *, mime: str = ROW_MIME):
    data = QMimeData()
    data.setData(mime, b"0")
    _KEEP.append(data)
    args = (
        Qt.DropAction.MoveAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    return cls(QPointF(at), *args) if cls is QDropEvent else cls(at, *args)


def test_the_grip_sits_in_the_margin_and_shows_on_hover(qtbot, rows):
    handle = rows.handles[1]
    assert isinstance(handle, DragHandle) and handle.x() == 2
    assert abs(handle.geometry().center().y() - rows.rows[1].height() // 2) <= 1
    assert not handle.shown  # nothing shows until the row is hovered
    QApplication.sendEvent(rows.rows[1], _enter())
    assert handle.shown and not rows.handles[0].shown
    QApplication.sendEvent(rows.rows[1], _leave())
    assert not handle.shown


def test_one_row_has_nothing_to_reorder(qtbot):
    w = Rows(1)
    qtbot.addWidget(w)
    QApplication.sendEvent(w.rows[0], _enter())
    assert not w.handles[0].shown and not w.handles[0].isEnabled()


def test_where_a_dragged_row_lands(qtbot, rows):
    r = rows.reorder
    tops = [row.geometry().top() for row in rows.rows]
    assert r.drop_index(QPoint(50, tops[0] + 5)) == 0  # top half of the first row
    assert r.drop_index(QPoint(50, tops[0] + 30)) == 1  # its bottom half: below it
    assert r.drop_index(QPoint(50, tops[3] + 35)) == 4  # past the last row
    # The drop line shows between rows while dragging; dropping lands there.
    r._dragging = rows.rows[0]
    try:
        move = _drag_event(QDragEnterEvent, QPoint(50, tops[2] + 5))
        QApplication.sendEvent(rows, move)
        assert move.isAccepted() and r._line.isVisibleTo(rows)
        assert tops[1] + 40 <= r._line.geometry().center().y() <= tops[2]
        # Hovering the row's own place (or just below it) shows no line: nothing would move.
        QApplication.sendEvent(rows, _drag_event(QDragMoveEvent, QPoint(50, tops[1] + 5)))
        assert not r._line.isVisibleTo(rows)
        drop = _drag_event(QDropEvent, QPoint(50, tops[3] + 5))
        QApplication.sendEvent(rows, drop)
        assert drop.isAccepted() and r._target == 3
    finally:
        r._dragging = None
    r.land(0, 3)
    r.land(1, 1)  # its own place
    r.land(1, 2)  # just below itself
    _settle(qtbot)
    assert rows.moves == [(0, 2)]


def test_other_drags_are_left_alone(qtbot, rows):
    """Excel files dragged from Explorer go to the General tab's own drop handling."""
    event = _drag_event(QDragEnterEvent, QPoint(50, 20), mime="text/uri-list")
    assert rows.reorder.eventFilter(rows, event) is False


def test_alt_arrows_move_the_row_with_the_keyboard(qtbot, rows):
    focusable = QWidget(rows.rows[2])
    focusable.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    focusable.show()  # made after the window was shown: hidden (and unfocusable) until then
    rows.reorder.keys(rows.rows[2], lambda: 2)
    with qtbot.waitActive(rows):
        rows.activateWindow()
    focusable.setFocus()
    qtbot.keyClick(focusable, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    _settle(qtbot)
    assert rows.moves == [(2, 1)]
    assert rows.handles[2].shown  # the row with the keyboard shows its grip
    assert not rows.reorder.step(3, 1) and not rows.reorder.step(0, -1)  # ends


# -- the job's workbooks ------------------------------------------------------------------


def _three_workbooks() -> dict:
    job = _sample_job_dict()
    job["workbooks"] = [
        {"input_excel_path": f"C:/r/{name}.xlsx", "sheets": [{"name": "Summary"}]}
        for name in ("Alpha", "Beta", "Gamma")
    ]
    return job


def _labels(dlg) -> list[str]:
    return [row.name.text() for row in dlg.wb_list.rows()]


def test_workbooks_reorder_and_the_shown_one_stays_shown(qtbot):
    dlg = _editor(qtbot, SheetApi(), _three_workbooks())
    dlg.wb_list.list.setCurrentRow(1)  # Beta is shown
    dlg.wb_list.reorder.moved.emit(0, 2)  # Alpha to the bottom
    assert _labels(dlg) == ["Beta.xlsx", "Gamma.xlsx", "Alpha.xlsx"]
    assert dlg.wb_title.text() == "Beta.xlsx" and dlg.wb_list.current() == 0
    # Built and attached in this order.
    paths = [wb["input_excel_path"] for wb in dlg.payload()["workbooks"]]
    assert paths == ["C:/r/Beta.xlsx", "C:/r/Gamma.xlsx", "C:/r/Alpha.xlsx"]
    # Every row has its grip; the selected one shows it (the keyboard path).
    handles = [getattr(row, "_rf_handle", None) for row in dlg.wb_list.rows()]
    assert all(isinstance(h, DragHandle) for h in handles)
    assert handles[0].shown and not handles[1].shown


def test_workbook_keys_and_menu(qtbot, monkeypatch):
    dlg = _editor(qtbot, SheetApi(), _three_workbooks())
    dlg.show()
    with qtbot.waitActive(dlg):
        dlg.activateWindow()
    dlg.wb_list.list.setCurrentRow(0)
    dlg.wb_list.list.setFocus()
    qtbot.keyClick(dlg.wb_list.list, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    _settle(qtbot)
    assert _labels(dlg) == ["Beta.xlsx", "Alpha.xlsx", "Gamma.xlsx"]
    assert dlg.wb_list.current() == 1 and dlg.wb_title.text() == "Alpha.xlsx"
    shown: list[list[tuple[str, bool]]] = []
    monkeypatch.setattr(
        Menu,
        "exec",
        lambda self, *a: shown.append([(x.text(), x.isEnabled()) for x in self.actions()]),
    )
    viewport = dlg.wb_list.list.viewport()
    first = dlg.wb_list.list.visualItemRect(dlg.wb_list.list.item(0)).center()
    dlg.wb_list._context_menu(first)
    entries = dict(e for e in shown[0] if e[0])
    # The key is a hint in the menu's key column, not a second shortcut.
    assert entries["Move up	Alt+↑"] is False and entries["Move down	Alt+↓"] is True
    assert viewport is not None


# -- the job's schedules ------------------------------------------------------------------


def test_schedules_reorder_and_keep_their_order_when_reopened(qtbot):
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    w = ScheduleWidget()
    qtbot.addWidget(w)
    w.load(["0 6 * * *", "0 9 * * SAT,SUN", "*/30 22 * * FRI"])
    assert [r.kind.currentData() for r in w.rows()] == ["daily", "weekly", "cron"]
    w.move_rule(2, 0)  # the custom one first
    crons = w.to_crons()
    assert crons == ["*/30 22 * * FRI", "0 6 * * *", "0 9 * * SAT,SUN"]
    w.load(crons)
    assert [r.kind.currentData() for r in w.rows()] == ["cron", "daily", "weekly"]
    # The grip sits beside each rule's kind (its first line).
    row = w.rows()[1]
    handle = row._rf_handle
    assert abs(handle.geometry().center().y() - row.kind.geometry().center().y()) <= 1


def test_schedule_alt_arrows(qtbot):
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    w = ScheduleWidget()
    qtbot.addWidget(w)
    w.load(["0 6 * * *", "0 9 * * SAT,SUN"])
    w.show()
    with qtbot.waitActive(w):
        w.activateWindow()
    second = w.rows()[1]
    second.kind.setFocus()
    qtbot.keyClick(second.kind, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    _settle(qtbot)
    assert w.rows()[0] is second and w.to_crons()[0] == "0 9 * * SAT,SUN"


# -- the dashboard's job cards ------------------------------------------------------------


class OrderApi(FakeApi):
    def __init__(self, names, **kw):
        super().__init__(jobs=[{**_sample_job_dict(), "name": n} for n in names], **kw)
        self.orders: list[list[str]] = []
        self.refuse = False

    def reorder_jobs(self, names):
        from reportflow.ui.api_client import ApiError

        if self.refuse:
            raise ApiError("the job list changed — reload it")
        self.orders.append(list(names))
        by_name = {j["name"]: j for j in self._jobs}
        self._jobs = [by_name[n] for n in names]
        return {"ok": True}


def _names(win) -> list[str]:
    return [c.property("jobName") for c in win._cards()]


def test_dashboard_cards_reorder_and_the_order_is_saved(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    api = OrderApi(["alpha", "beta", "gamma"])
    win = MainWindow(api)
    qtbot.addWidget(win)
    win.refresh()
    assert _names(win) == ["alpha", "beta", "gamma"]
    win._jobs_reorder.moved.emit(2, 0)
    assert api.orders == [["gamma", "alpha", "beta"]]
    assert _names(win) == ["gamma", "alpha", "beta"]
    # Each card has its grip, clear of the status edge.
    assert all(c._rf_handle.x() == 4 for c in win._cards())


def test_a_refused_order_says_so_and_reloads(qtbot):
    from reportflow.ui.feedback import toasts
    from reportflow.ui.windows.main_window import MainWindow

    api = OrderApi(["alpha", "beta"])
    win = MainWindow(api)
    qtbot.addWidget(win)
    win.refresh()
    api.refuse = True
    win._jobs_reorder.moved.emit(0, 1)
    assert any("Couldn't save the new order" in t for t in toasts(win))
    assert _names(win) == ["alpha", "beta"]  # back to what the service has


def test_dashboard_keys_keep_the_card_focused(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    api = OrderApi(["alpha", "beta", "gamma"])
    win = MainWindow(api)
    qtbot.addWidget(win)
    win.refresh()
    win.show()
    with qtbot.waitActive(win):
        win.activateWindow()
    card = win._cards()[0]
    card.setFocus()
    qtbot.keyClick(card, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    _settle(qtbot)
    assert _names(win) == ["beta", "alpha", "gamma"]
    focused = QApplication.focusWidget()
    assert focused is not None and focused.property("jobName") == "alpha"


def test_the_dashboard_waits_while_a_card_is_dragged(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    api = OrderApi(["alpha", "beta"])
    win = MainWindow(api)
    qtbot.addWidget(win)
    win.refresh()
    first = win._cards()[0]
    win._jobs_reorder._dragging = first
    try:
        api._jobs = list(reversed(api._jobs))
        win.refresh()
        assert win._cards()[0] is first  # not rebuilt under the drag
    finally:
        win._jobs_reorder._dragging = None


def _enter():
    from PySide6.QtCore import QEvent

    return QEvent(QEvent.Type.Enter)


def _leave():
    from PySide6.QtCore import QEvent

    return QEvent(QEvent.Type.Leave)

"""The UI kit: rounded popups, smooth scrolling, the wheel guard, popovers and labels."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QToolTip, QVBoxLayout, QWidget

from reportflow.ui.kit import (
    Button,
    ComboBox,
    ElidedLabel,
    Menu,
    PathLabel,
    Popover,
    ScrollArea,
    SpinBox,
    breakable,
)


@pytest.fixture
def themed(qapp):
    from reportflow.ui.style import apply_theme

    old_qss, old_palette = qapp.styleSheet(), qapp.palette()
    apply_theme(qapp)
    yield qapp
    qapp.setStyleSheet(old_qss)
    qapp.setPalette(old_palette)


def _wheel(widget: QWidget, notches: int = -1) -> QWheelEvent:
    event = QWheelEvent(
        QPointF(5, 5),
        QPointF(widget.mapToGlobal(QPoint(5, 5))),
        QPoint(0, 0),
        QPoint(0, 120 * notches),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)
    return event


def _corner_alpha(widget: QWidget) -> tuple[int, int]:
    image = widget.grab().toImage()
    corner = image.pixelColor(0, 0).alpha()
    middle = image.pixelColor(image.width() // 2, image.height() // 2).alpha()
    return corner, middle


def test_buttons_carry_their_variant_and_never_press_on_enter(qtbot):
    primary = Button("Save", variant="primary")
    qtbot.addWidget(primary)
    assert primary.property("variant") == "primary"
    assert not primary.autoDefault()
    with pytest.raises(ValueError):
        Button("x", variant="loud")


def test_menus_are_rounded_with_see_through_corners(qtbot, themed):
    host = QWidget()
    qtbot.addWidget(host)
    menu = Menu(host)
    menu.addAction("Edit")
    menu.addAction("Delete")
    assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    menu.popup(QPoint(100, 100))
    qtbot.waitUntil(menu.isVisible)
    corner, middle = _corner_alpha(menu)
    assert corner == 0 and middle == 255
    menu.hide()


def test_menus_qt_makes_itself_are_rounded_too(qtbot, themed):
    """A text field's right-click menu comes from Qt, not the kit — the chrome filter
    still makes it translucent before it is first shown."""
    edit = QLineEdit()
    qtbot.addWidget(edit)
    menu = edit.createStandardContextMenu()
    menu.ensurePolished()
    assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_tooltips_are_rounded(qtbot, themed):
    host = QLabel("hover me")
    qtbot.addWidget(host)
    host.show()
    QToolTip.showText(host.mapToGlobal(QPoint(5, 5)), "A tooltip", host)
    tips = [w for w in QApplication.topLevelWidgets() if w.inherits("QTipLabel")]
    assert tips and tips[0].testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    QToolTip.hideText()


def test_combo_popup_is_rounded_and_drops_below(qtbot, themed):
    combo = ComboBox()
    combo.addItems(["Fail the whole run — send nothing", "Send the workbooks that worked"])
    qtbot.addWidget(combo)
    combo.show()
    container = combo.view().window()
    assert container is not combo.window()
    assert container.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    combo.showPopup()
    qtbot.waitUntil(container.isVisible)
    assert container.y() >= combo.mapToGlobal(QPoint(0, combo.height())).y()
    combo.hidePopup()


def test_the_wheel_never_changes_an_unfocused_field(qtbot):
    combo = ComboBox()
    combo.addItems(["a", "b", "c"])
    spin = SpinBox()
    spin.setValue(5)
    for widget in (combo, spin):
        qtbot.addWidget(widget)
        widget.show()
    event = _wheel(combo)
    assert combo.currentIndex() == 0 and not event.isAccepted()  # the page scrolls instead
    _wheel(spin)
    assert spin.value() == 5


def test_wheel_scrolling_is_animated_and_lands_on_target(qtbot):
    content = QWidget()
    column = QVBoxLayout(content)
    for i in range(80):
        column.addWidget(QLabel(f"line {i}"))
    area = ScrollArea(content)
    qtbot.addWidget(area)
    area.resize(300, 200)
    area.show()
    qtbot.waitExposed(area)
    bar = area.verticalScrollBar()
    assert bar.value() == 0
    _wheel(area.viewport(), -1)
    assert bar.value() < 10  # not an instant jump…
    qtbot.waitUntil(lambda: bar.value() > 20, timeout=1000)  # …but it gets there
    assert area.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_popover_closes_on_escape_and_returns_focus(qtbot, themed):
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    anchor = Button("+ Add time")
    layout.addWidget(anchor)
    host.show()
    qtbot.waitExposed(host)
    popover = Popover(host)
    field = QLineEdit()
    popover.body.addWidget(field)
    popover.open_at(anchor, focus=field)
    qtbot.waitUntil(popover.isVisible)
    assert popover.y() >= anchor.mapToGlobal(QPoint(0, anchor.height())).y()
    assert popover.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    qtbot.keyClick(popover, Qt.Key.Key_Escape)
    assert not popover.isVisible()


def test_long_text_never_widens_a_layout(qtbot):
    path = (
        r"C:\Users\someone\Work\teams_download\PI_Vision_Report_01_Oct_to_31_Oct"
        r"\PI_Vision_Report_01_Oct_to_31_Oct\Aditya_PI_Vision_01_Oct_to_31_Oct.xlsx"
    )
    label = ElidedLabel(path)
    qtbot.addWidget(label)
    assert label.minimumSizeHint().width() < 100
    label.resize(200, 20)
    assert label.is_elided() and label.full_text() == path
    wrapped = QLabel(breakable(path))
    wrapped.setWordWrap(True)
    assert wrapped.minimumSizeHint().width() < 400  # breakable at every \ and _


def test_path_label_copies_the_full_path(qtbot):
    path = r"\\server\share\Reports\Monthly\report.xlsx"
    label = PathLabel(path)
    qtbot.addWidget(label)
    assert label.copy_button is not None
    label.copy_button.click()
    clipboard = QGuiApplication.clipboard()
    assert clipboard is not None and clipboard.text() == path


def test_a_scrolling_page_never_paints_over_its_frames_rounded_corners(qtbot, themed):
    """QScrollArea.setWidget turns the page's background fill on; that square fill hid the
    tab panel's corner arcs (owner's screenshots, 0.14)."""
    from PySide6.QtWidgets import QTabWidget

    from reportflow.ui.style import BG

    inner = QWidget()
    QVBoxLayout(inner).addWidget(QLabel("content"))
    page = ScrollArea(inner)
    assert not inner.autoFillBackground()
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    tabs.addTab(page, "General")
    tabs.resize(400, 240)
    tabs.show()
    qtbot.waitExposed(tabs)
    image = tabs.grab().toImage()
    h = image.height()
    corner = [image.pixelColor(i, h - 1 - i).name() for i in range(1, 4)]
    assert any(color != BG for color in corner), corner  # the border's curve is visible

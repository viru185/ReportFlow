"""App-wide finishing for widgets Qt creates by itself.

The kit's own widgets set themselves up, but some surfaces are made inside Qt — tooltips,
the right-click menu of every text field, the scroll areas inside text editors. One
application event filter catches each of them as it is *polished* (prepared for its first
show) and applies the same treatment as the kit:

- menus and tooltips become frameless and translucent, so their QSS radius shows;
- every scroll area gets smooth wheel scrolling.

``install_chrome(app)`` runs once, right after ``apply_theme``.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QMenu, QPlainTextEdit, QWidget

from reportflow.ui.kit.popups import round_popup
from reportflow.ui.kit.views import smooth_scroll

_POLISH = QEvent.Type.Polish


class _Chrome(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == _POLISH and isinstance(watched, QWidget):
            _finish(watched)
        return False


def _finish(widget: QWidget) -> None:
    if isinstance(widget, QMenu) or widget.inherits("QTipLabel"):
        if not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            round_popup(widget)
    elif isinstance(widget, QAbstractScrollArea) and not isinstance(widget, QPlainTextEdit):
        # QPlainTextEdit scrolls by line, not pixel; Qt's own stepping is right for it.
        smooth_scroll(widget)


def install_chrome(app: QApplication) -> None:
    """Install the finishing filter once per application."""
    if app.property("_rf_chrome"):
        return
    app.setProperty("_rf_chrome", True)
    chrome = _Chrome(app)
    app.installEventFilter(chrome)

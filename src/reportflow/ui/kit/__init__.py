"""ReportFlow's UI kit: the one set of widgets every window is built from.

Each class wraps a Qt widget once — its look (a ``variant`` the stylesheet in ``style.py``
paints) and its behaviour (cursor, focus, wheel, popups, eliding) — so every button,
dropdown, list, menu and label in the app looks and behaves the same. A window that needs
something different uses another variant, not its own stylesheet.

``tests/ui/test_kit_usage.py`` fails if UI code builds a raw ``QPushButton``, ``QComboBox``,
``QMenu``… or sets an inline stylesheet, so the look can't drift again.
"""

from reportflow.ui.kit.buttons import Button, IconButton, SegmentButton, segmented, set_variant
from reportflow.ui.kit.inputs import ComboBox, SpinBox, TimeEdit, styled_completer
from reportflow.ui.kit.labels import ElidedLabel, PathLabel, Tag, breakable, open_folder
from reportflow.ui.kit.popups import Menu, Popover, round_popup
from reportflow.ui.kit.views import (
    ListWidget,
    PopupItemDelegate,
    ScrollArea,
    TableWidget,
    smooth_scroll,
)

__all__ = [
    "Button",
    "ComboBox",
    "ElidedLabel",
    "IconButton",
    "ListWidget",
    "Menu",
    "PathLabel",
    "Popover",
    "PopupItemDelegate",
    "ScrollArea",
    "SegmentButton",
    "SpinBox",
    "TableWidget",
    "Tag",
    "TimeEdit",
    "breakable",
    "open_folder",
    "round_popup",
    "segmented",
    "set_variant",
    "smooth_scroll",
    "styled_completer",
]

"""In-app Help: the user guide (``ui/help/user_guide.md``) with a section list and search.

The guide is plain Markdown, so it reads well in the app and on GitHub. Headings carry an id
(``## Schedules {#schedule}``) so other screens can open the guide at a section — F1 opens the
part for the current tab — and links such as ``[groups](#groups)`` jump inside it. Three
tables are generated when the guide loads, from the same lists the app itself uses, so the
Help can't drift from the app: the email placeholders, their recipes and the file-name tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrame,
    QTextFrameFormat,
    QTextLength,
    QTextOption,
    QTextTable,
    QTextTableFormat,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from reportflow import __about__ as about
from reportflow.core.email.render import PLACEHOLDERS, render_email, sample_context
from reportflow.core.output_names import OUTPUT_NAME_TOKENS, expand_output_name
from reportflow.ui.feedback import restore_geometry, save_geometry
from reportflow.ui.style import ACCENT_HOVER, BORDER, CARD_BG, TEXT, TEXT_MUTED

GUIDE_PATH = Path(__file__).resolve().parents[1] / "help" / "user_guide.md"
EXAMPLE_TIME = datetime(2026, 10, 7, 6, 15)  # stable examples: 07-Oct-2026 06:15
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*(?:\{#([\w-]+)\})?\s*$")

_RECIPES = [
    (
        "A dated subject",
        "Daily production report — {{ today }}",
        "Daily production report — 07-Oct-2026",
    ),
    (
        "Yesterday's data (a report run in the morning)",
        "Production for {{ yesterday }} is attached.",
        "Production for 06-Oct-2026 is attached.",
    ),
    (
        "A monthly report run on the 1st",
        "The {{ previous_month }} summary is attached.",
        "The September 2026 summary is attached.",
    ),
    ("Your own date format", "{{ run_date.strftime('%d/%m/%Y') }}", "07/10/2026"),
    (
        "Only when the run has warnings",
        "{% if warnings %}Please note {{ warning_count }} warning(s).{% endif %}",
        "(nothing when there are none)",
    ),
    (
        "List the attached files",
        "<ul>{% for f in attachments %}<li>{{ f }}</li>{% endfor %}</ul>",
        "a bullet per file",
    ),
]


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _code(text: str) -> str:
    return f"`{_cell(text)}`"


def placeholder_table(now: datetime = EXAMPLE_TIME) -> str:
    sample = sample_context(now=now)
    rows = ["| Placeholder | Example | What it is |", "|---|---|---|"]
    for group, label, token, about_it in PLACEHOLDERS:
        example = "" if group == "Blocks" else render_email(token, sample)
        rows.append(f"| {_code(token)} | {_cell(example)} | {_cell(label)} — {_cell(about_it)} |")
    return "\n".join(rows)


def recipes_table() -> str:
    rows = ["| For | Write | Gives |", "|---|---|---|"]
    rows += [
        f"| {_cell(what)} | {_code(code)} | {_cell(result)} |" for what, code, result in _RECIPES
    ]
    return "\n".join(rows)


def output_tokens_table(now: datetime = EXAMPLE_TIME) -> str:
    rows = ["| Placeholder | Example | What it is |", "|---|---|---|"]
    for label, token, about_it in OUTPUT_NAME_TOKENS:
        example = expand_output_name(
            token, job_name="Sales", run_id="a1b2c3d4", now=now, workbook="Sales"
        )
        rows.append(f"| {_code(token)} | {_cell(example)} | {_cell(label)} — {_cell(about_it)} |")
    return "\n".join(rows)


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    level: int


def load_guide(path: Path = GUIDE_PATH) -> tuple[str, list[Section]]:
    """The guide's Markdown (generated tables filled in, ``{#id}`` markers removed) and the
    sections that have ids, in order."""
    text = path.read_text(encoding="utf-8")
    text = text.replace("<!-- placeholders -->", placeholder_table())
    text = text.replace("<!-- recipes -->", recipes_table())
    text = text.replace("<!-- output-tokens -->", output_tokens_table())
    sections: list[Section] = []
    lines: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        match = None if in_code else _HEADING.match(line)
        if match and match.group(3):
            hashes, title, section_id = match.groups()
            sections.append(Section(section_id, title, len(hashes)))
            lines.append(f"{hashes} {title}")
        else:
            lines.append(line)
    return "\n".join(lines), sections


# -- styling the rendered guide --------------------------------------------------------

_HEADING_STYLE = {
    1: (24, TEXT, 4, 10),
    2: (18, ACCENT_HOVER, 26, 8),
    3: (15, "#dbe4f3", 18, 6),
    4: (14, TEXT, 12, 4),
}
# Callouts: (background, border) for tips and for notes/warnings.
_TIP = (QColor("#15243a"), QColor("#274774"))
_NOTE = (QColor("#2c2312"), QColor("#6b5222"))
_CODE_BG = QColor("#1b2638")
_CODE_FG = QColor("#9cc3f5")


def _style_document(doc: QTextDocument) -> None:
    """Give the plain Markdown rendering the app's look: headings, callouts, code, tables."""
    # A "|" inside a table cell has to be written "\|"; Qt keeps the backslash in code.
    escaped_pipe = "\\|"
    cursor = doc.find(escaped_pipe)
    while not cursor.isNull():
        cursor.insertText("|", cursor.charFormat())
        cursor = doc.find(escaped_pipe, cursor)
    callouts: list[tuple[int, int, bool]] = []  # (first position, last position, is a note)
    block = doc.begin()
    while block.isValid():
        fmt = block.blockFormat()
        level = fmt.headingLevel()
        cursor = QTextCursor(block)
        if level:
            size, color, top, bottom = _HEADING_STYLE.get(level, _HEADING_STYLE[4])
            fmt.setTopMargin(top)
            fmt.setBottomMargin(bottom)
            cursor.setBlockFormat(fmt)
            char = QTextCharFormat()
            char.setFontPointSize(size * 0.75)
            char.setFontWeight(QFont.Weight.Bold)
            char.setForeground(QColor(color))
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.mergeCharFormat(char)
        elif fmt.intProperty(QTextFormat.Property.BlockQuoteLevel) > 0:
            # Tips and notes: a padded, tinted box (framed below) instead of an indented quote.
            fmt.setLeftMargin(0)
            fmt.setRightMargin(0)
            fmt.setTopMargin(0)
            fmt.setBottomMargin(0)
            fmt.setIndent(0)
            fmt.setTextIndent(0)
            fmt.setLineHeight(118, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            cursor.setBlockFormat(fmt)
            end = block.position() + block.length() - 1
            if callouts and callouts[-1][1] == block.position() - 1:  # the same quote goes on
                callouts[-1] = (callouts[-1][0], end, callouts[-1][2])
            else:
                callouts.append((block.position(), end, block.text().lstrip().startswith("⚠")))
        else:
            fmt.setLineHeight(118, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            fmt.setBottomMargin(max(fmt.bottomMargin(), 6))
            cursor.setBlockFormat(fmt)
        _style_code(block)
        block = block.next()
    _style_tables(doc.rootFrame())
    # Last, from the end, so the positions collected above stay valid.
    for start, end, note in reversed(callouts):
        background, border = _NOTE if note else _TIP
        frame = QTextFrameFormat()
        frame.setBackground(QBrush(background))
        frame.setBorder(1)
        frame.setBorderBrush(QBrush(border))
        frame.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        frame.setPadding(12)
        frame.setTopMargin(6)  # with a paragraph's 6, the usual 12 between blocks
        frame.setBottomMargin(6)
        cursor = QTextCursor(doc)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        box = cursor.insertFrame(frame)  # moves the selected quote inside the new frame
        # Qt keeps an empty paragraph on each side of a frame; fold them away so the box
        # sits at the same distance from the text as everything else.
        for position in (box.firstPosition() - 1, box.lastPosition() + 1):
            around = doc.findBlock(position)
            if around.isValid() and not around.text():
                _collapse(around)


def _collapse(block: object) -> None:
    cursor = QTextCursor(block)  # type: ignore[call-overload]
    fmt = QTextBlockFormat()
    fmt.setTopMargin(0)
    fmt.setBottomMargin(0)
    fmt.setLineHeight(0, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
    cursor.setBlockFormat(fmt)
    tiny = QTextCharFormat()
    tiny.setFontPointSize(1)
    cursor.setBlockCharFormat(tiny)


def _style_code(block: object) -> None:
    it = block.begin()  # type: ignore[attr-defined]
    while not it.atEnd():
        fragment = it.fragment()
        if fragment.isValid() and fragment.charFormat().fontFixedPitch():
            cursor = QTextCursor(block.document())  # type: ignore[attr-defined]
            cursor.setPosition(fragment.position())
            cursor.setPosition(
                fragment.position() + fragment.length(), QTextCursor.MoveMode.KeepAnchor
            )
            char = QTextCharFormat()
            char.setBackground(_CODE_BG)
            char.setForeground(_CODE_FG)
            char.setFontFamilies(["Consolas", "Cascadia Mono", "monospace"])
            cursor.mergeCharFormat(char)
        it += 1


def _style_tables(frame: QTextFrame) -> None:
    for child in frame.childFrames():
        if isinstance(child, QTextTable):
            fmt = QTextTableFormat(child.format())
            fmt.setBorder(1)
            fmt.setBorderBrush(QBrush(QColor(BORDER)))
            fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
            fmt.setBorderCollapse(True)
            fmt.setCellPadding(6)
            fmt.setCellSpacing(0)
            fmt.setTopMargin(6)
            fmt.setBottomMargin(10)
            fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
            child.setFormat(fmt)
            for column in range(child.columns()):
                cell = child.cellAt(0, column)
                cell_fmt = cell.format()
                cell_fmt.setBackground(QColor(CARD_BG))
                cell_fmt.setFontWeight(QFont.Weight.Bold)
                cell_fmt.setForeground(QColor(TEXT_MUTED))
                cell.setFormat(cell_fmt)
        _style_tables(child)


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, anchor: str | None = None) -> None:
        """``anchor`` opens the guide at that section (e.g. "placeholders")."""
        super().__init__(parent)
        self.setWindowTitle(f"{about.NAME} — Help")
        self.resize(1100, 800)
        self.setMinimumSize(720, 480)
        markdown, self.sections = load_guide()

        self.browser = QTextBrowser()
        self.browser.setObjectName("helpBrowser")
        self.browser.setOpenLinks(False)  # section links are handled here; web links open
        self.browser.anchorClicked.connect(self._on_link)
        # Long paths and tokens wrap too, so the guide never scrolls sideways.
        self.browser.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.browser.setMarkdown(markdown)
        doc = self.browser.document()
        doc.setDocumentMargin(24)
        _style_document(doc)
        self._positions = self._heading_blocks()

        # Left: search and the section list.
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the guide…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        self.search.returnPressed.connect(self._next_match)
        self.matches = QLabel("")
        self.matches.setObjectName("helpMatches")
        self.matches.setProperty("muted", True)
        self.matches.setVisible(False)  # only while searching
        self.matches.setWordWrap(True)
        self.toc = QListWidget()
        self.toc.setObjectName("helpToc")
        self.toc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.toc.setTextElideMode(Qt.TextElideMode.ElideRight)
        for section in self.sections:
            item = QListWidgetItem(section.title)
            item.setData(0x0100, section.id)
            item.setToolTip(section.title)
            if section.level >= 3:
                item.setText("    " + section.title)
                item.setForeground(QColor(TEXT_MUTED))
            self.toc.addItem(item)
        self.toc.itemClicked.connect(lambda item: self.go_to(str(item.data(0x0100))))
        side = QWidget()
        side.setMinimumWidth(190)
        side_col = QVBoxLayout(side)
        side_col.setContentsMargins(0, 0, 0, 0)
        side_col.setSpacing(8)
        side_col.addWidget(self.search)
        side_col.addWidget(self.matches)
        side_col.addWidget(self.toc, 1)
        side_col.addStretch(0)  # holds the space when nothing matches and the list hides

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        splitter.addWidget(side)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 850])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda *_: self.accept())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(splitter, 1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

        scroll = self.browser.verticalScrollBar()
        if scroll is not None:
            scroll.valueChanged.connect(self._follow_scroll)
        restore_geometry(self, "help")
        if anchor:
            # After the first layout pass — before it the section has no position yet.
            QTimer.singleShot(0, lambda: self.go_to(anchor))

    # -- navigation --

    def _heading_blocks(self) -> dict[str, int]:
        """Section id -> block number of its heading in the rendered guide."""
        wanted = list(self.sections)
        found: dict[str, int] = {}
        block = self.browser.document().begin()
        while block.isValid() and wanted:
            if block.blockFormat().headingLevel() and block.text().strip() == wanted[0].title:
                found[wanted.pop(0).id] = block.blockNumber()
            block = block.next()
        return found

    def section_top(self, section_id: str) -> int | None:
        number = self._positions.get(section_id)
        if number is None:
            return None
        doc = self.browser.document()
        block = doc.findBlockByNumber(number)
        layout = doc.documentLayout()
        return int(layout.blockBoundingRect(block).top()) if layout is not None else None

    def go_to(self, section_id: str) -> None:
        top = self.section_top(section_id)
        scroll = self.browser.verticalScrollBar()
        if top is None or scroll is None:
            return
        scroll.setValue(max(0, top - 8))
        self._select_toc(section_id)

    def _select_toc(self, section_id: str) -> None:
        self.toc.blockSignals(True)
        try:
            for i in range(self.toc.count()):
                item = self.toc.item(i)
                if item is not None and item.data(0x0100) == section_id:
                    self.toc.setCurrentRow(i)
                    break
        finally:
            self.toc.blockSignals(False)

    def current_section(self) -> str | None:
        scroll = self.browser.verticalScrollBar()
        position = (scroll.value() if scroll is not None else 0) + 24
        current = None
        for section in self.sections:
            top = self.section_top(section.id)
            if top is not None and top <= position:
                current = section.id
        return current

    def _follow_scroll(self, *_: object) -> None:
        if self.search.text().strip():
            return  # the list shows search results then
        section = self.current_section()
        if section:
            self._select_toc(section)

    def _on_link(self, url: QUrl) -> None:
        target = url.toString()
        if target.startswith("#"):
            self.go_to(target[1:])
        else:
            QDesktopServices.openUrl(url)

    # -- search --

    def _section_text(self, section_id: str) -> str:
        numbers = sorted(self._positions.values())
        start = self._positions.get(section_id)
        if start is None:
            return ""
        end = next((n for n in numbers if n > start), None)
        doc = self.browser.document()
        parts = []
        block = doc.findBlockByNumber(start)
        while block.isValid() and (end is None or block.blockNumber() < end):
            parts.append(block.text())
            block = block.next()
        return "\n".join(parts)

    def _on_search(self, text: str) -> None:
        needle = text.strip()
        selections: list[QTextEdit.ExtraSelection] = []
        if needle:
            doc = self.browser.document()
            cursor = doc.find(needle)
            while not cursor.isNull() and len(selections) < 500:
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor  # type: ignore[attr-defined]
                selection.format.setBackground(QColor("#5c4a12"))  # type: ignore[attr-defined]
                selection.format.setForeground(QColor("#fff7d6"))  # type: ignore[attr-defined]
                selections.append(selection)
                cursor = doc.find(needle, cursor)
        self.browser.setExtraSelections(selections)
        lowered = needle.casefold()
        for i in range(self.toc.count()):
            item = self.toc.item(i)
            if item is None:
                continue
            section_id = str(item.data(0x0100))
            item.setHidden(
                bool(lowered) and lowered not in self._section_text(section_id).casefold()
            )
        count = len(selections)
        self.matches.setVisible(bool(needle))
        self.toc.setVisible(not needle or count > 0)
        if needle and count:
            self.matches.setText(f"{count} match{'es' if count != 1 else ''} — Enter for the next")
            self._next_match()
        else:
            self.matches.setText(f"Nothing in the guide matches “{needle}”." if needle else "")
            cursor = self.browser.textCursor()
            cursor.clearSelection()  # no stale highlight from an earlier search
            self.browser.setTextCursor(cursor)

    def _next_match(self) -> None:
        needle = self.search.text().strip()
        if not needle:
            return
        doc = self.browser.document()
        found = doc.find(needle, self.browser.textCursor())
        if found.isNull():
            found = doc.find(needle)  # wrap around
        if not found.isNull():
            self.browser.setTextCursor(found)
            self.browser.ensureCursorVisible()

    def done(self, result: int) -> None:
        if self.isVisible():
            save_geometry(self, "help")
        super().done(result)

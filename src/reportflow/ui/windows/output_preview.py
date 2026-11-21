"""The Output tab's "Each run creates" card: every file a run makes, where it goes, and
whether it is emailed — instead of one long line of file names (0.13 showed
"→ (input file's folder)\\…xlsx · email: …_email.xlsx, …_<sheet>.pdf — one per workbook (8)").

:func:`plan_outputs` is the pure part (the same naming rules the service uses: the
``{workbook}`` suffix for several workbooks, ``_email.xlsx`` for the attachment copy,
``_<sheet>.pdf`` per sheet or one ``.pdf`` combined); :class:`OutputPreview` only shows it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from reportflow.core.output_names import (
    DEFAULT_OUTPUT_STEM,
    expand_output_name,
    overwrites_same_day,
)
from reportflow.ui.assets import asset_icon
from reportflow.ui.kit import ComboBox, ElidedLabel, Tag
from reportflow.ui.widgets import section_title


@dataclass(frozen=True)
class OutputPlan:
    """What one run creates for one workbook (``workbook``), and how many sets there are."""

    folder: str  # where the files go; "" = next to each workbook
    workbook_folder: str  # the shown workbook's own folder ("" when there is none)
    stem: str
    excel_attachment: bool
    pdf: str  # "none" | "combined" | "per_sheet"
    pdf_sheets: tuple[str, ...]
    workbook: str
    workbook_count: int
    overwrites: bool

    def files(self) -> list[tuple[str, str, str]]:
        """``(what, file name, where it goes)`` rows, in the order the card shows them."""
        rows = [("Full copy", f"{self.stem}.xlsx", "kept on disk")]
        if self.excel_attachment:
            rows.append(("Excel attachment", f"{self.stem}_email.xlsx", "emailed"))
        if self.pdf == "combined":
            rows.append(("PDF", f"{self.stem}.pdf", "emailed"))
        elif self.pdf == "per_sheet":
            count = len(self.pdf_sheets)
            rows.append((f"PDFs ({count})", f"{self.stem}_<sheet>.pdf", "emailed"))
        return rows


def plan_outputs(
    *,
    pattern: str,
    job_name: str,
    output_dir: str,
    workbook_path: str,
    included: list[tuple[str, bool, bool]],  # (sheet, excel attachment, pdf) of included sheets
    combined_pdf: bool,
    workbook_count: int,
    now: datetime | None = None,
) -> OutputPlan:
    pattern = pattern.strip() or DEFAULT_OUTPUT_STEM
    if workbook_count > 1 and "{workbook}" not in pattern:
        pattern += "_{workbook}"  # mirrors the launcher: several outputs need distinct names
    stem = expand_output_name(
        pattern,
        job_name=job_name.strip() or "job",
        run_id="a1b2c3",
        now=now or datetime.now(),
        workbook=Path(workbook_path).stem if workbook_path else "workbook",
    )
    pdf_sheets = tuple(name for name, _excel, pdf in included if pdf)
    return OutputPlan(
        folder=output_dir.strip(),
        workbook_folder=str(Path(workbook_path).parent) if workbook_path else "",
        stem=stem,
        excel_attachment=any(excel for _name, excel, _pdf in included),
        pdf="none" if not pdf_sheets else "combined" if combined_pdf else "per_sheet",
        pdf_sheets=pdf_sheets,
        workbook=Path(workbook_path).name if workbook_path else "",
        workbook_count=workbook_count,
        overwrites=overwrites_same_day(pattern),
    )


_ICONS = {"Full copy": "workbook.svg", "Excel attachment": "mail.svg"}


class _FileRow:
    """One line of the card: icon, what it is, the (shortened) name, a tag."""

    def __init__(self, grid: QGridLayout, row: int) -> None:
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        self.what = QLabel()
        self.what.setProperty("muted", True)
        self.name = ElidedLabel(max_hint=520)
        self.tag = Tag("", kind="neutral")
        grid.addWidget(self.icon, row, 0, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.what, row, 1)
        grid.addWidget(self.name, row, 2)
        grid.addWidget(self.tag, row, 3, Qt.AlignmentFlag.AlignRight)

    def show(self, icon: str, what: str, name: str, tag: str, *, tip: str = "") -> None:
        self.icon.setPixmap(asset_icon(icon).pixmap(16, 16))
        self.what.setText(what)
        self.name.setText(name)
        self.name.setToolTip(tip or name)
        self.tag.setText(tag)
        self.tag.set_kind("info" if tag == "emailed" else "neutral")
        self.set_visible(True)
        # After set_visible: an empty tag showed as a small empty pill ("Saved in" has none).
        self.tag.setVisible(bool(tag))

    def set_visible(self, visible: bool) -> None:
        for widget in (self.icon, self.what, self.name, self.tag):
            widget.setVisible(visible)


class OutputPreview(QFrame):
    """The "Each run creates" card. ``workbook_changed`` asks the editor for that one."""

    workbook_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(section_title("Each run creates"))
        self.workbook = ComboBox(min_chars=24)
        self.workbook.setToolTip("Show the files for another workbook of this job.")
        self.workbook.currentIndexChanged.connect(self._on_workbook)
        head.addWidget(self.workbook)
        self.sets = QLabel()
        self.sets.setProperty("muted", True)
        head.addWidget(self.sets)
        head.addStretch(1)
        outer.addLayout(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(2, 1)
        self.folder = _FileRow(grid, 0)
        self.rows = [_FileRow(grid, i) for i in range(1, 4)]
        outer.addLayout(grid)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setProperty("muted", True)
        outer.addWidget(self.note)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setProperty("tone", "warning")
        outer.addWidget(self.warning)
        self._syncing = False
        self._plan: OutputPlan | None = None

    # -- workbooks --

    def set_workbooks(self, labels: list[str], selected: int) -> None:
        self._syncing = True
        try:
            if [self.workbook.itemText(i) for i in range(self.workbook.count())] != labels:
                self.workbook.clear()
                self.workbook.addItems(labels)
            self.workbook.setCurrentIndex(max(0, min(selected, len(labels) - 1)))
        finally:
            self._syncing = False
        self.workbook.setVisible(len(labels) > 1)

    def selected(self) -> int:
        return self.workbook.currentIndex()

    def _on_workbook(self, index: int) -> None:
        if not self._syncing and index >= 0:
            self.workbook_changed.emit(index)

    # -- the plan --

    def show_plan(self, plan: OutputPlan) -> None:
        self._plan = plan
        many = plan.workbook_count > 1
        self.sets.setText(f"· one set per workbook ({plan.workbook_count})" if many else "")
        if plan.folder:
            self.folder.show("folder.svg", "Saved in", plan.folder, "")
        elif plan.workbook_folder:
            self.folder.show(
                "folder.svg",
                "Saved in",
                plan.workbook_folder,
                "next to the workbook",
                tip=f"{plan.workbook_folder}\n(no output folder set: next to the workbook)",
            )
        else:
            self.folder.show("folder.svg", "Saved in", "Next to each workbook", "")
        files = plan.files()
        for row, (what, name, where) in zip(self.rows, files, strict=False):
            icon = "pdf.svg" if what.startswith("PDF") else _ICONS.get(what, "workbook.svg")
            tip = name
            if what.startswith("PDFs"):
                tip = "One PDF per sheet: " + ", ".join(plan.pdf_sheets)
            row.show(icon, what, name, where, tip=tip)
        for row in self.rows[len(files) :]:
            row.set_visible(False)
        emailed = plan.excel_attachment or plan.pdf != "none"
        self.note.setText(
            ""
            if emailed
            else "Nothing is attached to the email yet — tick Excel attachment or PDF for a "
            "sheet on the General tab."
        )
        self.note.setVisible(not emailed)
        self.warning.setText(
            "⚠ A second run on the same day overwrites the first — add {time} to the name."
            if plan.overwrites
            else ""
        )
        self.warning.setVisible(plan.overwrites)

    def text(self) -> str:
        """Everything the card says, as plain text (for tests and screen readers)."""
        if self._plan is None:
            return ""
        lines = [f"Saved in: {self._plan.folder or self._plan.workbook_folder}"]
        lines += [f"{what}: {name} ({where})" for what, name, where in self._plan.files()]
        if self.sets.text():
            lines.append(self.sets.text())
        if self.warning.text():
            lines.append(self.warning.text())
        return "\n".join(lines)

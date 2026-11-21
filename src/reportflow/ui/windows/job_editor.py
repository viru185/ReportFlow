"""Job editor dialog — compact tabs (General / Output / Schedule / Email / Advanced).

Each tab is focused and scrolls on smaller screens. Non-mandatory settings are optional.
A job has one or more workbooks (a list on the General tab, the selected one's sheets beside
it; sheet names are read in the background), and each included sheet has its own PDF /
Hidden choice. Outputs are a folder + optional filename stem; the schedule
is built visually; the email body is authored in-app via EmailTemplateDialog.
"""

from __future__ import annotations

import itertools
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from reportflow.core.config.models import migrate_legacy_job
from reportflow.core.email.render import explain_template_error, template_error
from reportflow.core.output_names import (
    DEFAULT_OUTPUT_STEM,
    OUTPUT_NAME_TOKENS,
)
from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.assets import asset_icon
from reportflow.ui.feedback import (
    FormDialog,
    InlineNotice,
    clear_field_error,
    mark_tab_errors,
    set_field_error,
    show_help,
    toast,
)
from reportflow.ui.fs_util import open_start_dir
from reportflow.ui.group_editor import EmailGroupDialog
from reportflow.ui.kit import (
    Button,
    ComboBox,
    ElidedLabel,
    PathLabel,
    SpinBox,
    TableWidget,
    breakable,
    set_variant,
    styled_completer,
)
from reportflow.ui.placeholder_picker import (
    PlaceholderButton,
    email_placeholders,
    output_name_placeholders,
)
from reportflow.ui.recipient_field import RecipientField, RecipientSet, header_recipients
from reportflow.ui.sheet_loader import PoolExecutor, SheetLoader, SheetOutcome
from reportflow.ui.style import WARNING
from reportflow.ui.suggestions import (
    concurrency_groups,
    email_groups,
    field_entries,
    known_addresses,
)
from reportflow.ui.widgets import CenteredCheckDelegate, scroll_page, section_title, space_layout
from reportflow.ui.windows.email_template_dialog import EmailTemplateDialog
from reportflow.ui.windows.output_preview import OutputPreview, plan_outputs
from reportflow.ui.windows.schedule_widget import ScheduleWidget
from reportflow.ui.windows.workbook_panel import (
    DropOverlay,
    EmptyDropZone,
    FileDropFilter,
    RowView,
    WorkbookList,
    is_excel_path,
)

# Sheet table columns.
_COL_NAME, _COL_INCLUDE, _COL_EXCEL, _COL_PDF, _COL_HIDDEN = range(5)
# The tick columns: short titles, so all four share one narrow width and the ticks sit at even
# gaps. Each sized to its own title ("Excel attachment" 117 px, "PDF" 43 px at 150 %) they
# drifted; the full meaning is in each title's tooltip.
_CHECK_COLUMNS = {
    _COL_INCLUDE: ("Include", "The sheet is refreshed, checked and frozen."),
    _COL_EXCEL: ("Excel", "The sheet is in the emailed Excel attachment."),
    _COL_PDF: ("PDF", "The sheet is exported to the emailed PDF."),
    _COL_HIDDEN: ("Hidden", "Kept in the Excel attachment but hidden (recipients can unhide it)."),
}

# What the output copy does with the sheets that are NOT included (stored per workbook).
_UNSELECTED_MODES = [
    ("Remove them from the file", "remove"),
    ("Keep them, hidden", "hide"),
    ("Keep them, visible", "keep"),
]


_UIDS = itertools.count(1)
_REREAD_SECONDS = 5.0  # selecting a workbook or returning to the window re-reads at most this often
_STACK_BELOW = 720  # px: narrower than this, the workbook list sits above the sheets
_LIST_MIN = 220  # px: the workbook list is never narrower than this side by side


def merge_sheets(rows: list[_SheetRow], names: list[str], *, tick_all: bool) -> list[_SheetRow]:
    """The workbook's sheets (in its order) with the job's choices kept.

    New sheets come in unticked — or all ticked for a workbook just added (``tick_all``)
    that has nothing ticked yet. An included sheet the workbook no longer has stays, marked
    ``missing`` where it was, instead of silently disappearing from the job.
    """
    known = {row.name: row for row in rows}
    include_new = tick_all and not any(row.include for row in rows)
    present = set(names)
    merged = [
        replace(known[name], missing=False) if name in known else _SheetRow(name, include_new)
        for name in names
    ]
    for i, row in enumerate(rows):
        if row.name in present or not row.include:
            continue
        position = 0
        for before in reversed(rows[:i]):
            at = next((k for k, r in enumerate(merged) if r.name == before.name), None)
            if at is not None:
                position = at + 1
                break
        merged.insert(position, replace(row, missing=True))
    return merged


@dataclass
class _Problem:
    """Something that stops Save: where it is, and what to do about it."""

    tab: int
    message: str
    widget: QWidget | None = None
    workbook: int | None = None
    help: str | None = None  # the Help section its "Learn more" link opens


_TAB_GENERAL, _TAB_OUTPUT, _TAB_SCHEDULE, _TAB_EMAIL, _TAB_ADVANCED = range(5)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _split_csv(text: str) -> list[str]:
    return [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]


def _same_file_key(path: str) -> str:
    """One spelling per file: C:/Reports/a.xlsx and c:\\reports\\A.xlsx are the same file."""
    return os.path.normcase(os.path.normpath(os.path.abspath(path.strip())))


def _join_csv(items: list[str] | None) -> str:
    return ", ".join(items or [])


@dataclass
class _SheetRow:
    name: str
    include: bool
    excel: bool = True
    pdf: bool = True
    hidden: bool = False
    missing: bool = False  # included, but the workbook no longer has it


@dataclass
class _WorkbookState:
    """The editor's copy of one workbook; the widgets show the current one."""

    path: str = ""
    rows: list[_SheetRow] = field(default_factory=list)
    unselected: str = "remove"
    pdf_mode: str = "separate"
    uid: int = field(default_factory=lambda: next(_UIDS))
    fresh: bool = False  # added in this editor: its first read ticks every sheet
    read: str = "unread"  # last answer: unread / ok / missing / unreadable / offline
    reading: bool = False
    error: str = ""
    total: int | None = None  # sheets in the file, once read
    last_read: float = 0.0

    @property
    def label(self) -> str:
        return Path(self.path).name if self.path else "New workbook"


class JobEditorDialog(FormDialog):
    def __init__(
        self,
        api: ApiClient,
        job: dict[str, Any] | None = None,
        parent: QWidget | None = None,
        *,
        prefill: dict[str, Any] | None = None,
        prefill_template: str | None = None,
        prefill_template_link: str | None = None,
        save_handler: Callable[[JobEditorDialog], str | None] | None = None,
    ) -> None:
        """``job`` opens EDIT mode; ``prefill`` opens CREATE mode seeded from an existing
        job (Duplicate): everything copied except the name (fresh) and the stage (back to
        Testing). ``prefill_template`` is the source job's email template content — the copy
        gets its own file with the same content; ``prefill_template_link`` instead means the
        source is linked to a file of the user's, and the copy links to the same file.
        ``save_handler(dialog)`` stores the job and returns an error to show, or None —
        so a save the service refuses keeps the editor open with its edits."""
        super().__init__(parent, settings_key="job_editor")
        self._save_handler = save_handler
        self._problem_widgets: list[QWidget] = []
        self._showing_problems = False
        self._api = api
        self._editing = job is not None
        self._template_html: str | None = None  # authored in-app; caller saves it after job save
        self._existing_template_path: str | None = None
        # A template file of the user's that the job stays linked to (re-read every run).
        self._template_link: str | None = None
        self._workbooks: list[_WorkbookState] = []
        self._loaded_timeout_seconds: int | None = None
        self._original_name: str | None = None  # EDIT mode: the name the job is stored under
        self._current_wb: int | None = None
        self._syncing = False  # guards widget signals while the editor fills widgets itself
        self.setWindowTitle("Edit Job" if self._editing else "New Job")
        self.resize(900, 680)
        # One config snapshot feeds the defaults and every autocomplete list.
        self._config = self._fetch_config()
        self._email_groups = email_groups(self._config)
        self._loader = self._make_loader()
        self._reactivated = QTimer(self)
        self._reactivated.setSingleShot(True)
        self._reactivated.setInterval(250)
        self._reactivated.timeout.connect(self._on_reactivated)
        self._recheck = QTimer(self)  # after a refused save, problems clear as fixed
        self._recheck.setSingleShot(True)
        self._recheck.setInterval(300)
        self._recheck.timeout.connect(self._refresh_problems)
        self._build()
        if job:
            self._load(job)
        elif prefill:
            self._load(prefill)
            self._apply_duplicate_mode(
                prefill.get("name", ""), prefill_template, prefill_template_link
            )
        self._update_output_example()
        # The sheet lists are read now, in the background — always current, never a button.
        for wb in self._workbooks:
            self._request_read(wb, force=True)
        self.finish_form(self._save_button_widget)

    def _apply_duplicate_mode(
        self, source: str, template: str | None, template_link: str | None = None
    ) -> None:
        """Duplicating is CREATE, not EDIT: everything is copied except the name (fresh)
        and the stage (a new job verifies in Testing first, like any other)."""
        self.setWindowTitle(f"New Job (duplicate of {source})" if source else "New Job")
        self.name.clear()
        self.name.setFocus()
        self.stage.setCurrentIndex(self.stage.findData("testing"))
        self.stage.setEnabled(False)  # like any new job: promote from the card after a run
        # The job's OWN template file is never shared — two jobs editing one file would
        # cross-wire — but its content is copied and saved as the new job's own template.
        # A linked file of the user's is shared on purpose: both jobs follow its edits.
        self._existing_template_path = None
        if template_link:
            self._template_link = template_link
            self.template_status.setText(f"Linked to {Path(template_link).name}, like {source}.")
        elif template and template.strip():
            self._template_html = template
            self.template_status.setText(f"Template copied from {source}.")
        else:
            self.template_status.setText("Using the default template (as the original).")

    # -- construction ------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        # ---- General tab ----
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        input_form = QFormLayout()
        general_layout.addLayout(input_form)
        self.name = QLineEdit()
        self.name.setToolTip(
            "A unique name for this job; it is also used in output filenames. Renaming keeps "
            "the job's run history and email template."
        )
        self.name.textChanged.connect(self._update_output_example)
        self.name.textChanged.connect(self._recheck_soon)
        self.enabled = QCheckBox("Run on schedule")
        self.enabled.setChecked(True)
        self.enabled.setToolTip("Untick to keep the job configured but never run it on schedule.")
        name_row = QHBoxLayout()
        name_row.addWidget(self.name)
        name_row.addWidget(self.enabled)
        self.name.setAcceptDrops(False)  # a dropped file goes to the workbook list instead
        # The job's workbooks: a list on the left, the selected one's sheets on the right.
        self.wb_list = WorkbookList()
        self.wb_list.setMinimumWidth(_LIST_MIN)
        self.wb_list.current_changed.connect(self._on_workbook_selected)
        self.wb_list.add_requested.connect(self._pick_workbooks)
        self.wb_list.replace_requested.connect(self._replace_workbook)
        self.wb_list.remove_requested.connect(self._remove_workbook)
        self.wb_list.moved.connect(self.move_workbook)
        # The selected workbook: its name with Replace / Remove beside it, and its folder.
        # Both are shortened in the middle (full text on hover) — a long path or name never
        # makes the page wider than the window.
        self.wb_title = ElidedLabel(max_hint=480)
        self.wb_title.setObjectName("workbookTitle")
        self.wb_path = PathLabel()
        self.wb_path.label.setObjectName("workbookPath")
        self.wb_replace = Button(
            "Replace…",
            icon=asset_icon("replace.svg"),
            tooltip="Use another file for this workbook — its sheet choices are kept.",
        )
        self.wb_replace.clicked.connect(
            lambda: self._replace_workbook(self._current_wb if self._current_wb is not None else -1)
        )
        self.wb_remove = Button(
            "Remove",
            variant="danger",
            icon=asset_icon("trash.svg"),
            tooltip="Remove this workbook from the job (Undo is offered).",
        )
        self.wb_remove.clicked.connect(
            lambda: self._remove_workbook(self._current_wb if self._current_wb is not None else -1)
        )
        # Why the sheets can't be shown fresh right now (file missing, unreadable, ...).
        self.wb_banner = QFrame()
        self.wb_banner.setObjectName("workbookBanner")
        self.wb_banner.setProperty("banner", "warning")
        banner_row = QHBoxLayout(self.wb_banner)
        banner_row.setContentsMargins(12, 8, 8, 8)
        banner_row.setSpacing(8)
        self.wb_banner_text = QLabel()
        self.wb_banner_text.setWordWrap(True)
        banner_row.addWidget(self.wb_banner_text, 1)
        self.wb_banner_replace = Button("Replace…")
        self.wb_banner_replace.clicked.connect(
            lambda: self._replace_workbook(self._current_wb if self._current_wb is not None else -1)
        )
        self.wb_banner_retry = Button("Try again")
        self.wb_banner_retry.clicked.connect(self._retry_current)
        banner_row.addWidget(self.wb_banner_replace)
        banner_row.addWidget(self.wb_banner_retry)
        self.wb_banner.hide()
        self.sheets = TableWidget(0, 5)
        self.sheets.setHorizontalHeaderLabels(
            ["Sheet", *(title for title, _tip in _CHECK_COLUMNS.values())]
        )
        name_header = self.sheets.horizontalHeaderItem(_COL_NAME)
        if name_header is not None:  # over the names it heads, not centred in the gap
            name_header.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col, (_title, tip) in _CHECK_COLUMNS.items():
            column_header = self.sheets.horizontalHeaderItem(col)
            if column_header is not None:
                column_header.setToolTip(f"{tip}\nClick to tick or untick it for every sheet.")
        self.sheets.verticalHeader().setVisible(False)
        self.sheets.verticalHeader().setDefaultSectionSize(34)
        self.sheets.setTabKeyNavigation(True)
        # One line per sheet: a long name is shortened ("Monthly Energy Report — Sm…"), with
        # the full name on hover, instead of wrapping into a cramped two-line row.
        self.sheets.setWordWrap(False)
        self.sheets.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sheets.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.sheets.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.sheets.horizontalHeader()
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        # One width for every tick column: the widest title's (the ticks are centred in it).
        check_width = max(header.sectionSizeHint(col) for col in _CHECK_COLUMNS)
        for col in _CHECK_COLUMNS:
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(col, check_width)
            self.sheets.setItemDelegateForColumn(col, CenteredCheckDelegate(self.sheets))
        header.setToolTip("Click a column title to tick or untick the whole column.")
        header.sectionClicked.connect(self._toggle_column)
        self.sheets.itemChanged.connect(self._on_sheet_item_changed)
        self.sheets.setToolTip(
            "\n".join(f"{title}: {tip}" for title, tip in _CHECK_COLUMNS.values())
        )
        sheets_hint = QLabel(
            "Include sheets to process, then choose their Excel and PDF attachments. "
            "A full Excel copy is saved locally. Click a column heading to select all."
        )
        sheets_hint.setProperty("muted", True)
        sheets_hint.setWordWrap(True)
        # What the output copy does with the sheets you did NOT include. One choice covers
        # "keep or remove" and "if kept, hidden or visible".
        self.nonselected_mode = ComboBox()
        for label, key in _UNSELECTED_MODES:
            self.nonselected_mode.addItem(label, key)
        self.nonselected_mode.currentIndexChanged.connect(lambda *_: self._store_current())
        self.nonselected_mode.setToolTip(
            "What the OUTPUT copy does with the sheets you did not include (the source is "
            "never modified):\n"
            "• Remove — delete them for a smaller file (can break charts/defined names that "
            "referenced them, so Office may refuse to open the output).\n"
            "• Keep, hidden — keep every sheet but make the extra ones very-hidden; "
            "references stay intact and the file always opens, but the raw data stays "
            "inside it.\n"
            "• Keep, visible — leave every sheet as it is."
        )
        self.combine_pdf = QCheckBox("Combine selected sheets into one PDF")
        self.combine_pdf.setToolTip("One PDF for this workbook, in the listed sheet order.")
        self.combine_pdf.toggled.connect(lambda *_: self._store_current())
        self.combine_pdf.toggled.connect(self._update_output_example)
        input_form.addRow("Job name", name_row)
        details = QWidget()
        details_col = QVBoxLayout(details)
        details_col.setContentsMargins(0, 0, 0, 0)
        details_col.setSpacing(8)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(self.wb_title, 1)
        title_row.addWidget(self.wb_replace)
        title_row.addWidget(self.wb_remove)
        details_col.addLayout(title_row)
        details_col.addWidget(self.wb_path)
        details_col.addWidget(self.wb_banner)
        details_col.addSpacing(4)
        details_col.addWidget(section_title("Sheets and email attachments"))
        details_col.addWidget(self.sheets)
        details_col.addWidget(sheets_hint)
        options_form = QFormLayout()
        options_form.addRow("Other local sheets", self.nonselected_mode)
        options_form.addRow("PDF output", self.combine_pdf)
        space_layout(options_form, margin=0)
        details_col.addLayout(options_form)
        details_col.addStretch(1)
        self.wb_split = QSplitter(Qt.Orientation.Horizontal)
        self.wb_split.setChildrenCollapsible(False)
        self.wb_split.setHandleWidth(16)
        self.wb_split.addWidget(self.wb_list)
        self.wb_split.addWidget(details)
        self.wb_split.setStretchFactor(0, 0)
        self.wb_split.setStretchFactor(1, 1)
        self.wb_split.setSizes([300, 600])
        self.empty_zone = EmptyDropZone()
        self.empty_zone.add_requested.connect(self._pick_workbooks)
        self.wb_stack = QStackedWidget()
        self.wb_stack.addWidget(self.empty_zone)
        self.wb_stack.addWidget(self.wb_split)
        workbook_box = QGroupBox("Workbooks")
        workbook_layout = QVBoxLayout(workbook_box)
        workbook_layout.addWidget(self.wb_stack)
        space_layout(workbook_layout)
        general_layout.addWidget(workbook_box, 1)
        self.wb_notice = InlineNotice()  # why the workbooks can't be saved yet
        general_layout.addWidget(self.wb_notice)
        # ---- Output tab ----
        output_tab = QWidget()
        output_form = QFormLayout(output_tab)
        self._output_form = output_form
        output_form.addRow(section_title("Report files"))
        self.output_dir = QLineEdit()
        self.output_dir.setPlaceholderText("(same folder as the input file)")
        self.output_dir.setToolTip(
            "Folder where the output Excel and PDFs are saved. Leave empty to save next to "
            "the input file."
        )
        self.output_dir.textChanged.connect(self._update_output_example)
        browse_dir = Button("Browse…")
        browse_dir.clicked.connect(self._pick_output_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.output_dir)
        dir_row.addWidget(browse_dir)
        self.output_name = QLineEdit()
        self.output_name.setPlaceholderText(DEFAULT_OUTPUT_STEM)
        tokens = ", ".join(token for _, token, _ in OUTPUT_NAME_TOKENS)
        self.output_name.setToolTip(
            f"Optional filename (without extension). Placeholders: {tokens} — use Insert "
            f"placeholder to pick one. Leave empty for {DEFAULT_OUTPUT_STEM}."
        )
        self.output_placeholders = PlaceholderButton(
            self.output_name,
            lambda: output_name_placeholders(job_name=self.name.text()),
            field_name="File name",
        )
        output_name_row = QHBoxLayout()
        output_name_row.addWidget(self.output_name, 1)
        output_name_row.addWidget(self.output_placeholders)
        self.output_name.textChanged.connect(self._update_output_example)
        # "Each run creates": every file a run makes, where it goes, and what is emailed.
        self.output_example = OutputPreview()
        self.output_example.workbook_changed.connect(lambda *_: self._update_output_example())
        self.freeze = QCheckBox("Freeze formulas to values")
        self.freeze.setChecked(True)
        self.freeze.setToolTip(
            "Convert formulas to plain values on the included sheets in the output copy, so "
            "recipients see the numbers without needing your data connections."
        )
        # Only meaningful with several workbooks (row hidden otherwise).
        self.on_failure = ComboBox()
        self.on_failure.addItem("Fail the whole run — send nothing", "fail_run")
        self.on_failure.addItem("Send the workbooks that worked (with a warning)", "send_partial")
        self.on_failure.setToolTip(
            "When one of this job's workbooks fails to build: either nothing is emailed "
            "(the safe default), or the email goes out with the workbooks that did work and "
            "the run lists the failed one as a warning."
        )
        output_form.addRow("Output folder", dir_row)
        output_form.addRow("Filename (optional)", output_name_row)
        output_form.addRow("", self.freeze)
        output_form.addRow("If a workbook fails", self.on_failure)
        output_form.addRow(self.output_example)
        # ---- Schedule tab ----
        schedule_tab = QWidget()
        schedule_lay = QVBoxLayout(schedule_tab)
        self.schedule = ScheduleWidget()
        self.schedule.changed.connect(self._recheck_soon)
        schedule_lay.addWidget(self.schedule)
        schedule_lay.addStretch()
        # ---- Email tab ----
        email_tab = QWidget()
        email_form = QFormLayout(email_tab)
        self.subject = QLineEdit()
        self.subject.textChanged.connect(self._recheck_soon)
        self.subject.setPlaceholderText("e.g. Daily production report — {{ today }}")
        self.subject.setToolTip(
            "Email subject; Testing-stage runs are prefixed [TEST]. Placeholders work here "
            "too — e.g. {{ today }}, {{ month }}; Insert placeholder lists them all."
        )
        self.subject_placeholders = PlaceholderButton(
            self.subject, lambda: email_placeholders(subject=True), field_name="Subject"
        )
        subject_row = QHBoxLayout()
        subject_row.addWidget(self.subject, 1)
        subject_row.addWidget(self.subject_placeholders)
        # Lifecycle stage. New jobs always start in Testing (the combo is locked on create —
        # promotion happens from the job card's "Go live" after a verified run); editing a
        # job exposes it so a live job can be moved back to Testing.
        self.stage = ComboBox()
        self.stage.addItem("Testing — every run emails the Test recipients", "testing")
        self.stage.addItem("Production — runs email the Production recipients", "live")
        self.stage.setToolTip(
            "Testing: every run (manual or scheduled) emails only the Test recipients, so "
            "you can verify the report internally. Production: runs email the Production "
            "recipients. Promote from the job card's 'Move to production' button."
        )
        if not self._editing:
            self.stage.setEnabled(False)  # new jobs always start in Testing
        # Addresses and Settings → Email groups, as chips with autocomplete. Each recipient
        # list is one RecipientSet: a person is in it once, directly or through a group.
        self._known_addresses = known_addresses(self._config)
        self.prod_to = self._recipient_field(
            "Production To — required: at least one address or email group."
        )
        self.prod_cc = self._recipient_field("Production Cc — optional.")
        self.prod_bcc = self._recipient_field(
            "Production Bcc — optional (hidden from other recipients)."
        )
        self.test_to = self._recipient_field("Test To — who receives Testing-stage emails.")
        self.test_cc = self._recipient_field("Test Cc — optional.")
        self.test_bcc = self._recipient_field("Test Bcc — optional.")
        self.prod_notice = InlineNotice()
        self.test_notice = InlineNotice()
        self.prod_set = RecipientSet(
            {"To": self.prod_to, "Cc": self.prod_cc, "Bcc": self.prod_bcc},
            groups=self._email_groups,
            addresses=self._known_addresses,
            notice=self.prod_notice,
        )
        self.test_set = RecipientSet(
            {"To": self.test_to, "Cc": self.test_cc, "Bcc": self.test_bcc},
            groups=self._email_groups,
            addresses=self._known_addresses,
            notice=self.test_notice,
        )
        edit_template = Button("Edit email template…")
        edit_template.setToolTip(
            "Author the email body in-app (simple text or HTML) with a live preview."
        )
        edit_template.clicked.connect(self._edit_template)
        self.template_status = QLabel("Using the default template.")
        self.template_status.setProperty("muted", True)
        tpl_row = QHBoxLayout()
        tpl_row.addWidget(edit_template)
        tpl_row.addWidget(self.template_status)
        tpl_row.addStretch()
        email_form.addRow("Subject", subject_row)
        email_form.addRow("Stage", self.stage)
        email_form.addRow(section_title("Production recipients"))
        email_form.addRow("Production: To", self.prod_to)
        email_form.addRow("Production: Cc (optional)", self.prod_cc)
        email_form.addRow("Production: Bcc (optional)", self.prod_bcc)
        email_form.addRow("", self.prod_notice)
        email_form.addRow(section_title("Test recipients"))
        email_form.addRow("Test: To", self.test_to)
        email_form.addRow("Test: Cc (optional)", self.test_cc)
        email_form.addRow("Test: Bcc (optional)", self.test_bcc)
        email_form.addRow("", self.test_notice)
        email_form.addRow(section_title("Email content"))
        email_form.addRow("Body", tpl_row)
        # ---- Advanced tab ----
        advanced_tab = QWidget()
        adv_form = QFormLayout(advanced_tab)
        adv_hint = QLabel("Optional tuning — most jobs don't need these.")
        adv_hint.setProperty("muted", True)
        adv_form.addRow(adv_hint)
        # The two run-time knobs carry an always-visible one-line explanation: users hit a
        # 20+ minute PI report timing out and never found the tooltip that said what to do.
        default_minutes = self._default_timeout_minutes()
        self.timeout = SpinBox()
        self.timeout.setRange(0, 24 * 60)
        self.timeout.setSuffix(" min")
        self.timeout.setSpecialValueText(
            f"Default ({default_minutes} min)" if default_minutes else "Default (from Settings)"
        )
        self.timeout.setToolTip(
            "The longest a run may take, start to finish (all workbooks). When it is "
            "reached the run is stopped and marked Timed out. 0 = the default from "
            "File → Settings."
        )
        timeout_help = self._help_label(
            "Stops the whole run after this long and marks it Timed out. A big report that "
            "pulls a lot of PI data can need 20–60 min — raise this if runs end as Timed out."
        )
        self.group = QLineEdit()
        self.group.setToolTip(
            "Jobs sharing the same group name run one-at-a-time instead of in parallel — "
            "useful when several jobs hit the same slow database. Leave empty for normal "
            "parallel behavior. Groups other jobs already use are suggested as you type."
        )
        # A typo makes a second, separate group — suggest the ones already in use.
        group_completer = QCompleter(concurrency_groups(self._config), self.group)
        group_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        group_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        styled_completer(group_completer)
        self.group.setCompleter(group_completer)
        self.post_refresh_wait = SpinBox()
        self.post_refresh_wait.setRange(0, 3600)
        self.post_refresh_wait.setPrefix("up to ")
        self.post_refresh_wait.setSuffix(" s")
        self.post_refresh_wait.setSpecialValueText("Don't wait")
        self.post_refresh_wait.setValue(10)
        self.post_refresh_wait.setToolTip(
            "Add-ins such as PI DataLink keep filling cells after Excel reports the refresh "
            "as done. ReportFlow keeps checking for up to this long and moves on as soon as "
            "the data stops changing. This time counts toward the time limit."
        )
        wait_help = self._help_label(
            "After Excel finishes calculating, keep waiting — up to this long — while PI "
            "DataLink is still filling cells; moves on as soon as the data stops changing. "
            "Raise it if sheets arrive partly empty."
        )
        self.fail_if_empty = QCheckBox("Fail the run if an included sheet comes out empty")
        self.fail_if_empty.setChecked(True)
        self.fail_if_empty.setToolTip(
            "Safety net: if an included sheet contains no data at all after refresh, the "
            "run fails with a clear error instead of emailing a blank report."
        )
        self.fail_if_errors = QCheckBox(
            "Fail the run if an included sheet has error cells (strict)"
        )
        self.fail_if_errors.setChecked(False)
        self.fail_if_errors.setToolTip(
            "STRICT (off by default): fail the run if an included sheet contains Excel errors "
            "(#REF!, #NAME?, …). Off = the report is delivered anyway and the error cells are "
            "reported as a warning; use 'Blank out values' below to strip specific errors."
        )
        self.require_pi = QCheckBox("Require PI DataLink to connect before building the report")
        self.require_pi.setToolTip(
            "Fail this workbook if PI DataLink is missing or fails to load, even when "
            "pasted or cached values contain no errors. Diagnostic logs are collected "
            "under the service account; no interactive login is needed."
        )
        self.blank_values = QLineEdit()
        self.blank_values.setPlaceholderText("#REF!, #N/A, Tag not found, No Data")
        self.blank_values.setToolTip(
            "Comma-separated cell values to blank out of the output after saving — error "
            "codes (#REF!, #N/A, #NAME?) or PI DataLink strings. Leave empty to keep everything."
        )
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(96)
        self.notes.setToolTip("Free-form description of this job.")
        for spin in (self.timeout, self.post_refresh_wait):
            spin.setMaximumWidth(220)  # a number, not a text field — keep it compact
        timeout_group = QVBoxLayout()
        timeout_group.addWidget(self.timeout)
        timeout_group.addWidget(timeout_help)
        wait_group = QVBoxLayout()
        wait_group.addWidget(self.post_refresh_wait)
        wait_group.addWidget(wait_help)
        adv_form.addRow("Time limit", timeout_group)
        adv_form.addRow("Wait for add-in data", wait_group)
        adv_form.addRow("Concurrency group", self.group)
        adv_form.addRow(section_title("Report checks"))
        adv_form.addRow("", self.fail_if_empty)
        adv_form.addRow("", self.fail_if_errors)
        adv_form.addRow("", self.require_pi)
        adv_form.addRow("Blank out values", self.blank_values)
        adv_form.addRow("Notes", self.notes)
        for page in (general_tab, output_tab, schedule_tab, email_tab, advanced_tab):
            space_layout(page.layout())
        timeout_group.setSpacing(8)
        wait_group.setSpacing(8)
        general_scroll = scroll_page(general_tab)
        # A narrow window stacks the list above the sheets — decided on the width the tab
        # can SHOW (side by side, the box itself is never narrower than both panes).
        self._general_view = general_scroll.viewport()
        self._general_view.installEventFilter(self)
        self.tabs.addTab(general_scroll, "General")
        # Excel files can be dropped anywhere on the General tab.
        self.drop_overlay = DropOverlay(general_scroll.viewport())
        self._drops = FileDropFilter(
            general_tab, self.drop_overlay, self._add_paths, zone=self.empty_zone
        )
        self.tabs.addTab(scroll_page(output_tab), "Output")
        self.tabs.addTab(scroll_page(schedule_tab), "Schedule")
        self.tabs.addTab(scroll_page(email_tab), "Email")
        self.tabs.addTab(scroll_page(advanced_tab), "Advanced")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self._save_button_widget = buttons.button(QDialogButtonBox.StandardButton.Save)
        set_variant(self._save_button_widget, "primary")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(self.tabs)
        outer.addWidget(buttons)
        space_layout(outer)
        self._refresh_workbook_chrome()

    @staticmethod
    def _help_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("muted", True)
        label.setWordWrap(True)
        return label

    def _fetch_config(self) -> dict[str, Any]:
        try:
            config = self._api.get_config()
        except ApiError:
            return {}  # the editor still works; it just has nothing to suggest
        return config if isinstance(config, dict) else {}

    def _default_timeout_minutes(self) -> int | None:
        """The Settings default, so "Default" says what it means (None if unreachable)."""
        raw = (self._config.get("app") or {}).get("default_timeout_seconds")
        try:
            seconds = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            return None
        if seconds <= 0:
            return None
        return max(1, -(-seconds // 60))

    def _preview_job(self) -> dict[str, Any]:
        """What is on screen now, so the template preview shows this job's real email."""
        return {
            "name": self.name.text().strip(),
            "subject": self.subject.text().strip(),
            "stage": self.stage.currentData(),
            "sheets": [row.name for wb in self._workbooks for row in wb.rows if row.include],
            "workbooks": [Path(wb.path).name for wb in self._workbooks if wb.path],
            "recipients": {
                "testing": header_recipients(self.test_to, self.test_cc, self._email_groups),
                "live": header_recipients(self.prod_to, self.prod_cc, self._email_groups),
            },
        }

    def _recipient_field(self, tip: str) -> RecipientField:
        box = RecipientField(placeholder="Type a group or an address…")
        box.changed.connect(self._recheck_soon)
        box.group_edit_requested.connect(self._edit_group)
        box.setToolTip(
            f"{tip}\nType to search email groups and known addresses; Enter, Tab, comma or "
            "semicolon adds it. Click a chip's × to remove it; double-click a group to edit it."
        )
        return box

    def _edit_group(self, name: str) -> None:
        """Edit a group from its chip. It is saved to Settings at once (it is shared); this
        job's chips — saved or not — follow a rename straight away."""
        try:
            dialog = EmailGroupDialog(self._api, name, self)
        except ApiError as e:
            toast(self, f"Can't edit the group — the service isn't reachable ({e}).", "error")
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new, members = dialog.saved_name, dialog.saved_members
        groups = {k: v for k, v in self._email_groups.items() if k.casefold() != name.casefold()}
        groups[new] = members
        self._email_groups = groups
        email = self._config.setdefault("email", {})
        email["groups"] = [{"name": k, "members": v} for k, v in groups.items()]
        for box in self._recipient_boxes():
            if new != name:
                box.rename_group(name, new)
        for recipient_set in (self.prod_set, self.test_set):
            recipient_set.set_groups(groups)
        others = [j for j in dialog.used_by if j != self.name.text().strip()]
        where = (
            f" — also used by {len(others)} other job{'s' if len(others) != 1 else ''}"
            if others
            else ""
        )
        toast(self, f"Saved the group {new}{where}.", "success")

    # -- workbooks -----------------------------------------------------------------
    def _current(self) -> _WorkbookState | None:
        if self._current_wb is None or not 0 <= self._current_wb < len(self._workbooks):
            return None
        return self._workbooks[self._current_wb]

    def _store_current(self) -> None:
        """Every edit of the sheets table, the other-sheets choice or the PDF option goes
        straight into the shown workbook's state — results read in the background then
        always merge into the latest choices."""
        wb = self._current()
        if wb is None or self._syncing:
            return
        wb.rows = self._rows()
        wb.unselected = self.nonselected_mode.currentData()
        wb.pdf_mode = "combined" if self.combine_pdf.isChecked() else "separate"
        self._refresh_row(wb)
        self._recheck_soon()

    def _row_view(self, wb: _WorkbookState) -> RowView:
        included = sum(1 for row in wb.rows if row.include)
        gone = [row.name for row in wb.rows if row.include and row.missing]
        if wb.reading and wb.total is None and wb.read == "unread":
            status, kind = "Reading sheets…", "busy"
        elif wb.read == "missing":
            status, kind = "⚠ File not found", "warning"
        elif wb.read == "unreadable":
            status, kind = "⚠ Can't open the file", "warning"
        elif gone:
            status, kind = f"⚠ {_plural(len(gone), 'sheet')} missing", "warning"
        elif wb.total is not None:
            status, kind = f"{included} of {_plural(wb.total, 'sheet')}", "muted"
        else:
            status, kind = _plural(included, "sheet"), "muted"
            if wb.read == "offline":
                status += " · not refreshed"
        tooltip = wb.path + (f"\n{wb.error}" if wb.error else "")
        return RowView(wb.label, wb.path, status, kind, tooltip)

    def _refresh_row(self, wb: _WorkbookState) -> None:
        if wb in self._workbooks:
            self.wb_list.update_row(self._workbooks.index(wb), self._row_view(wb))

    def _set_workbooks(self, workbooks: list[_WorkbookState]) -> None:
        self._workbooks = list(workbooks)
        self.wb_list.set_rows([self._row_view(wb) for wb in self._workbooks], 0)
        self._show_workbook(0 if self._workbooks else None)
        self._refresh_workbook_chrome()

    def _show_workbook(self, index: int | None) -> None:
        """Show workbook ``index`` (None: the job has none — the drop zone shows)."""
        if index is None or not 0 <= index < len(self._workbooks):
            self._current_wb = None
            self.wb_stack.setCurrentWidget(self.empty_zone)
            self._set_rows([])
            self._update_output_example()
            return
        self._current_wb = index
        # The Output tab's card follows the workbook chosen here.
        self.output_example.set_workbooks([w.label for w in self._workbooks], index)
        self.wb_stack.setCurrentWidget(self.wb_split)
        wb = self._workbooks[index]
        if self.wb_list.current() != index:
            self.wb_list.set_current(index)
        self.wb_title.setText(wb.label)
        self.wb_title.setToolTip(wb.label)
        self.wb_path.set_path(wb.path)
        self._syncing = True
        try:
            self.combine_pdf.setChecked(wb.pdf_mode == "combined")
            mode_index = self.nonselected_mode.findData(wb.unselected)
            self.nonselected_mode.setCurrentIndex(max(mode_index, 0))
        finally:
            self._syncing = False
        self._set_rows(wb.rows)
        self._show_banner(wb)
        self._update_output_example()

    def _show_banner(self, wb: _WorkbookState) -> None:
        gone = [row.name for row in wb.rows if row.include and row.missing]
        retry = True
        if wb.read == "missing":
            text = (
                "The ReportFlow service can't find this file — it may have moved, or be on a "
                "drive the service can't see. The job's sheet choices are kept."
            )
        elif wb.read == "unreadable":
            text = f"This file couldn't be opened: {wb.error}"
        elif wb.read == "offline":
            text = "The ReportFlow service isn't reachable, so the sheet list can't be refreshed."
        elif gone:
            names = ", ".join(f"“{name}”" for name in gone)
            text = (
                f"{names} {'is' if len(gone) == 1 else 'are'} no longer in this workbook — "
                f"untick {'it' if len(gone) == 1 else 'them'} below, or replace the file."
            )
            retry = False
        else:
            self.wb_banner.hide()
            return
        self.wb_banner_text.setText(breakable(text))
        self.wb_banner_retry.setVisible(retry)
        self.wb_banner_replace.setVisible(wb.read != "offline")
        self.wb_banner.show()

    def _on_workbook_selected(self, index: int) -> None:
        if index < 0 or index == self._current_wb:
            return
        self._show_workbook(index)
        self._request_read(self._workbooks[index])  # at most every few seconds

    def _pick_workbooks(self) -> None:
        current = self._current()
        start = open_start_dir(current.path if current else "")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add Excel workbooks to this job", start, "Excel (*.xlsx *.xlsm)"
        )
        self._add_paths(paths)

    def add_workbooks(self, paths: list[str]) -> None:
        self._add_paths(paths)

    def _add_paths(self, paths: list[str]) -> None:
        """Add the Excel files among ``paths``; anything already in the job (however its
        path is spelled) or not an Excel workbook is left out, with one notice saying so."""
        seen: set[str] = set()
        added: list[_WorkbookState] = []
        duplicates: list[str] = []
        not_excel: list[str] = []
        for raw in paths:
            path = str(raw).strip()
            if not path:
                continue
            name = Path(path).name
            if Path(path).is_dir() or not is_excel_path(path):
                not_excel.append(name)
                continue
            key = _same_file_key(path)
            existing = self._workbook_index(path)
            if existing is not None or key in seen:
                duplicates.append(name)
                if existing is not None:
                    self.wb_list.flash(existing)
                continue
            seen.add(key)
            wb = _WorkbookState(path=path, fresh=True)
            self._workbooks.append(wb)
            self.wb_list.insert_row(len(self._workbooks) - 1, self._row_view(wb))
            added.append(wb)
        if added:
            self._show_workbook(len(self._workbooks) - 1)
            self._refresh_workbook_chrome()
            for wb in added:
                self._request_read(wb, force=True)
        problems = []
        if duplicates:
            problems.append(f"Already in this job: {', '.join(duplicates)}")
        if not_excel:
            problems.append(f"Not an Excel workbook (.xlsx, .xlsm): {', '.join(not_excel)}")
        if problems:
            toast(self, ". ".join(problems) + ".", "warning")

    def _workbook_index(self, path: str, *, ignore: int | None = None) -> int | None:
        """The workbook already holding ``path`` (same file, however it's spelled), or None."""
        key = _same_file_key(path)
        for i, wb in enumerate(self._workbooks):
            if i != ignore and wb.path and _same_file_key(wb.path) == key:
                return i
        return None

    def _replace_workbook(self, index: int) -> None:
        """Point a workbook at another file (e.g. next month's), keeping its sheet choices."""
        if not 0 <= index < len(self._workbooks):
            return
        wb = self._workbooks[index]
        path, _ = QFileDialog.getOpenFileName(
            self, f"Replace {wb.label}", open_start_dir(wb.path), "Excel (*.xlsx *.xlsm)"
        )
        if path:
            self.replace_workbook(index, path)

    def replace_workbook(self, index: int, path: str) -> None:
        wb = self._workbooks[index]
        other = self._workbook_index(path, ignore=index)
        if other is not None:
            self.wb_list.flash(other)
            toast(self, f"{Path(path).name} is already in this job.", "warning")
            return
        wb.path = path
        wb.read, wb.error, wb.total = "unread", "", None
        self._refresh_row(wb)
        self._show_workbook(index)
        self._request_read(wb, force=True)

    def _remove_workbook(self, index: int) -> None:
        if not 0 <= index < len(self._workbooks):
            return
        wb = self._workbooks.pop(index)
        if self._loader is not None:
            self._loader.forget(wb.uid)
        self.wb_list.remove_row(index)
        self._current_wb = None
        self._show_workbook(min(index, len(self._workbooks) - 1) if self._workbooks else None)
        self._refresh_workbook_chrome()
        toast(
            self,
            f"Removed {wb.label}.",
            "info",
            action=("Undo", lambda: self._restore_workbook(index, wb)),
        )

    def move_workbook(self, source: int, target: int) -> None:
        """Workbooks are built and attached in list order. The one shown stays shown, and
        the moved row flashes where it landed."""
        if not (0 <= source < len(self._workbooks) and 0 <= target < len(self._workbooks)):
            return
        shown = self._current()
        self._workbooks.insert(target, self._workbooks.pop(source))
        current = self._workbooks.index(shown) if shown is not None else target
        self.wb_list.set_rows([self._row_view(wb) for wb in self._workbooks], current)
        self._current_wb = None
        self._show_workbook(current)
        self._refresh_workbook_chrome()
        self.wb_list.flash(target)
        self.wb_list.list.setFocus(Qt.FocusReason.OtherFocusReason)

    def _restore_workbook(self, index: int, wb: _WorkbookState) -> None:
        index = min(index, len(self._workbooks))
        self._workbooks.insert(index, wb)
        self.wb_list.insert_row(index, self._row_view(wb))
        self._current_wb = None
        self._show_workbook(index)
        self._refresh_workbook_chrome()
        self._request_read(wb, force=True)

    def _refresh_workbook_chrome(self) -> None:
        """Bits that depend on how many workbooks there are."""
        self._recheck_soon()
        multi = len(self._workbooks) > 1
        self._output_form.setRowVisible(self.on_failure, multi)
        self._update_output_example()

    def _fit_workbook_layout(self) -> None:
        """Side by side when there's room; in a narrow window the list sits above."""
        narrow = self._general_view.width() < _STACK_BELOW
        orientation = Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal
        if self.wb_split.orientation() != orientation:
            self.wb_split.setOrientation(orientation)
            self.wb_list.setMaximumHeight(220 if narrow else 16777215)
            self.wb_list.setMinimumWidth(0 if narrow else _LIST_MIN)
            # Stacked: the list part is only as tall as it needs; the sheets get the rest.
            self.wb_split.setSizes([220, 2000] if narrow else [300, 600])

    def eventFilter(self, watched: Any, event: QEvent) -> bool:  # noqa: N802
        if watched is getattr(self, "_general_view", None) and event.type() == QEvent.Type.Resize:
            self._fit_workbook_layout()
        return super().eventFilter(watched, event)

    # -- reading sheets (always current, in the background) ---------------------------
    def _make_loader(self) -> SheetLoader | None:
        make_reader = getattr(self._api, "sheet_reader", None)
        if make_reader is None:
            return None  # an API without one (a bare test double): nothing is read
        executor = getattr(self._api, "sheet_executor", None) or PoolExecutor.shared()
        loader = SheetLoader(make_reader(), executor, self)
        loader.loaded.connect(self._on_sheets_loaded)
        return loader

    def _request_read(self, wb: _WorkbookState, *, force: bool = False) -> None:
        if self._loader is None or not wb.path:
            return
        now = time.monotonic()
        if not force and (wb.reading or now - wb.last_read < _REREAD_SECONDS):
            return
        # Marked first: an immediate answer (e.g. a fast local read) must find it reading.
        wb.reading = True
        wb.last_read = now
        self._refresh_row(wb)
        self._loader.request(wb.uid, wb.path)

    def _on_sheets_loaded(self, uid: int, path: str, outcome: SheetOutcome) -> None:
        wb = next((w for w in self._workbooks if w.uid == uid), None)
        if wb is None or wb.path != path:
            return  # removed or replaced since it was asked for
        wb.reading = False
        wb.last_read = time.monotonic()
        wb.read = outcome.state
        wb.error = outcome.message
        changed = False
        if outcome.state == "ok":
            wb.total = len(outcome.names)
            merged = merge_sheets(wb.rows, list(outcome.names), tick_all=wb.fresh)
            wb.fresh = False
            changed = merged != wb.rows
            wb.rows = merged
        self._refresh_row(wb)
        if wb is self._current():
            if changed:
                self._set_rows(wb.rows, keep_view=True)
            self._show_banner(wb)
            self._update_output_example()

    def _retry_current(self) -> None:
        wb = self._current()
        if wb is not None:
            self._request_read(wb, force=True)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._reactivated.start()  # back from Excel: the files may have changed

    def _on_reactivated(self) -> None:
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not self:
            return  # a file dialog or message box is up; activation is just churn
        for wb in self._workbooks:
            self._request_read(wb)

    def done(self, result: int) -> None:
        if self._loader is not None:
            self._loader.close()
        super().done(result)

    # -- sheet table -----------------------------------------------------------------
    @staticmethod
    def _check_item(checked: bool) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsSelectable
        )
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item

    def _set_rows(self, rows: list[_SheetRow], *, keep_view: bool = False) -> None:
        scroll = self.sheets.verticalScrollBar()
        position = scroll.value() if keep_view and scroll is not None else 0
        current = (self.sheets.currentRow(), self.sheets.currentColumn())
        self._syncing = True
        try:
            # Exactly tall enough for its rows (scrolling only past ~9 of them), so the
            # space below can never squeeze it.
            header = self.sheets.horizontalHeader().sizeHint().height()
            body = 34 * max(len(rows), 3)
            self.sheets.setFixedHeight(min(header + body + 14, 360))
            self.sheets.setRowCount(0)
            for row in rows:
                r = self.sheets.rowCount()
                self.sheets.insertRow(r)
                label = f"⚠  {row.name} — not in the file any more" if row.missing else row.name
                name = QTableWidgetItem(label)
                name.setData(Qt.ItemDataRole.UserRole, row.name)
                name.setData(Qt.ItemDataRole.UserRole + 1, row.missing)
                name.setFlags(Qt.ItemFlag.ItemIsEnabled)
                name.setToolTip(row.name)  # a long name is shortened in its one-line cell
                if row.missing:
                    name.setForeground(QColor(WARNING))
                    name.setToolTip(
                        "The job includes this sheet, but the workbook doesn't have it any more. "
                        "Untick it, or replace the file."
                    )
                self.sheets.setItem(r, _COL_NAME, name)
                self.sheets.setItem(r, _COL_INCLUDE, self._check_item(row.include))
                self.sheets.setItem(r, _COL_EXCEL, self._check_item(row.excel))
                self.sheets.setItem(r, _COL_PDF, self._check_item(row.pdf))
                self.sheets.setItem(r, _COL_HIDDEN, self._check_item(row.hidden))
                self._sync_row_enabled(r)
        finally:
            self._syncing = False
        if keep_view:
            if scroll is not None:
                scroll.setValue(position)
            if 0 <= current[0] < self.sheets.rowCount():
                self.sheets.setCurrentCell(*current)

    def _rows(self) -> list[_SheetRow]:
        def checked(r: int, c: int) -> bool:
            item = self.sheets.item(r, c)
            return item is not None and item.checkState() == Qt.CheckState.Checked

        def name(r: int) -> tuple[str, bool]:
            item = self.sheets.item(r, _COL_NAME)
            if item is None:
                return "", False
            stored = item.data(Qt.ItemDataRole.UserRole)
            return (
                str(stored) if stored is not None else item.text(),
                bool(item.data(Qt.ItemDataRole.UserRole + 1)),
            )

        rows = []
        for r in range(self.sheets.rowCount()):
            sheet, missing = name(r)
            rows.append(
                _SheetRow(
                    name=sheet,
                    include=checked(r, _COL_INCLUDE),
                    excel=checked(r, _COL_EXCEL),
                    pdf=checked(r, _COL_PDF),
                    hidden=checked(r, _COL_HIDDEN),
                    missing=missing,
                )
            )
        return rows

    def _sync_row_enabled(self, r: int) -> None:
        """PDF / Hidden only apply to included sheets — grey them out otherwise."""
        include = self.sheets.item(r, _COL_INCLUDE)
        on = include is not None and include.checkState() == Qt.CheckState.Checked
        excel = self.sheets.item(r, _COL_EXCEL)
        excel_on = excel is not None and excel.checkState() == Qt.CheckState.Checked
        for col in (_COL_EXCEL, _COL_PDF, _COL_HIDDEN):
            item = self.sheets.item(r, col)
            if item is not None:
                flags = (
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                    | (
                        Qt.ItemFlag.ItemIsEnabled
                        if on and (col != _COL_HIDDEN or excel_on)
                        else Qt.ItemFlag.NoItemFlags
                    )
                )
                item.setFlags(flags)

    def _on_sheet_item_changed(self, item: QTableWidgetItem) -> None:
        if self._syncing:
            return
        if item.column() in (_COL_INCLUDE, _COL_EXCEL):
            self._syncing = True
            try:
                self._sync_row_enabled(item.row())
            finally:
                self._syncing = False
        self._store_current()
        wb = self._current()
        if wb is not None:
            self._show_banner(wb)
        self._update_output_example()

    def _toggle_column(self, col: int) -> None:
        """Header click: tick the column for every (applicable) sheet, or untick if all are."""
        if col == _COL_NAME:
            return
        rows = self._rows()
        # PDF/Hidden only apply to included sheets; a sheet the file no longer has is never
        # ticked by "all".
        targets = [
            r
            for r, row in enumerate(rows)
            if (col == _COL_INCLUDE or (row.include and (col != _COL_HIDDEN or row.excel)))
            and not (row.missing and not row.include)
        ]
        items = [self.sheets.item(r, col) for r in targets]
        all_on = all(i is not None and i.checkState() == Qt.CheckState.Checked for i in items)
        state = Qt.CheckState.Unchecked if all_on else Qt.CheckState.Checked
        for item in items:
            if item is not None:
                item.setCheckState(state)

    def _checked_sheet_names(self) -> list[str]:
        """Included sheets of the workbook currently shown."""
        return [row.name for row in self._rows() if row.include]

    # -- actions -----------------------------------------------------------------
    def _pick_output_dir(self) -> None:
        current = self._current()
        start = open_start_dir(self.output_dir.text().strip() or (current.path if current else ""))
        path = QFileDialog.getExistingDirectory(self, "Select output folder", start)
        if path:
            self.output_dir.setText(path)

    def _update_output_example(self) -> None:
        """Refresh the "Each run creates" card for the workbook it shows (the one selected
        on the General tab, unless another was picked on the card)."""
        card = self.output_example
        labels = [wb.label for wb in self._workbooks]
        index = card.selected()
        if not 0 <= index < len(labels):
            index = self._current_wb if self._current_wb is not None else 0
        card.set_workbooks(labels, index)
        wb = self._workbooks[index] if 0 <= index < len(self._workbooks) else None
        rows = (
            self._rows()
            if wb is not None and index == self._current_wb
            else (wb.rows if wb is not None else [])
        )
        combined = (
            self.combine_pdf.isChecked()
            if index == self._current_wb
            else (wb is not None and wb.pdf_mode == "combined")
        )
        card.show_plan(
            plan_outputs(
                pattern=self.output_name.text(),
                job_name=self.name.text(),
                output_dir=self.output_dir.text(),
                workbook_path=wb.path if wb is not None else "",
                included=[(r.name, r.excel, r.pdf) for r in rows if r.include and not r.missing],
                combined_pdf=combined,
                workbook_count=len(self._workbooks),
            )
        )

    def _test_email_sender(self) -> Callable[[dict], object] | None:
        make = getattr(self._api, "test_email_sender", None)
        return make() if callable(make) else None

    def _edit_template(self) -> None:
        existing = self._template_html or ""
        link = self._template_link
        if not existing and self._editing:
            try:
                # Stored under the original name until a rename is saved.
                stored_as = self._original_name or self.name.text().strip()
                existing = self._api.get_email_template(stored_as).get("content", "")
            except ApiError:
                existing = ""
        if link and not existing:
            existing = self._read_link(link)
        dlg = EmailTemplateDialog(
            existing,
            self.name.text().strip(),
            self,
            linked_path=link,
            check_path=self._api.check_email_template,
            preview_job=self._preview_job(),
            send_test=self._test_email_sender(),
            addresses=self._known_addresses,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        link = dlg.linked_path()
        if link:
            self._template_link, self._template_html = link, None
            self.template_status.setText(f"Linked to {Path(link).name} — read on every run.")
        else:
            self._template_link, self._template_html = None, dlg.result_html()
            self.template_status.setText("Custom template ready — saved with the job.")

    @staticmethod
    def _read_link(path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _detect_template_link(self, name: str) -> None:
        """Ask the service whether the saved template is a linked file of the user's."""
        try:
            info = self._api.get_email_template(name)
        except ApiError:
            return
        if info.get("linked") and info.get("path"):
            self._template_link = str(info["path"])
            self.template_status.setText(
                f"Linked to {Path(self._template_link).name} — read on every run."
            )

    def _problems(self, *, commit: bool = True) -> list[_Problem]:
        """Everything that stops Save, in reading order. ``commit`` adds what was typed into
        the recipient boxes first (Save does; the live re-check while fixing must not)."""
        problems: list[_Problem] = []
        if not self.name.text().strip():
            problems.append(_Problem(_TAB_GENERAL, "Give the job a name.", self.name, help="jobs"))
        if not self._workbooks:
            problems.append(
                _Problem(
                    _TAB_GENERAL,
                    "Add at least one workbook — drop Excel files here, or Add workbooks…",
                )
            )
        seen: set[str] = set()
        for i, wb in enumerate(self._workbooks):
            message = None
            included = [row for row in wb.rows if row.include]
            gone = [row.name for row in included if row.missing]
            excel_rows = [row for row in included if row.excel]
            if _same_file_key(wb.path) in seen:
                message = f"{wb.label} is added twice."
            elif gone:
                message = (
                    f"{wb.label}: {', '.join(gone)} {'is' if len(gone) == 1 else 'are'} no "
                    "longer in the workbook — untick it, or replace the file."
                )
            elif not included:
                if wb.read in ("missing", "unreadable", "offline") or wb.reading:
                    message = f"{wb.label}: its sheets couldn't be read yet. {wb.error}".strip()
                else:
                    message = f"Include at least one sheet of {wb.label}."
            elif excel_rows and all(row.hidden for row in excel_rows):
                message = (
                    f"{wb.label}: at least one Excel attachment sheet must stay visible — untick "
                    "Hidden on one of them."
                )
            seen.add(_same_file_key(wb.path))
            if message:
                problems.append(_Problem(_TAB_GENERAL, message, workbook=i, help="attachments"))
        subject_problem = template_error(self.subject.text())
        if subject_problem:
            plain = explain_template_error(subject_problem)
            message = (
                plain
                if plain != subject_problem
                else f"This placeholder isn't finished: {subject_problem}"
            )
            problems.append(_Problem(_TAB_EMAIL, message, self.subject, help="placeholders"))
        for box in self._recipient_boxes():
            typed = box.commit_pending() if commit else None  # typed but not yet added
            if typed:
                problems.append(_Problem(_TAB_EMAIL, typed, box, help="email"))
        for box in (self.prod_to, self.test_to):
            if box.is_empty() and not any(p.widget is box for p in problems):
                problems.append(
                    _Problem(
                        _TAB_EMAIL, "Add at least one address or email group.", box, help="email"
                    )
                )
        try:
            self.schedule.to_crons()
        except ValueError as e:
            problems.append(_Problem(_TAB_SCHEDULE, str(e), help="schedule"))
        return problems

    def _validation_error(self) -> tuple[int | None, str] | None:
        """``(workbook_index, message)`` for the first problem, or None when the job is valid."""
        problems = self._problems()
        if not problems:
            return None
        first = problems[0]
        return first.workbook, first.message

    def _clear_problems(self) -> None:
        for widget in self._problem_widgets:
            clear_field_error(widget)
        self._problem_widgets = []
        self.wb_notice.clear_notice()
        mark_tab_errors(self.tabs, set())

    def _show_problems(self, problems: list[_Problem], *, focus: bool) -> None:
        """Each problem on its own field, a red dot on its tab — no OK popup."""
        self._clear_problems()
        for problem in problems:
            if problem.widget is not None:
                set_field_error(problem.widget, problem.message, problem.help)
                self._problem_widgets.append(problem.widget)
        workbook = next((p for p in problems if p.tab == _TAB_GENERAL and p.widget is None), None)
        if workbook is not None:
            anchor = workbook.help or "jobs"
            self.wb_notice.show_notice(
                workbook.message,
                "error",
                timeout_ms=0,
                action=("Learn more", lambda: show_help(self, anchor)),
            )
        mark_tab_errors(self.tabs, {p.tab for p in problems})
        self._showing_problems = bool(problems)
        if focus and problems:
            first = problems[0]
            self.tabs.setCurrentIndex(first.tab)
            if first.workbook is not None:
                self._show_workbook(first.workbook)
            if first.widget is not None:
                first.widget.setFocus()
            elif first.tab == _TAB_SCHEDULE:
                self.schedule.reveal_problem()  # the clashing card is outlined; show it

    def _recheck_soon(self, *_: object) -> None:
        if self._showing_problems:
            self._recheck.start()

    def _refresh_problems(self) -> None:
        if self._showing_problems:
            self._show_problems(self._problems(commit=False), focus=False)

    def _on_save(self) -> None:
        problems = self._problems()
        if problems:
            self._show_problems(problems, focus=True)
            return
        self._clear_problems()
        if self._save_handler is not None:
            error = self._save_handler(self)
            if error:
                # The service refused it: say so here, with every edit still on screen.
                toast(self, f"Couldn't save: {error}", "error")
                return
        self.accept()

    # -- form behaviour (FormDialog) --------------------------------------------
    _HELP_FOR_TAB = ("jobs", "output", "schedule", "email", "advanced")

    def help_anchor(self) -> str | None:
        index = self.tabs.currentIndex()
        return self._HELP_FOR_TAB[index] if 0 <= index < len(self._HELP_FOR_TAB) else None

    def save_form(self) -> None:
        self._on_save()

    def _recipient_boxes(self) -> list[RecipientField]:
        return [
            self.prod_to,
            self.prod_cc,
            self.prod_bcc,
            self.test_to,
            self.test_cc,
            self.test_bcc,
        ]

    def dirty_key(self) -> str:
        """What Save would store, so Cancel only asks when something real changed.

        Sheets compare by name: reading a workbook may reorder or add (unticked) rows,
        which is not an edit."""
        data = self.payload()
        for wb in data["workbooks"]:
            wb["sheets"] = sorted(wb["sheets"], key=lambda s: s["name"])
        data["_template"] = [self._template_html, self._template_link]
        data["_typed"] = [box.edit.text().strip() for box in self._recipient_boxes()]
        return json.dumps(data, sort_keys=True, default=str)

    # -- payload -----------------------------------------------------------------
    def payload(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name.text().strip(),
            "enabled": self.enabled.isChecked(),
            "workbooks": [
                {
                    "input_excel_path": wb.path,
                    "sheets": [
                        {"name": row.name, "excel": row.excel, "pdf": row.pdf, "hidden": row.hidden}
                        for row in wb.rows
                        if row.include
                    ],
                    "unselected_sheets": wb.unselected,
                    "pdf_mode": wb.pdf_mode,
                }
                for wb in self._workbooks
            ],
            "on_workbook_failure": self.on_failure.currentData(),
            "output_dir": self.output_dir.text().strip() or None,
            "output_name": self.output_name.text().strip() or None,
            "freeze_values": self.freeze.isChecked(),
            "schedule_crons": self.schedule.to_crons(),
            "timeout_seconds": self._timeout_seconds(),
            "concurrency_group": self.group.text().strip() or None,
            "post_refresh_wait_seconds": self.post_refresh_wait.value(),
            "fail_if_sheet_empty": self.fail_if_empty.isChecked(),
            "fail_if_sheet_has_errors": self.fail_if_errors.isChecked(),
            "require_pi_datalink": self.require_pi.isChecked(),
            "blank_out_values": _split_csv(self.blank_values.text()),
            "subject": self.subject.text().strip() or None,
            "stage": self.stage.currentData(),
            # In the order shown: the email lists people that way (groups at their place).
            "prod": {
                "to": self.prod_to.entries(),
                "cc": self.prod_cc.entries(),
                "bcc": self.prod_bcc.entries(),
            },
            "test": {
                "to": self.test_to.entries(),
                "cc": self.test_cc.entries(),
                "bcc": self.test_bcc.entries(),
            },
            "notes": self.notes.toPlainText().strip(),
        }
        # Preserve the template file (payload rebuilds the job): a linked file of the user's,
        # else the job's own previously saved one.
        if self._template_link:
            data["email_template_path"] = self._template_link
        elif self._existing_template_path:
            data["email_template_path"] = self._existing_template_path
        return data

    def _timeout_seconds(self) -> int | None:
        minutes = self.timeout.value()
        if not minutes:
            return None
        # Untouched: keep the stored value exactly (older jobs were set in seconds).
        loaded = self._loaded_timeout_seconds
        if loaded and -(-loaded // 60) == minutes:
            return loaded
        return minutes * 60

    def original_name(self) -> str | None:
        """EDIT mode: the name the job is saved under (differs from payload's on a rename)."""
        return self._original_name

    def template_html(self) -> str | None:
        """The in-app authored template source, or None when unchanged."""
        return self._template_html

    def _load(self, job: dict[str, Any]) -> None:
        job = migrate_legacy_job(job)  # an old-shaped (pre-0.11) job dict still loads
        self.name.setText(job.get("name", ""))
        if self._editing:
            # Renaming is allowed: the service moves the run history and template along.
            self._original_name = job.get("name")
        self.enabled.setChecked(job.get("enabled", True))
        # Only the included sheets are known until the workbook is read (right after this).
        self._set_workbooks(
            [
                _WorkbookState(
                    path=str(wb.get("input_excel_path") or ""),
                    rows=[
                        _SheetRow(
                            s["name"],
                            include=True,
                            excel=s.get("excel", True),
                            pdf=s.get("pdf", True),
                            hidden=s.get("hidden", False),
                        )
                        for s in wb.get("sheets", [])
                    ],
                    unselected=wb.get("unselected_sheets", "remove"),
                    pdf_mode=wb.get("pdf_mode", "separate"),
                )
                for wb in job.get("workbooks", [])
            ]
        )
        failure_index = self.on_failure.findData(job.get("on_workbook_failure", "fail_run"))
        self.on_failure.setCurrentIndex(max(failure_index, 0))
        self.output_dir.setText(job.get("output_dir") or "")
        self.output_name.setText(job.get("output_name") or "")
        self.freeze.setChecked(job.get("freeze_values", True))
        self.schedule.load(job.get("schedule_crons") or [])
        self._loaded_timeout_seconds = job.get("timeout_seconds") or None
        self.timeout.setValue(
            -(-self._loaded_timeout_seconds // 60) if self._loaded_timeout_seconds else 0
        )
        self.group.setText(job.get("concurrency_group") or "")
        self.post_refresh_wait.setValue(job.get("post_refresh_wait_seconds") or 0)
        self.fail_if_empty.setChecked(job.get("fail_if_sheet_empty", True))
        self.fail_if_errors.setChecked(job.get("fail_if_sheet_has_errors", False))
        self.require_pi.setChecked(job.get("require_pi_datalink", False))
        self.blank_values.setText(_join_csv(job.get("blank_out_values")))
        self.notes.setPlainText(job.get("notes", ""))
        self.subject.setText(job.get("subject") or "")
        stage_index = self.stage.findData(job.get("stage", "testing"))
        self.stage.setCurrentIndex(stage_index if stage_index >= 0 else 0)
        self._existing_template_path = job.get("email_template_path")
        if self._existing_template_path:
            self.template_status.setText("This job has a custom template.")
            if self._editing:
                self._detect_template_link(job.get("name", ""))
        prod = job.get("prod", {})
        self.prod_to.set_entries(field_entries(prod, "to"))
        self.prod_cc.set_entries(field_entries(prod, "cc"))
        self.prod_bcc.set_entries(field_entries(prod, "bcc"))
        test = job.get("test", {})
        self.test_to.set_entries(field_entries(test, "to"))
        self.test_cc.set_entries(field_entries(test, "cc"))
        self.test_bcc.set_entries(field_entries(test, "bcc"))

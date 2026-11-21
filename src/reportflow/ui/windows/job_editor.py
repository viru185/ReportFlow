"""Job editor dialog — compact tabs (General / Output / Schedule / Email / Advanced).

Each tab is focused and scrolls on smaller screens. Non-mandatory settings are optional.
A job has one or more workbooks (one tab each on the General tab), and each included sheet
has its own PDF / Hidden choice. Outputs are a folder + optional filename stem; the schedule
is built visually; the email body is authored in-app via EmailTemplateDialog.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from reportflow.core.config.models import migrate_legacy_job
from reportflow.core.email.render import template_error
from reportflow.core.output_names import (
    DEFAULT_OUTPUT_STEM,
    OUTPUT_NAME_TOKENS,
    expand_output_name,
    overwrites_same_day,
)
from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.feedback import FormDialog, InlineNotice
from reportflow.ui.fs_util import open_start_dir
from reportflow.ui.placeholder_picker import (
    PlaceholderButton,
    email_placeholders,
    output_name_placeholders,
)
from reportflow.ui.recipient_field import RecipientField, RecipientSet, header_recipients
from reportflow.ui.suggestions import concurrency_groups, email_groups, known_addresses
from reportflow.ui.widgets import CenteredCheckDelegate, scroll_page, section_title, space_layout
from reportflow.ui.windows.email_template_dialog import EmailTemplateDialog
from reportflow.ui.windows.schedule_widget import ScheduleWidget

# Sheet table columns.
_COL_NAME, _COL_INCLUDE, _COL_EXCEL, _COL_PDF, _COL_HIDDEN = range(5)

# What the output copy does with the sheets that are NOT included (stored per workbook).
_UNSELECTED_MODES = [
    ("Remove them from the file", "remove"),
    ("Keep them, hidden", "hide"),
    ("Keep them, visible", "keep"),
]


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


@dataclass
class _WorkbookState:
    """The editor's copy of one workbook; the widgets show the current one."""

    path: str = ""
    rows: list[_SheetRow] = field(default_factory=list)
    unselected: str = "remove"
    pdf_mode: str = "separate"

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
    ) -> None:
        """``job`` opens EDIT mode; ``prefill`` opens CREATE mode seeded from an existing
        job (Duplicate): everything copied except the name (fresh) and the stage (back to
        Testing). ``prefill_template`` is the source job's email template content — the copy
        gets its own file with the same content; ``prefill_template_link`` instead means the
        source is linked to a file of the user's, and the copy links to the same file."""
        super().__init__(parent, settings_key="job_editor")
        self._api = api
        self._editing = job is not None
        self._template_html: str | None = None  # authored in-app; caller saves it after job save
        self._existing_template_path: str | None = None
        # A template file of the user's that the job stays linked to (re-read every run).
        self._template_link: str | None = None
        self._workbooks: list[_WorkbookState] = [_WorkbookState()]
        self._loaded_timeout_seconds: int | None = None
        self._original_name: str | None = None  # EDIT mode: the name the job is stored under
        self._current_wb = 0
        self._syncing = False  # guards widget signals while the editor fills widgets itself
        self.setWindowTitle("Edit Job" if self._editing else "New Job")
        self.resize(900, 680)
        # One config snapshot feeds the defaults and every autocomplete list.
        self._config = self._fetch_config()
        self._email_groups = email_groups(self._config)
        self._build()
        if job:
            self._load(job)
        elif prefill:
            self._load(prefill)
            self._apply_duplicate_mode(
                prefill.get("name", ""), prefill_template, prefill_template_link
            )
        self._update_output_example()
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
        self.enabled = QCheckBox("Run on schedule")
        self.enabled.setChecked(True)
        self.enabled.setToolTip("Untick to keep the job configured but never run it on schedule.")
        name_row = QHBoxLayout()
        name_row.addWidget(self.name)
        name_row.addWidget(self.enabled)
        # One tab per input workbook; × removes one. A run builds them all and sends ONE email.
        self.workbook_tabs = QTabBar()
        self.workbook_tabs.setExpanding(False)
        self.workbook_tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.workbook_tabs.setUsesScrollButtons(True)
        self.workbook_tabs.setDocumentMode(True)
        self.workbook_tabs.addTab(self._workbooks[0].label)
        self.workbook_tabs.currentChanged.connect(self._on_workbook_switched)
        self.workbook_tabs.tabCloseRequested.connect(self._remove_workbook)
        add_wb = QPushButton("+ Add workbook…")
        add_wb.setToolTip(
            "Add another Excel file to this job. Every workbook is built on each run and all "
            "the files go out in one email."
        )
        add_wb.clicked.connect(self._pick_additional_workbook)
        wbs_row = QHBoxLayout()
        wbs_row.addWidget(self.workbook_tabs, 1)
        wbs_row.addWidget(add_wb)
        self.input_excel = QLineEdit()
        self.input_excel.setToolTip("The Excel workbook to open, refresh, and export.")
        self.input_excel.textChanged.connect(self._on_input_path_edited)
        browse_wb = QPushButton("Browse…")
        browse_wb.clicked.connect(self._pick_input_excel)
        discover = QPushButton("Discover sheets")
        discover.setToolTip("Read the sheet names from the selected workbook.")
        discover.clicked.connect(self._discover_sheets)
        wb_row = QHBoxLayout()
        wb_row.addWidget(self.input_excel)
        wb_row.addWidget(browse_wb)
        wb_row.addWidget(discover)
        self.sheets = QTableWidget(0, 5)
        self.sheets.setHorizontalHeaderLabels(
            ["Sheet", "Include", "Excel attachment", "PDF", "Hidden"]
        )
        self.sheets.verticalHeader().setVisible(False)
        self.sheets.verticalHeader().setDefaultSectionSize(34)
        self.sheets.setMinimumHeight(150)
        self.sheets.setMaximumHeight(320)
        self.sheets.setTabKeyNavigation(True)
        self.sheets.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.sheets.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sheets.setShowGrid(False)
        header = self.sheets.horizontalHeader()
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in (_COL_INCLUDE, _COL_EXCEL, _COL_PDF, _COL_HIDDEN):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
            self.sheets.setItemDelegateForColumn(col, CenteredCheckDelegate(self.sheets))
        header.setToolTip("Click a column title to tick or untick the whole column.")
        header.sectionClicked.connect(self._toggle_column)
        self.sheets.itemChanged.connect(self._on_sheet_item_changed)
        self.sheets.setToolTip(
            "Include: the sheet is refreshed, checked and frozen.\n"
            "Excel attachment: include this sheet in the emailed Excel file.\n"
            "PDF: include this sheet in PDF output.\n"
            "Hidden: keep it in the Excel file but hidden (recipients can unhide it)."
        )
        sheets_hint = QLabel(
            "Include sheets to process, then choose their Excel and PDF attachments. "
            "A full Excel copy is saved locally. Click a column heading to select all."
        )
        sheets_hint.setProperty("muted", True)
        sheets_hint.setWordWrap(True)
        # What the output copy does with the sheets you did NOT include. One choice covers
        # "keep or remove" and "if kept, hidden or visible".
        self.nonselected_mode = QComboBox()
        for label, key in _UNSELECTED_MODES:
            self.nonselected_mode.addItem(label, key)
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
        self.combine_pdf.toggled.connect(self._update_output_example)
        input_form.addRow("Job name", name_row)
        workbook_box = QGroupBox("Workbooks")
        workbook_layout = QVBoxLayout(workbook_box)
        workbook_layout.addLayout(wbs_row)
        source_form = QFormLayout()
        source_form.addRow("Input Excel file", wb_row)
        workbook_layout.addLayout(source_form)
        workbook_layout.addWidget(section_title("Sheets and email attachments"))
        workbook_layout.addWidget(self.sheets)
        workbook_layout.addWidget(sheets_hint)
        options_form = QFormLayout()
        options_form.addRow("Other local sheets", self.nonselected_mode)
        options_form.addRow("PDF output", self.combine_pdf)
        workbook_layout.addLayout(options_form)
        space_layout(workbook_layout)
        general_layout.addWidget(workbook_box)
        general_layout.addStretch()
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
        browse_dir = QPushButton("Browse…")
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
        self.output_example = QLabel("")
        self.output_example.setProperty("muted", True)
        self.output_example.setWordWrap(True)
        self.freeze = QCheckBox("Freeze formulas to values")
        self.freeze.setChecked(True)
        self.freeze.setToolTip(
            "Convert formulas to plain values on the included sheets in the output copy, so "
            "recipients see the numbers without needing your data connections."
        )
        # Only meaningful with several workbooks (row hidden otherwise).
        self.on_failure = QComboBox()
        self.on_failure.addItem("Fail the whole run — send nothing", "fail_run")
        self.on_failure.addItem("Send the workbooks that worked (with a warning)", "send_partial")
        self.on_failure.setToolTip(
            "When one of this job's workbooks fails to build: either nothing is emailed "
            "(the safe default), or the email goes out with the workbooks that did work and "
            "the run lists the failed one as a warning."
        )
        output_form.addRow("Output folder", dir_row)
        output_form.addRow("Filename (optional)", output_name_row)
        output_form.addRow("", self.output_example)
        output_form.addRow("", self.freeze)
        output_form.addRow("If a workbook fails", self.on_failure)
        # ---- Schedule tab ----
        schedule_tab = QWidget()
        schedule_lay = QVBoxLayout(schedule_tab)
        self.schedule = ScheduleWidget()
        schedule_lay.addWidget(self.schedule)
        schedule_lay.addStretch()
        # ---- Email tab ----
        email_tab = QWidget()
        email_form = QFormLayout(email_tab)
        self.subject = QLineEdit()
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
        self.stage = QComboBox()
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
        edit_template = QPushButton("Edit email template…")
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
        self.timeout = QSpinBox()
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
        self.group.setCompleter(group_completer)
        self.post_refresh_wait = QSpinBox()
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
        self.tabs.addTab(scroll_page(general_tab), "General")
        self.tabs.addTab(scroll_page(output_tab), "Output")
        self.tabs.addTab(scroll_page(schedule_tab), "Schedule")
        self.tabs.addTab(scroll_page(email_tab), "Email")
        self.tabs.addTab(scroll_page(advanced_tab), "Advanced")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self._save_button_widget = buttons.button(QDialogButtonBox.StandardButton.Save)
        self._save_button_widget.setProperty("accent", True)
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
        self._commit_current()
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
        box.setToolTip(
            f"{tip}\nType to search email groups and known addresses; Enter, Tab, comma or "
            "semicolon adds it. Click a chip's × to remove it."
        )
        return box

    # -- workbooks -----------------------------------------------------------------
    def _commit_current(self) -> None:
        """Copy the widgets back into the current workbook's state."""
        wb = self._workbooks[self._current_wb]
        wb.path = self.input_excel.text().strip()
        wb.rows = self._rows()
        wb.unselected = self.nonselected_mode.currentData()
        wb.pdf_mode = "combined" if self.combine_pdf.isChecked() else "separate"

    def _show_workbook(self, index: int) -> None:
        self._current_wb = index
        wb = self._workbooks[index]
        self._syncing = True
        try:
            self.input_excel.setText(wb.path)
            self.combine_pdf.setChecked(wb.pdf_mode == "combined")
            mode_index = self.nonselected_mode.findData(wb.unselected)
            self.nonselected_mode.setCurrentIndex(max(mode_index, 0))
        finally:
            self._syncing = False
        self._set_rows(wb.rows)
        self._update_output_example()

    def _set_workbooks(self, workbooks: list[_WorkbookState]) -> None:
        self._workbooks = workbooks or [_WorkbookState()]
        self._syncing = True
        try:
            while self.workbook_tabs.count():
                self.workbook_tabs.removeTab(0)
            for wb in self._workbooks:
                self.workbook_tabs.addTab(wb.label)
            self.workbook_tabs.setCurrentIndex(0)
        finally:
            self._syncing = False
        self._show_workbook(0)
        self._refresh_workbook_chrome()

    def _on_workbook_switched(self, index: int) -> None:
        if self._syncing or index < 0 or index == self._current_wb:
            return
        self._commit_current()
        self._show_workbook(index)

    def _add_workbook(self, path: str) -> None:
        """Append a workbook, switch to it, and read its sheets."""
        self._commit_current()
        self._workbooks.append(_WorkbookState(path=path))
        self._syncing = True
        try:
            index = self.workbook_tabs.addTab(self._workbooks[-1].label)
            self.workbook_tabs.setCurrentIndex(index)
        finally:
            self._syncing = False
        self._show_workbook(index)
        self._refresh_workbook_chrome()
        if path:
            self._discover_sheets()

    def _pick_additional_workbook(self) -> None:
        start = open_start_dir(self.input_excel.text().strip())
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add Excel files to this job", start, "Excel (*.xlsx *.xlsm)"
        )
        self.add_workbooks(paths)

    def add_workbooks(self, paths: list[str]) -> None:
        """Add several workbooks at once; files already in the job are skipped, with one
        warning naming them (adding the same file twice would build it twice)."""
        self._commit_current()
        skipped: list[str] = []
        for path in paths:
            if self._workbook_index(path) is not None:
                skipped.append(Path(path).name)
                continue
            if len(self._workbooks) == 1 and not self._workbooks[0].path:
                # A new job's first tab is still empty: fill it rather than leave it blank.
                self.input_excel.setText(path)
                self._discover_sheets()
                continue
            self._add_workbook(path)
        if skipped:
            QMessageBox.warning(
                self,
                "Already in this job",
                "These files are already in this job, so they weren't added again:\n"
                + "\n".join(f"• {name}" for name in skipped),
            )

    def _workbook_index(self, path: str, *, ignore: int | None = None) -> int | None:
        """The tab already holding ``path`` (same file, however it's spelled), or None."""
        key = _same_file_key(path)
        for i, wb in enumerate(self._workbooks):
            if i != ignore and wb.path and _same_file_key(wb.path) == key:
                return i
        return None

    def _remove_workbook(self, index: int) -> None:
        if len(self._workbooks) <= 1:
            return  # the × is hidden then; a job always has one workbook
        label = self._workbooks[index].label
        confirm = QMessageBox.question(self, "Remove workbook", f"Remove {label} from this job?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._commit_current()
        del self._workbooks[index]
        self._syncing = True
        try:
            self.workbook_tabs.removeTab(index)
            new_index = min(index, len(self._workbooks) - 1)
            self.workbook_tabs.setCurrentIndex(new_index)
        finally:
            self._syncing = False
        self._show_workbook(new_index)
        self._refresh_workbook_chrome()

    def _refresh_workbook_chrome(self) -> None:
        """Bits that depend on how many workbooks there are."""
        multi = len(self._workbooks) > 1
        self.workbook_tabs.setTabsClosable(multi)
        self._output_form.setRowVisible(self.on_failure, multi)
        self._update_output_example()

    def _on_input_path_edited(self, text: str) -> None:
        if self._syncing:
            return
        self._workbooks[self._current_wb].path = text.strip()
        self.workbook_tabs.setTabText(self._current_wb, self._workbooks[self._current_wb].label)
        self._update_output_example()

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

    def _set_rows(self, rows: list[_SheetRow]) -> None:
        self._syncing = True
        try:
            self.sheets.setMaximumHeight(min(320, max(150, 36 * (len(rows) + 1))))
            self.sheets.setRowCount(0)
            for row in rows:
                r = self.sheets.rowCount()
                self.sheets.insertRow(r)
                name = QTableWidgetItem(row.name)
                name.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.sheets.setItem(r, _COL_NAME, name)
                self.sheets.setItem(r, _COL_INCLUDE, self._check_item(row.include))
                self.sheets.setItem(r, _COL_EXCEL, self._check_item(row.excel))
                self.sheets.setItem(r, _COL_PDF, self._check_item(row.pdf))
                self.sheets.setItem(r, _COL_HIDDEN, self._check_item(row.hidden))
                self._sync_row_enabled(r)
        finally:
            self._syncing = False

    def _rows(self) -> list[_SheetRow]:
        def checked(r: int, c: int) -> bool:
            item = self.sheets.item(r, c)
            return item is not None and item.checkState() == Qt.CheckState.Checked

        def name(r: int) -> str:
            item = self.sheets.item(r, _COL_NAME)
            return item.text() if item is not None else ""

        return [
            _SheetRow(
                name=name(r),
                include=checked(r, _COL_INCLUDE),
                excel=checked(r, _COL_EXCEL),
                pdf=checked(r, _COL_PDF),
                hidden=checked(r, _COL_HIDDEN),
            )
            for r in range(self.sheets.rowCount())
        ]

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
        self._update_output_example()

    def _toggle_column(self, col: int) -> None:
        """Header click: tick the column for every (applicable) sheet, or untick if all are."""
        if col == _COL_NAME:
            return
        rows = self._rows()
        # PDF/Hidden only apply to included sheets.
        targets = [
            r
            for r, row in enumerate(rows)
            if col == _COL_INCLUDE or (row.include and (col != _COL_HIDDEN or row.excel))
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
    def _pick_input_excel(self) -> None:
        # Reopen at the currently-selected file's folder, else the Downloads folder.
        start = open_start_dir(self.input_excel.text().strip())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Excel file", start, "Excel (*.xlsx *.xlsm)"
        )
        if path:
            other = self._workbook_index(path, ignore=self._current_wb)
            if other is not None:
                QMessageBox.warning(
                    self,
                    "Already in this job",
                    f"{Path(path).name} is already in this job (tab {other + 1}). Choose a "
                    "different file, or use that tab.",
                )
                return
            self.input_excel.setText(path)
            self._discover_sheets()
            self._update_output_example()

    def _pick_output_dir(self) -> None:
        start = open_start_dir(self.output_dir.text().strip() or self.input_excel.text().strip())
        path = QFileDialog.getExistingDirectory(self, "Select output folder", start)
        if path:
            self.output_dir.setText(path)

    def _discover_sheets(self) -> None:
        path = self.input_excel.text().strip()
        if not path:
            return
        try:
            names = self._api.workbook_sheets(path)
        except ApiError as e:
            QMessageBox.warning(self, "Sheet discovery failed", str(e))
            return
        known = {row.name: row for row in self._rows()}
        # Fresh discovery with nothing ticked yet (a new workbook): include everything —
        # exporting all sheets is the common case, unticking the exception. Re-discovery
        # keeps each known sheet's saved choices.
        include_all = not any(row.include for row in known.values())
        self._set_rows([known.get(name) or _SheetRow(name, include=include_all) for name in names])
        self._update_output_example()

    def _update_output_example(self) -> None:
        pattern = self.output_name.text().strip() or DEFAULT_OUTPUT_STEM
        multi = len(self._workbooks) > 1
        if multi and "{workbook}" not in pattern:
            pattern += "_{workbook}"  # mirrors the launcher: several outputs need distinct names
        current = self.input_excel.text().strip()
        stem = expand_output_name(
            pattern,
            job_name=self.name.text().strip() or "job",
            run_id="a1b2c3",
            now=datetime.now(),
            workbook=Path(current).stem if current else "workbook",
        )
        folder = self.output_dir.text().strip() or "(input file's folder)"
        example = f"→ {folder}\\{stem}.xlsx"
        if any(row.include and row.excel for row in self._rows()):
            example += f" · email: {stem}_email.xlsx"
        if any(row.include and row.pdf for row in self._rows()):
            example += f", {stem}.pdf" if self.combine_pdf.isChecked() else f", {stem}_<sheet>.pdf"
        if multi:
            example += f" — one per workbook ({len(self._workbooks)})"
        if overwrites_same_day(pattern):
            example += "\n⚠ A second run on the same day overwrites the first — add {time}."
        self.output_example.setText(example)

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

    def _validation_error(self) -> tuple[int | None, str] | None:
        """``(tab_index, message)`` for the first problem, or None when the job is valid.

        ``tab_index`` is the workbook tab to bring forward (None: not workbook-specific).
        """
        self._commit_current()
        if not self.name.text().strip():
            return None, "Job name is required."
        seen: set[str] = set()
        for i, wb in enumerate(self._workbooks):
            if not wb.path:
                return i, "Select the input Excel file."
            if _same_file_key(wb.path) in seen:
                return i, f"{wb.label} is added twice."
            seen.add(_same_file_key(wb.path))
            included = [row for row in wb.rows if row.include]
            if not included:
                return i, f"Include at least one sheet of {wb.label}."
            excel_rows = [row for row in included if row.excel]
            if excel_rows and all(row.hidden for row in excel_rows):
                return i, (
                    f"{wb.label}: at least one Excel attachment sheet must stay visible — untick "
                    "Hidden on one of them."
                )
        subject_problem = template_error(self.subject.text())
        if subject_problem:
            return None, f"The Subject has a placeholder typo: {subject_problem}"
        for label, box in (
            ("Production: To", self.prod_to),
            ("Production: Cc", self.prod_cc),
            ("Production: Bcc", self.prod_bcc),
            ("Test: To", self.test_to),
            ("Test: Cc", self.test_cc),
            ("Test: Bcc", self.test_bcc),
        ):
            problem = box.commit_pending()  # typed but not yet added
            if problem:
                return None, f"{label}: {problem}"
        if self.prod_to.is_empty():
            return None, "Production: To needs at least one address or email group."
        if self.test_to.is_empty():
            return None, "Test: To needs at least one address or email group."
        return None

    def _on_save(self) -> None:
        problem = self._validation_error()
        if problem is not None:
            tab, message = problem
            if tab is not None:
                self.tabs.setCurrentIndex(0)
                self.workbook_tabs.setCurrentIndex(tab)
            QMessageBox.warning(self, "Validation", message)
            return
        try:
            self.schedule.to_crons()
        except ValueError as e:
            QMessageBox.warning(self, "Schedule", str(e))
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
        self._commit_current()
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
            "prod": {
                "to": self.prod_to.emails(),
                "cc": self.prod_cc.emails(),
                "bcc": self.prod_bcc.emails(),
                "to_groups": self.prod_to.groups(),
                "cc_groups": self.prod_cc.groups(),
                "bcc_groups": self.prod_bcc.groups(),
            },
            "test": {
                "to": self.test_to.emails(),
                "cc": self.test_cc.emails(),
                "bcc": self.test_bcc.emails(),
                "to_groups": self.test_to.groups(),
                "cc_groups": self.test_cc.groups(),
                "bcc_groups": self.test_bcc.groups(),
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
        # Only the included sheets are known until "Discover sheets" reads the workbook.
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
        self.prod_to.set_value(prod.get("to") or [], prod.get("to_groups"))
        self.prod_cc.set_value(prod.get("cc") or [], prod.get("cc_groups"))
        self.prod_bcc.set_value(prod.get("bcc") or [], prod.get("bcc_groups"))
        test = job.get("test", {})
        self.test_to.set_value(test.get("to") or [], test.get("to_groups"))
        self.test_cc.set_value(test.get("cc") or [], test.get("cc_groups"))
        self.test_bcc.set_value(test.get("bcc") or [], test.get("bcc_groups"))

"""Job editor dialog — compact tabs (General / Output / Schedule / Email / Advanced).

No scrolling: each tab is small and focused. Everything non-mandatory is optional.
Outputs are a folder + optional filename stem; the schedule is built visually; the email
body is authored in-app via EmailTemplateDialog.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.fs_util import open_start_dir
from reportflow.ui.windows.email_template_dialog import EmailTemplateDialog
from reportflow.ui.windows.schedule_widget import ScheduleWidget


def _split_csv(text: str) -> list[str]:
    return [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]


def _join_csv(items: list[str] | None) -> str:
    return ", ".join(items or [])


class JobEditorDialog(QDialog):
    def __init__(
        self, api: ApiClient, job: dict[str, Any] | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._editing = job is not None
        self._template_html: str | None = None  # authored in-app; caller saves it after job save
        self._existing_template_path: str | None = None
        self.setWindowTitle("Edit Job" if self._editing else "New Job")
        self.resize(620, 540)
        self._build()
        if job:
            self._load(job)
        self._update_output_example()

    # -- construction ------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # ---- General tab ----
        general_tab = QWidget()
        input_form = QFormLayout(general_tab)

        self.name = QLineEdit()
        self.name.setToolTip("A unique name for this job; it is also used in output filenames.")
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(True)
        self.enabled.setToolTip("Untick to keep the job configured but never run it on schedule.")
        name_row = QHBoxLayout()
        name_row.addWidget(self.name)
        name_row.addWidget(self.enabled)

        self.input_excel = QLineEdit()
        self.input_excel.setToolTip("The Excel workbook to open, refresh, and export.")
        browse_wb = QPushButton("Browse…")
        browse_wb.clicked.connect(self._pick_input_excel)
        discover = QPushButton("Discover sheets")
        discover.setToolTip("Read the sheet names from the selected workbook.")
        discover.clicked.connect(self._discover_sheets)
        wb_row = QHBoxLayout()
        wb_row.addWidget(self.input_excel)
        wb_row.addWidget(browse_wb)
        wb_row.addWidget(discover)

        self.sheets = QListWidget()
        self.sheets.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.sheets.setToolTip("Tick the sheets this job should refresh, freeze, and export.")

        input_form.addRow("Job name", name_row)
        input_form.addRow("Input Excel file", wb_row)
        input_form.addRow("Sheets", self.sheets)

        # ---- Output tab ----
        output_tab = QWidget()
        output_form = QFormLayout(output_tab)

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
        self.output_name.setPlaceholderText("{job}_{date}")
        self.output_name.setToolTip(
            "Optional filename (without extension). Placeholders: {job}, {date}, "
            "{datetime}, {run_id}. Leave empty for {job}_{date}."
        )
        self.output_name.textChanged.connect(self._update_output_example)

        self.output_example = QLabel("")
        self.output_example.setProperty("muted", True)
        self.output_example.setWordWrap(True)

        self.freeze = QCheckBox("Freeze formulas to values")
        self.freeze.setChecked(True)
        self.freeze.setToolTip(
            "Convert formulas to plain values on the selected sheets in the output copy, so "
            "recipients see the numbers without needing your data connections."
        )
        self.gen_pdf = QCheckBox("Generate PDF (one per sheet)")
        self.gen_pdf.setChecked(True)
        self.gen_pdf.setToolTip(
            "Export each selected sheet to PDF using the workbook's own print layout."
        )
        self.gen_pdf.toggled.connect(self._update_output_example)
        toggles_row = QHBoxLayout()
        toggles_row.addWidget(self.freeze)
        toggles_row.addWidget(self.gen_pdf)
        toggles_row.addStretch()

        output_form.addRow("Output folder", dir_row)
        output_form.addRow("Filename (optional)", self.output_name)
        output_form.addRow("", self.output_example)
        output_form.addRow("", toggles_row)

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
        self.subject.setToolTip("Email subject; test runs are automatically prefixed [TEST].")
        self.send_email = QCheckBox("Also email Production recipients on real / scheduled runs")
        self.send_email.setToolTip(
            "When ticked, successful real and scheduled Runs email the Production recipients. "
            "When unticked, real/scheduled Runs email no one. Test email runs always go to the "
            "Test recipients regardless."
        )
        self.email_hint = QLabel("")
        self.email_hint.setProperty("muted", True)
        self.email_hint.setWordWrap(True)
        self.send_email.toggled.connect(self._update_email_hint)
        self._update_email_hint(self.send_email.isChecked())

        self.prod_to = QLineEdit()
        self.prod_to.setToolTip("Production To — required. Comma-separated addresses.")
        self.prod_cc = QLineEdit()
        self.prod_cc.setToolTip("Production Cc — optional.")
        self.prod_bcc = QLineEdit()
        self.prod_bcc.setToolTip("Production Bcc — optional (hidden from other recipients).")
        self.test_to = QLineEdit()
        self.test_to.setToolTip("Test To — who receives TEST run emails.")
        self.test_cc = QLineEdit()
        self.test_cc.setToolTip("Test Cc — optional.")
        self.test_bcc = QLineEdit()
        self.test_bcc.setToolTip("Test Bcc — optional.")

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

        email_form.addRow("Subject", self.subject)
        email_form.addRow("", self.send_email)
        email_form.addRow("", self.email_hint)
        email_form.addRow("Prod: To", self.prod_to)
        email_form.addRow("Prod: Cc (optional)", self.prod_cc)
        email_form.addRow("Prod: Bcc (optional)", self.prod_bcc)
        email_form.addRow("Test: To", self.test_to)
        email_form.addRow("Test: Cc (optional)", self.test_cc)
        email_form.addRow("Test: Bcc (optional)", self.test_bcc)
        email_form.addRow("Body", tpl_row)

        # ---- Advanced tab ----
        advanced_tab = QWidget()
        adv_form = QFormLayout(advanced_tab)
        adv_hint = QLabel("Optional tuning — most jobs don't need these.")
        adv_hint.setProperty("muted", True)
        adv_form.addRow(adv_hint)

        self.timeout = QSpinBox()
        self.timeout.setRange(0, 86400)
        self.timeout.setSpecialValueText("(use default)")
        self.timeout.setSuffix(" s")
        self.timeout.setToolTip(
            "Maximum seconds a run may take. If Excel hangs, the run is killed at this limit "
            "and marked Timed out. 0 = use the default from Settings."
        )
        self.group = QLineEdit()
        self.group.setToolTip(
            "Jobs sharing the same group name run one-at-a-time instead of in parallel — "
            "useful when several jobs hit the same slow database. Leave empty for normal "
            "parallel behavior."
        )
        self.post_refresh_wait = QSpinBox()
        self.post_refresh_wait.setRange(0, 3600)
        self.post_refresh_wait.setSuffix(" s")
        self.post_refresh_wait.setSpecialValueText("(none)")
        self.post_refresh_wait.setValue(10)
        self.post_refresh_wait.setToolTip(
            "Extra wait after the data refresh completes, before freezing/exporting. Use "
            "this when the workbook relies on Excel add-ins that load data asynchronously "
            "— e.g. PI DataLink — and the output would otherwise capture incomplete data."
        )
        self.fail_if_empty = QCheckBox("Fail the run if a selected sheet comes out empty")
        self.fail_if_empty.setChecked(True)
        self.fail_if_empty.setToolTip(
            "Safety net: if a selected sheet contains no data at all after refresh, the "
            "run fails with a clear error instead of emailing a blank report."
        )
        self.fail_if_errors = QCheckBox("Fail the run if a selected sheet has error cells (strict)")
        self.fail_if_errors.setChecked(False)
        self.fail_if_errors.setToolTip(
            "STRICT (off by default): fail the run if a selected sheet contains Excel errors "
            "(#REF!, #NAME?, …). Off = the report is delivered anyway and the error cells are "
            "reported as a warning; use 'Blank out values' below to strip specific errors."
        )
        # One control for what happens to the sheets you did NOT select. Keep-all and Hide
        # both retain every sheet in the file (Hide just makes the extras very-hidden);
        # Remove deletes them. Data is derived into the two config fields in payload().
        self.nonselected_mode = QComboBox()
        self.nonselected_mode.addItem("Keep all sheets (visible)", "keep")
        self.nonselected_mode.addItem("Remove them (smaller file)", "remove")
        self.nonselected_mode.addItem("Hide them (kept in file, always opens)", "hide")
        self.nonselected_mode.setCurrentIndex(1)  # default Remove — matches JobConfig default
        self.nonselected_mode.setToolTip(
            "What to do in the OUTPUT copy with the sheets you did not select (the source is "
            "never modified):\n"
            "• Keep all — leave every sheet visible.\n"
            "• Remove — delete them for a smaller file (can break charts/defined names that "
            "referenced them, so Office may refuse to open the output).\n"
            "• Hide — keep every sheet in the file but make the non-selected ones very-hidden; "
            "references stay intact and the file always opens, but the raw data stays inside it."
        )
        self.blank_values = QLineEdit()
        self.blank_values.setPlaceholderText("#REF!, #N/A, Tag not found, No Data")
        self.blank_values.setToolTip(
            "Comma-separated cell values to blank out of the output after saving — error "
            "codes (#REF!, #N/A, #NAME?) or PI DataLink strings. Leave empty to keep everything."
        )
        self.notes = QPlainTextEdit()
        self.notes.setToolTip("Free-form description of this job.")

        adv_form.addRow("Timeout", self.timeout)
        adv_form.addRow("Concurrency group", self.group)
        adv_form.addRow("Extra wait after refresh", self.post_refresh_wait)
        adv_form.addRow("", self.fail_if_empty)
        adv_form.addRow("", self.fail_if_errors)
        adv_form.addRow("Non-selected sheets", self.nonselected_mode)
        adv_form.addRow("Blank out values", self.blank_values)
        adv_form.addRow("Notes", self.notes)

        self.tabs.addTab(general_tab, "General")
        self.tabs.addTab(output_tab, "Output")
        self.tabs.addTab(schedule_tab, "Schedule")
        self.tabs.addTab(email_tab, "Email")
        self.tabs.addTab(advanced_tab, "Advanced")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        outer.addWidget(self.tabs)
        outer.addWidget(buttons)

    def _update_email_hint(self, checked: bool) -> None:
        if checked:
            self.email_hint.setText(
                "Successful scheduled and manual Runs will email the Production recipients. "
                "Test email runs still go only to the Test recipients."
            )
        else:
            self.email_hint.setText(
                "Scheduled and manual Runs will build the report but email NO ONE (not even "
                "the Test recipients). Only a Test email run sends mail, to the Test "
                "recipients. Tick this to also email Production on real/scheduled runs."
            )

    # -- actions -----------------------------------------------------------------

    def _pick_input_excel(self) -> None:
        # Reopen at the currently-selected file's folder, else the Downloads folder.
        start = open_start_dir(self.input_excel.text().strip())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Excel file", start, "Excel (*.xlsx *.xlsm)"
        )
        if path:
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
        checked = self._checked_sheet_names()
        self.sheets.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked
            )
            self.sheets.addItem(item)

    def _update_output_example(self) -> None:
        job = self.name.text().strip() or "job"
        now = datetime.now()
        stem = self.output_name.text().strip() or "{job}_{date}"
        stem = stem.replace("{job}", job).replace("{date}", now.strftime("%Y%m%d"))
        stem = stem.replace("{datetime}", now.strftime("%Y%m%d_%H%M%S"))
        stem = stem.replace("{run_id}", "a1b2c3")
        folder = self.output_dir.text().strip() or "(input file's folder)"
        example = f"→ {folder}\\{stem}.xlsx"
        if self.gen_pdf.isChecked():
            example += f", {stem}_<sheet>.pdf"
        self.output_example.setText(example)

    def _edit_template(self) -> None:
        existing = self._template_html or ""
        if not existing and self._editing:
            try:
                existing = self._api.get_email_template(self.name.text().strip()).get("content", "")
            except ApiError:
                existing = ""
        dlg = EmailTemplateDialog(existing, self.name.text().strip(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._template_html = dlg.result_html()
            self.template_status.setText("Custom template ready — saved with the job.")

    def _checked_sheet_names(self) -> list[str]:
        result = []
        for i in range(self.sheets.count()):
            item = self.sheets.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result

    def _on_save(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Validation", "Job name is required.")
            return
        if not self.input_excel.text().strip():
            QMessageBox.warning(self, "Validation", "Select the input Excel file.")
            return
        if not self._checked_sheet_names():
            QMessageBox.warning(self, "Validation", "Select at least one sheet.")
            return
        if not _split_csv(self.prod_to.text()):
            QMessageBox.warning(self, "Validation", "Prod: To is required.")
            return
        if not _split_csv(self.test_to.text()):
            QMessageBox.warning(self, "Validation", "Test: To is required.")
            return
        try:
            self.schedule.to_crons()
        except ValueError as e:
            QMessageBox.warning(self, "Schedule", str(e))
            return
        self.accept()

    # -- payload -----------------------------------------------------------------

    def payload(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name.text().strip(),
            "enabled": self.enabled.isChecked(),
            "input_excel_path": self.input_excel.text().strip(),
            "output_dir": self.output_dir.text().strip() or None,
            "output_name": self.output_name.text().strip() or None,
            "sheet_names": self._checked_sheet_names(),
            "freeze_values": self.freeze.isChecked(),
            "generate_pdf": self.gen_pdf.isChecked(),
            "schedule_crons": self.schedule.to_crons(),
            "timeout_seconds": self.timeout.value() or None,
            "concurrency_group": self.group.text().strip() or None,
            "post_refresh_wait_seconds": self.post_refresh_wait.value(),
            "fail_if_sheet_empty": self.fail_if_empty.isChecked(),
            "fail_if_sheet_has_errors": self.fail_if_errors.isChecked(),
            # One dropdown -> two config fields. "keep" leaves all sheets; "remove"/"hide"
            # prune to the selected ones (mode says how). Hide is only meaningful when pruning.
            "keep_only_selected_sheets": self.nonselected_mode.currentData() != "keep",
            "unselected_sheets_mode": (
                "hide" if self.nonselected_mode.currentData() == "hide" else "remove"
            ),
            "blank_out_values": _split_csv(self.blank_values.text()),
            "subject": self.subject.text().strip() or None,
            "send_report_email": self.send_email.isChecked(),
            "prod": {
                "to": _split_csv(self.prod_to.text()),
                "cc": _split_csv(self.prod_cc.text()),
                "bcc": _split_csv(self.prod_bcc.text()),
            },
            "test": {
                "to": _split_csv(self.test_to.text()),
                "cc": _split_csv(self.test_cc.text()),
                "bcc": _split_csv(self.test_bcc.text()),
            },
            "notes": self.notes.toPlainText().strip(),
        }
        # Preserve a previously configured template file path (payload rebuilds the job).
        if self._existing_template_path:
            data["email_template_path"] = self._existing_template_path
        return data

    def template_html(self) -> str | None:
        """The in-app authored template source, or None when unchanged."""
        return self._template_html

    def _load(self, job: dict[str, Any]) -> None:
        self.name.setText(job.get("name", ""))
        self.name.setReadOnly(True)  # name is the key; edit via delete+recreate
        self.enabled.setChecked(job.get("enabled", True))
        self.input_excel.setText(job.get("input_excel_path", ""))
        self.output_dir.setText(job.get("output_dir") or "")
        self.output_name.setText(job.get("output_name") or "")
        self.freeze.setChecked(job.get("freeze_values", True))
        self.gen_pdf.setChecked(job.get("generate_pdf", True))
        self.schedule.load(job.get("schedule_crons") or [])
        self.timeout.setValue(job.get("timeout_seconds") or 0)
        self.group.setText(job.get("concurrency_group") or "")
        self.post_refresh_wait.setValue(job.get("post_refresh_wait_seconds") or 0)
        self.fail_if_empty.setChecked(job.get("fail_if_sheet_empty", True))
        self.fail_if_errors.setChecked(job.get("fail_if_sheet_has_errors", False))
        # Rebuild the single dropdown from the two stored fields.
        if not job.get("keep_only_selected_sheets", True):
            nonselected = "keep"
        else:
            nonselected = "hide" if job.get("unselected_sheets_mode") == "hide" else "remove"
        mode_index = self.nonselected_mode.findData(nonselected)
        self.nonselected_mode.setCurrentIndex(mode_index if mode_index >= 0 else 1)
        self.blank_values.setText(_join_csv(job.get("blank_out_values")))
        self.notes.setPlainText(job.get("notes", ""))
        self.subject.setText(job.get("subject") or "")
        self.send_email.setChecked(job.get("send_report_email", False))
        self._existing_template_path = job.get("email_template_path")
        if self._existing_template_path:
            self.template_status.setText("This job has a custom template.")

        prod = job.get("prod", {})
        self.prod_to.setText(_join_csv(prod.get("to")))
        self.prod_cc.setText(_join_csv(prod.get("cc")))
        self.prod_bcc.setText(_join_csv(prod.get("bcc")))
        test = job.get("test", {})
        self.test_to.setText(_join_csv(test.get("to")))
        self.test_cc.setText(_join_csv(test.get("cc")))
        self.test_bcc.setText(_join_csv(test.get("bcc")))

        for name in job.get("sheet_names", []):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.sheets.addItem(item)

"""Job editor dialog — grouped sections (Input / Output / Schedule / Email / Advanced).

Everything non-mandatory is optional. Outputs are a folder + optional filename stem; the
schedule is built visually; the email body is authored in-app via EmailTemplateDialog.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError
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
        self.resize(660, 760)
        self._build()
        if job:
            self._load(job)
        self._update_output_example()

    # -- construction ------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        page = QVBoxLayout(content)

        # ---- Input ----
        input_box = QGroupBox("Input")
        input_form = QFormLayout(input_box)

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
        self.sheets.setMaximumHeight(110)
        self.sheets.setToolTip("Tick the sheets this job should refresh, freeze, and export.")

        input_form.addRow("Job name", name_row)
        input_form.addRow("Input Excel file", wb_row)
        input_form.addRow("Sheets", self.sheets)

        # ---- Output ----
        output_box = QGroupBox("Output")
        output_form = QFormLayout(output_box)

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

        # ---- Schedule ----
        schedule_box = QGroupBox("Schedule")
        schedule_lay = QVBoxLayout(schedule_box)
        self.schedule = ScheduleWidget()
        schedule_lay.addWidget(self.schedule)

        # ---- Email ----
        email_box = QGroupBox("Email")
        email_form = QFormLayout(email_box)

        self.subject = QLineEdit()
        self.subject.setToolTip("Email subject; test runs are automatically prefixed [TEST].")
        self.send_email = QCheckBox("Email report to production recipients on real runs")
        self.send_email.setToolTip(
            "When ticked, successful REAL runs email the production recipients. Test runs "
            "always email the test recipients regardless."
        )

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
        email_form.addRow("Prod: To", self.prod_to)
        email_form.addRow("Prod: Cc (optional)", self.prod_cc)
        email_form.addRow("Prod: Bcc (optional)", self.prod_bcc)
        email_form.addRow("Test: To", self.test_to)
        email_form.addRow("Test: Cc (optional)", self.test_cc)
        email_form.addRow("Test: Bcc (optional)", self.test_bcc)
        email_form.addRow("Body", tpl_row)

        # ---- Advanced (collapsible) ----
        self.advanced_box = QGroupBox("Advanced")
        self.advanced_box.setCheckable(True)
        self.advanced_box.setChecked(False)
        self.advanced_box.setToolTip("Optional tuning — most jobs don't need these.")
        adv_form = QFormLayout(self.advanced_box)

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
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(56)
        self.notes.setToolTip("Free-form description of this job.")

        adv_form.addRow("Timeout", self.timeout)
        adv_form.addRow("Concurrency group", self.group)
        adv_form.addRow("Notes", self.notes)
        self._adv_form = adv_form
        self.advanced_box.toggled.connect(self._toggle_advanced)
        self._toggle_advanced(False)

        page.addWidget(input_box)
        page.addWidget(output_box)
        page.addWidget(schedule_box)
        page.addWidget(email_box)
        page.addWidget(self.advanced_box)
        page.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        outer.addWidget(scroll)
        outer.addWidget(buttons)

    def _toggle_advanced(self, on: bool) -> None:
        for row in range(self._adv_form.rowCount()):
            for role in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole):
                item = self._adv_form.itemAt(row, role)
                widget = item.widget() if item is not None else None
                if widget is not None:
                    widget.setVisible(on)

    # -- actions -----------------------------------------------------------------

    def _pick_input_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Excel file", "", "Excel (*.xlsx *.xlsm)"
        )
        if path:
            self.input_excel.setText(path)
            self._discover_sheets()
            self._update_output_example()

    def _pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output folder")
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
        timeout = job.get("timeout_seconds") or 0
        self.timeout.setValue(timeout)
        self.group.setText(job.get("concurrency_group") or "")
        self.notes.setPlainText(job.get("notes", ""))
        if timeout or job.get("concurrency_group") or job.get("notes"):
            self.advanced_box.setChecked(True)
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

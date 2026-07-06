"""Job editor dialog: workbook picker, dynamic sheet discovery, To/CC/BCC, email preview."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError


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
        self.setWindowTitle("Edit Job" if self._editing else "New Job")
        self.resize(560, 720)
        self._build()
        if job:
            self._load(job)

    # -- construction ------------------------------------------------------------

    def _build(self) -> None:
        form = QFormLayout()

        self.name = QLineEdit()
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(True)

        self.workbook = QLineEdit()
        browse_wb = QPushButton("Browse…")
        browse_wb.clicked.connect(self._pick_workbook)
        discover = QPushButton("Discover sheets")
        discover.clicked.connect(self._discover_sheets)
        wb_row = QHBoxLayout()
        wb_row.addWidget(self.workbook)
        wb_row.addWidget(browse_wb)
        wb_row.addWidget(discover)

        self.sheets = QListWidget()
        self.sheets.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        self.output_xlsx = QLineEdit()
        self.output_pdf = QLineEdit()
        self.output_pdf.setPlaceholderText(r"e.g. C:\Reports\{date}_{sheet}.pdf")

        self.freeze = QCheckBox("Freeze formulas to values")
        self.freeze.setChecked(True)
        self.gen_pdf = QCheckBox("Generate PDF (one per sheet)")
        self.gen_pdf.setChecked(True)

        self.cron = QLineEdit()
        self.cron.setPlaceholderText("min hour dom mon dow  (e.g. 0 6 * * MON-FRI)")
        self.timeout = QSpinBox()
        self.timeout.setRange(0, 86400)
        self.timeout.setSpecialValueText("(use default)")
        self.group = QLineEdit()

        self.subject = QLineEdit()
        self.send_email = QCheckBox("Email report to production recipients on real runs")

        self.prod_to = QLineEdit()
        self.prod_cc = QLineEdit()
        self.prod_bcc = QLineEdit()
        self.test_to = QLineEdit()
        self.test_cc = QLineEdit()
        self.test_bcc = QLineEdit()

        self.email_template = QLineEdit()
        browse_tpl = QPushButton("Browse…")
        browse_tpl.clicked.connect(self._pick_template)
        preview = QPushButton("Preview")
        preview.clicked.connect(self._preview_email)
        tpl_row = QHBoxLayout()
        tpl_row.addWidget(self.email_template)
        tpl_row.addWidget(browse_tpl)
        tpl_row.addWidget(preview)

        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(60)

        form.addRow("Job name", self.name)
        form.addRow("", self.enabled)
        form.addRow("Workbook template", wb_row)
        form.addRow("Sheets", self.sheets)
        form.addRow("Output Excel path", self.output_xlsx)
        form.addRow("Output PDF path", self.output_pdf)
        form.addRow("", self.freeze)
        form.addRow("", self.gen_pdf)
        form.addRow("Schedule (cron)", self.cron)
        form.addRow("Timeout (seconds)", self.timeout)
        form.addRow("Concurrency group", self.group)
        form.addRow("Subject", self.subject)
        form.addRow("", self.send_email)
        form.addRow("Prod: To", self.prod_to)
        form.addRow("Prod: Cc (optional)", self.prod_cc)
        form.addRow("Prod: Bcc (optional)", self.prod_bcc)
        form.addRow("Test: To", self.test_to)
        form.addRow("Test: Cc (optional)", self.test_cc)
        form.addRow("Test: Bcc (optional)", self.test_bcc)
        form.addRow("Email template (optional)", tpl_row)
        form.addRow("Notes", self.notes)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    # -- actions -----------------------------------------------------------------

    def _pick_workbook(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select workbook", "", "Excel (*.xlsx *.xlsm)")
        if path:
            self.workbook.setText(path)
            self._discover_sheets()

    def _pick_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select email template", "", "HTML (*.html *.htm)"
        )
        if path:
            self.email_template.setText(path)

    def _discover_sheets(self) -> None:
        path = self.workbook.text().strip()
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

    def _preview_email(self) -> None:
        from reportflow.core.config.defaults import DEFAULT_EMAIL_TEMPLATE
        from reportflow.core.email.render import render_email, sample_context

        tpl_path = self.email_template.text().strip()
        try:
            source = (
                Path(tpl_path).read_text(encoding="utf-8")
                if tpl_path and Path(tpl_path).exists()
                else DEFAULT_EMAIL_TEMPLATE
            )
            html = render_email(source, sample_context())
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Preview failed", str(e))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Email preview")
        dlg.resize(600, 500)
        browser = QTextBrowser(dlg)
        browser.setHtml(html)
        lay = QVBoxLayout(dlg)
        lay.addWidget(browser)
        dlg.exec()

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
        if not self._checked_sheet_names():
            QMessageBox.warning(self, "Validation", "Select at least one sheet.")
            return
        if not _split_csv(self.prod_to.text()):
            QMessageBox.warning(self, "Validation", "Prod: To is required.")
            return
        self.accept()

    # -- payload -----------------------------------------------------------------

    def payload(self) -> dict[str, Any]:
        timeout = self.timeout.value() or None
        pdf = self.output_pdf.text().strip() or None
        tpl = self.email_template.text().strip() or None
        job: dict[str, Any] = {
            "name": self.name.text().strip(),
            "enabled": self.enabled.isChecked(),
            "workbook_template_path": self.workbook.text().strip(),
            "output_xlsx_path": self.output_xlsx.text().strip(),
            "output_pdf_path": pdf,
            "sheet_names": self._checked_sheet_names(),
            "freeze_values": self.freeze.isChecked(),
            "generate_pdf": self.gen_pdf.isChecked(),
            "schedule_cron": self.cron.text().strip() or None,
            "timeout_seconds": timeout,
            "concurrency_group": self.group.text().strip() or None,
            "subject": self.subject.text().strip() or None,
            "send_report_email": self.send_email.isChecked(),
            "email_template_path": tpl,
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
        return job

    def _load(self, job: dict[str, Any]) -> None:
        self.name.setText(job.get("name", ""))
        self.name.setReadOnly(True)  # name is the key; edit via delete+recreate
        self.enabled.setChecked(job.get("enabled", True))
        self.workbook.setText(job.get("workbook_template_path", ""))
        self.output_xlsx.setText(job.get("output_xlsx_path", ""))
        self.output_pdf.setText(job.get("output_pdf_path") or "")
        self.freeze.setChecked(job.get("freeze_values", True))
        self.gen_pdf.setChecked(job.get("generate_pdf", True))
        self.cron.setText(job.get("schedule_cron") or "")
        self.timeout.setValue(job.get("timeout_seconds") or 0)
        self.group.setText(job.get("concurrency_group") or "")
        self.subject.setText(job.get("subject") or "")
        self.send_email.setChecked(job.get("send_report_email", False))
        self.email_template.setText(job.get("email_template_path") or "")
        self.notes.setPlainText(job.get("notes", ""))

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

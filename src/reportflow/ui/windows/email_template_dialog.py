"""In-app email template editor: Simple (plain text) or HTML mode, with live preview.

The result is HTML template source (Jinja2 placeholders); Simple mode wraps the text into
the default scaffold on save. The caller persists it via PUT /jobs/{name}/email-template.
"""

from __future__ import annotations

import html as html_mod

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from reportflow.core.config.defaults import DEFAULT_EMAIL_TEMPLATE
from reportflow.core.email.render import render_email, sample_context

_PLACEHOLDERS = [
    ("Job name", "{{ job_name }}"),
    ("Status", "{{ status }}"),
    ("Run ID", "{{ run_id }}"),
    ("Started", "{{ started_at }}"),
    ("Finished", "{{ finished_at }}"),
    ("Duration", "{{ duration_seconds }}"),
    ("Sheets", '{{ sheet_names | join(", ") }}'),
    ("Host", "{{ hostname }}"),
]

_SIMPLE_SCAFFOLD = """\
<!doctype html>
<html>
  <body style="font-family: Segoe UI, Arial, sans-serif; color: #1a1a1a;">
{body}
    {{% if is_test %}}
    <p style="color: #b00; font-weight: bold;">*** TEST RUN — internal recipients only ***</p>
    {{% endif %}}
    <p style="color: #999; font-size: 12px;">Generated automatically by ReportFlow.</p>
  </body>
</html>
"""


def _wrap_simple(text: str) -> str:
    """Wrap plain text (with Jinja2 placeholders) into the default HTML scaffold."""
    paragraphs = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        # Escape HTML but keep the {{ ... }} / {% ... %} placeholders intact.
        escaped = html_mod.escape(block).replace("\n", "<br>")
        escaped = escaped.replace("&#x27;", "'").replace("&quot;", '"')
        paragraphs.append(f"    <p>{escaped}</p>")
    return _SIMPLE_SCAFFOLD.format(body="\n".join(paragraphs))


class EmailTemplateDialog(QDialog):
    """Edit a job's email body. ``result_html()`` returns the template source to save."""

    def __init__(
        self,
        existing_html: str = "",
        job_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Email template — {job_name}" if job_name else "Email template")
        self.resize(760, 620)
        self._build(existing_html)

    def _build(self, existing_html: str) -> None:
        layout = QVBoxLayout(self)

        hint = QLabel(
            "Write the email body in <b>Simple</b> mode (plain text) or switch to "
            "<b>HTML</b> for full control. Click a placeholder button to insert a value "
            "that is filled in at send time."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        chips = QHBoxLayout()
        chips.addWidget(QLabel("Insert:"))
        for label, token in _PLACEHOLDERS:
            btn = QPushButton(label)
            btn.setToolTip(f"Insert {token}")
            btn.clicked.connect(lambda *_, t=token: self._insert(t))
            chips.addWidget(btn)
        chips.addStretch()
        layout.addLayout(chips)

        self.tabs = QTabWidget()
        self.simple_edit = QPlainTextEdit()
        self.simple_edit.setPlaceholderText(
            "Hello,\n\nThe {{ job_name }} report finished with status {{ status }}.\n\n"
            "Regards,\nReportFlow"
        )
        self.simple_edit.setToolTip("Plain text; blank lines separate paragraphs.")
        self.html_edit = QPlainTextEdit()
        self.html_edit.setToolTip("Raw HTML template source (Jinja2 placeholders supported).")
        self.tabs.addTab(self.simple_edit, "Simple")
        self.tabs.addTab(self.html_edit, "HTML")
        layout.addWidget(self.tabs, 2)

        if existing_html.strip():
            self.html_edit.setPlainText(existing_html)
            self.tabs.setCurrentWidget(self.html_edit)
        else:
            self.html_edit.setPlainText(DEFAULT_EMAIL_TEMPLATE)

        preview_btn = QPushButton("Preview")
        preview_btn.setProperty("accent", True)
        preview_btn.setToolTip("Render the template with sample data.")
        preview_btn.clicked.connect(self._preview)

        self.preview = QTextBrowser()
        self.preview.setPlaceholderText("Click Preview to render the email with sample data.")
        layout.addWidget(preview_btn)
        layout.addWidget(self.preview, 2)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- behavior ----------------------------------------------------------------

    def _insert(self, token: str) -> None:
        editor = (
            self.simple_edit if self.tabs.currentWidget() is self.simple_edit else self.html_edit
        )
        editor.insertPlainText(token)
        editor.setFocus()

    def result_html(self) -> str:
        if self.tabs.currentWidget() is self.simple_edit:
            return _wrap_simple(self.simple_edit.toPlainText())
        return self.html_edit.toPlainText()

    def _preview(self) -> None:
        try:
            rendered = render_email(self.result_html(), sample_context())
        except Exception as e:  # noqa: BLE001 — template errors surface to the author
            QMessageBox.warning(self, "Template error", str(e))
            return
        self.preview.setHtml(rendered)

    def _on_save(self) -> None:
        source = self.result_html()
        if not source.strip():
            QMessageBox.warning(self, "Validation", "The template is empty.")
            return
        try:
            render_email(source, sample_context())  # syntax check before saving
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Template error", f"The template does not render:\n{e}")
            return
        self.accept()

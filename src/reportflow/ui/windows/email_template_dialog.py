"""In-app email template editor: Simple (plain text) or HTML mode, with live preview.

The result is HTML template source (Jinja2 placeholders); Simple mode wraps the text into
the default scaffold on save. The caller persists it via PUT /jobs/{name}/email-template.

An .html file can be loaded instead: either imported (a copy is saved with the job, like
in-app text) or kept LINKED — the job then points at the file and every run re-reads it, so
edits made to the file outside ReportFlow are picked up. ``linked_path()`` reports that.
"""

from __future__ import annotations

import html as html_mod
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from reportflow.core.config.defaults import DEFAULT_EMAIL_TEMPLATE
from reportflow.core.email.render import PLACEHOLDERS, render_email, sample_context
from reportflow.ui.fs_util import open_start_dir

_TOKEN_ROLE = Qt.ItemDataRole.UserRole

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
        *,
        linked_path: str | None = None,
        check_path: Callable[[str], object] | None = None,
    ) -> None:
        """``linked_path``: the job is linked to this file (opens in linked mode).
        ``check_path(path)`` raises with a reason when the SERVICE can't use the file —
        linking is only allowed once it passes."""
        super().__init__(parent)
        self.setWindowTitle(f"Email template — {job_name}" if job_name else "Email template")
        self.resize(820, 640)
        self._check_path = check_path
        self._file_path: str | None = linked_path
        self._build(existing_html)
        if linked_path:
            self.keep_linked.setChecked(True)
        self._sync_link_ui()

    def _build(self, existing_html: str) -> None:
        layout = QVBoxLayout(self)

        hint = QLabel(
            "Write the email body in <b>Simple</b> mode (plain text) or switch to "
            "<b>HTML</b> for full control. Click a placeholder on the right to insert a value "
            "that is filled in at send time (they work in the job's Subject too)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        file_row = QHBoxLayout()
        load = QPushButton("Load from file…")
        load.setToolTip("Use an .html file you made elsewhere as this job's email body.")
        load.clicked.connect(self._pick_file)
        self.keep_linked = QCheckBox("Keep linked to this file")
        self.keep_linked.setToolTip(
            "Ticked: the job keeps pointing at the file and every run reads it again, so "
            "edits you make to the file are used automatically. The ReportFlow service must "
            "be able to read it (a shared folder works best).\n"
            "Unticked: a copy is saved with the job; later edits to the file are ignored."
        )
        self.keep_linked.toggled.connect(self._sync_link_ui)
        self.file_label = QLabel("")
        self.file_label.setProperty("muted", True)
        self.file_label.setWordWrap(True)
        file_row.addWidget(load)
        file_row.addWidget(self.keep_linked)
        file_row.addWidget(self.file_label, 1)
        layout.addLayout(file_row)

        body = QHBoxLayout()
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
        body.addWidget(self.tabs, 3)

        # Placeholders: one click inserts; each shows what it turns into today.
        side = QVBoxLayout()
        side.addWidget(QLabel("<b>Placeholders</b> — click to insert"))
        self.placeholders = QListWidget()
        self.placeholders.setToolTip("Click a placeholder to insert it at the cursor.")
        samples = sample_context()
        group = ""
        for item_group, label, token, about in PLACEHOLDERS:
            if item_group != group:
                group = item_group
                header = QListWidgetItem(group)
                header.setFlags(Qt.ItemFlag.NoItemFlags)  # a heading, not a placeholder
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                self.placeholders.addItem(header)
            try:
                example = "" if group == "Blocks" else render_email(token, samples)
            except Exception:  # noqa: BLE001 — a sample must never break the dialog
                example = ""
            text = f"{label} — {example}" if example else label
            item = QListWidgetItem(text)
            item.setData(_TOKEN_ROLE, token)
            item.setToolTip(f"{token}\n{about}")
            self.placeholders.addItem(item)
        self.placeholders.itemClicked.connect(self._on_placeholder_clicked)
        side.addWidget(self.placeholders, 1)
        how_to = QLabel('<a href="#placeholders">How to use placeholders</a>')
        how_to.setToolTip("Open the Help guide's placeholder section, with examples.")
        how_to.linkActivated.connect(self._open_placeholder_help)
        side.addWidget(how_to)
        body.addLayout(side, 2)
        layout.addLayout(body, 2)

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
        # Emails are designed on white — the preview is a deliberate light island inside the
        # dark app so it shows what recipients actually see.
        self.preview.setStyleSheet(
            "QTextBrowser { background: #ffffff; color: #1a1a1a; border: 1px solid #363b47; }"
        )
        layout.addWidget(preview_btn)
        layout.addWidget(self.preview, 2)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- behavior ----------------------------------------------------------------

    def _on_placeholder_clicked(self, item: QListWidgetItem) -> None:
        token = item.data(_TOKEN_ROLE)
        if token:
            self._insert(token)

    def _open_placeholder_help(self, *_: object) -> None:
        from reportflow.ui.windows.help_dialog import HelpDialog

        HelpDialog(self, anchor="placeholders").exec()

    def _insert(self, token: str) -> None:
        editor = (
            self.simple_edit if self.tabs.currentWidget() is self.simple_edit else self.html_edit
        )
        editor.insertPlainText(token)
        editor.setFocus()

    def _pick_file(self) -> None:
        start = open_start_dir(self._file_path or "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Load an email template", start, "HTML (*.html *.htm)"
        )
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> None:
        """Import ``path`` into the HTML editor (and remember it for "Keep linked")."""
        try:
            source = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            QMessageBox.warning(self, "Load from file", f"Could not read the file:\n{e}")
            return
        self._file_path = path
        self.html_edit.setPlainText(source)
        self.tabs.setCurrentWidget(self.html_edit)
        self._sync_link_ui()

    def _sync_link_ui(self) -> None:
        linked = self.keep_linked.isChecked() and bool(self._file_path)
        self.keep_linked.setEnabled(bool(self._file_path))
        # Linked: the FILE is the template — edit it there, not here.
        self.html_edit.setReadOnly(linked)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.simple_edit), not linked)
        if linked:
            self.tabs.setCurrentWidget(self.html_edit)
            self.file_label.setText(
                f"Linked to {self._file_path} — edit that file; every run reads it again."
            )
        elif self._file_path:
            self.file_label.setText(f"Loaded from {Path(self._file_path).name} — saved as a copy.")
        else:
            self.file_label.setText("")

    def linked_path(self) -> str | None:
        """The linked file when "Keep linked" is ticked, else None (save a copy)."""
        if self.keep_linked.isChecked() and self._file_path:
            return self._file_path
        return None

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
        linked = self.linked_path()
        if linked and self._check_path is not None:
            try:
                self._check_path(linked)
            except Exception as e:  # noqa: BLE001 — the service's reason, shown to the user
                QMessageBox.warning(
                    self,
                    "Can't link this file",
                    f"{e}\n\nPut the file somewhere the ReportFlow service can read (e.g. a "
                    "shared folder), or untick 'Keep linked' to save a copy instead.",
                )
                return
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

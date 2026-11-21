"""In-app email template editor: Simple (plain text) or HTML, beside a live preview.

The editor and the preview sit side by side in a large, resizable window; the preview
re-renders a moment after each change and shows the email as recipients get it — subject
(with [TEST] on Testing), To/Cc and body — for either stage, one click apart.

The result is HTML template source (Jinja2 placeholders); Simple mode wraps the text into
the default scaffold on save. The caller persists it via PUT /jobs/{name}/email-template.

An .html file can be loaded instead: either imported (a copy is saved with the job, like
in-app text) or kept LINKED — the job then points at the file and every run re-reads it, so
edits made to the file outside ReportFlow are picked up. ``linked_path()`` reports that.
"""

from __future__ import annotations

import html as html_mod
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from reportflow.core.config.defaults import DEFAULT_EMAIL_TEMPLATE
from reportflow.core.email.render import (
    explain_template_error,
    final_subject,
    render_email,
    sample_context,
)
from reportflow.ui.feedback import FormDialog, toast
from reportflow.ui.fs_util import open_start_dir
from reportflow.ui.placeholder_picker import PlaceholderButton, email_placeholders
from reportflow.ui.widgets import section_title

_PREVIEW_DELAY_MS = 300  # re-render this long after the last keystroke
_EMPTY_PREVIEW = (
    '<p style="color:#888;font-family:Segoe UI,Arial,sans-serif;">Start writing on the left '
    "— the preview follows as you type.</p>"
)

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


def _with_email_header(body: str, subject: str, recipients: dict[str, list[str]]) -> str:
    """Put an email-client style Subject / To / Cc block above the rendered body."""
    rows = [("Subject", subject)]
    for key, label in (("to", "To"), ("cc", "Cc")):
        addresses = recipients.get(key) or []
        if addresses:
            rows.append((label, ", ".join(addresses)))
    lines = "".join(
        f'<tr><td style="color:#666;padding:1px 10px 1px 0;">{label}</td>'
        f"<td>{html_mod.escape(value)}</td></tr>"
        for label, value in rows
    )
    header = (
        '<table cellspacing="0" style="font-family:Segoe UI,Arial,sans-serif;font-size:13px;'
        'margin-bottom:10px;">'
        f"{lines}</table><hr>"
    )
    match = re.search(r"<body[^>]*>", body, flags=re.IGNORECASE)
    if match:
        return body[: match.end()] + header + body[match.end() :]
    return header + body


class EmailTemplateDialog(FormDialog):
    """Edit a job's email body. ``result_html()`` returns the template source to save."""

    def __init__(
        self,
        existing_html: str = "",
        job_name: str = "",
        parent: QWidget | None = None,
        *,
        linked_path: str | None = None,
        check_path: Callable[[str], object] | None = None,
        preview_job: dict[str, Any] | None = None,
    ) -> None:
        """``linked_path``: the job is linked to this file (opens in linked mode).
        ``check_path(path)`` raises with a reason when the SERVICE can't use the file —
        linking is only allowed once it passes. ``preview_job`` is what the job editor has
        on screen (name, subject, stage, sheets, workbooks, recipients per stage), so the
        preview shows this job's email rather than a sample one."""
        super().__init__(parent, settings_key="template_editor")
        self._preview_job = preview_job or {}
        self.setWindowTitle(f"Email template — {job_name}" if job_name else "Email template")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setMinimumSize(900, 600)
        self._size_to_screen()
        self._check_path = check_path
        self._file_path: str | None = linked_path
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(_PREVIEW_DELAY_MS)
        self._render_timer.timeout.connect(self._preview)
        self._build(existing_html)
        if linked_path:
            self.keep_linked.setChecked(True)
        self._sync_link_ui()
        self._preview()
        self.finish_form(self._save_button_widget)

    def _size_to_screen(self) -> None:
        """Big by default — about 85% of the screen — so both panes have real room."""
        owner = self.parentWidget()
        screen = (owner.screen() if owner is not None else None) or (
            QGuiApplication.primaryScreen()
        )
        if screen is None:
            self.resize(1200, 800)
            return
        area = screen.availableGeometry()
        width = min(area.width(), max(1100, int(area.width() * 0.85)))
        height = min(area.height(), max(720, int(area.height() * 0.85)))
        self.resize(width, height)

    # -- construction ------------------------------------------------------------

    def _build(self, existing_html: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Where the body comes from: typed here, or an .html file (copied or linked).
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
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

        # ---- left: the editor ----
        editor_pane = QWidget()
        editor_col = QVBoxLayout(editor_pane)
        editor_col.setContentsMargins(0, 0, 0, 0)
        editor_col.setSpacing(8)
        editor_head = QHBoxLayout()
        editor_head.addWidget(section_title("Message"))
        editor_head.addStretch(1)
        self.insert_placeholder = PlaceholderButton(
            self._current_editor,
            email_placeholders,
            field_name="Email body",
            read_only_message="This template is linked to a file — edit that file instead.",
        )
        editor_head.addWidget(self.insert_placeholder)
        editor_col.addLayout(editor_head)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.tabs = QTabWidget()
        self.simple_edit = QPlainTextEdit()
        self.simple_edit.setPlaceholderText(
            "Hello,\n\nThe {{ job_name }} report finished with status {{ status }}.\n\n"
            "Regards,\nReportFlow"
        )
        self.simple_edit.setToolTip(
            "Plain text; blank lines separate paragraphs. Use Insert placeholder for values "
            "filled in when the email is sent."
        )
        self.html_edit = QPlainTextEdit()
        self.html_edit.setFont(mono)
        self.html_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.html_edit.setToolTip("Raw HTML template source (Jinja2 placeholders supported).")
        self.tabs.addTab(self.simple_edit, "Simple")
        self.tabs.addTab(self.html_edit, "HTML")
        editor_col.addWidget(self.tabs, 1)

        # ---- right: the live preview ----
        preview_pane = QWidget()
        preview_col = QVBoxLayout(preview_pane)
        preview_col.setContentsMargins(0, 0, 0, 0)
        preview_col.setSpacing(8)
        # One click switches what the preview shows: the email Testing-stage runs send (with
        # [TEST] and the test recipients) or the one Production runs send.
        self.preview_testing = QPushButton("Testing")
        self.preview_production = QPushButton("Production")
        self._preview_stage = QButtonGroup(self)
        for button, tip in (
            (self.preview_testing, "Preview the email Testing-stage runs send."),
            (self.preview_production, "Preview the email Production runs send."),
        ):
            button.setCheckable(True)
            button.setProperty("segment", True)  # the checked one shows in the accent colour
            button.setToolTip(tip)
            self._preview_stage.addButton(button)
        live = self._preview_job.get("stage") == "live"
        (self.preview_production if live else self.preview_testing).setChecked(True)
        self._preview_stage.buttonClicked.connect(lambda *_: self._preview())
        preview_head = QHBoxLayout()
        preview_head.setSpacing(8)
        preview_head.addWidget(section_title("Preview"))
        preview_head.addStretch(1)
        preview_as = QLabel("Show the email as")
        preview_as.setProperty("muted", True)
        preview_head.addWidget(preview_as)
        segments = QHBoxLayout()
        segments.setSpacing(0)
        segments.addWidget(self.preview_testing)
        segments.addWidget(self.preview_production)
        self.preview_testing.setProperty("segmentPos", "first")
        self.preview_production.setProperty("segmentPos", "last")
        preview_head.addLayout(segments)
        preview_col.addLayout(preview_head)
        self.preview_error = QLabel("")
        self.preview_error.setObjectName("previewError")
        self.preview_error.setWordWrap(True)
        self.preview_error.hide()
        preview_col.addWidget(self.preview_error)
        self.preview = QTextBrowser()
        self.preview.setObjectName("emailPreview")
        self.preview.setOpenExternalLinks(False)
        # Emails are designed on white — the preview is a deliberate light island inside the
        # dark app so it shows what recipients actually see.
        self.preview.setStyleSheet(
            "QTextBrowser { background: #ffffff; color: #1a1a1a; border: 1px solid #363b47; "
            "border-radius: 6px; padding: 8px; }"
        )
        preview_col.addWidget(self.preview, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        self.splitter.addWidget(editor_pane)
        self.splitter.addWidget(preview_pane)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter, 1)

        if existing_html.strip():
            self.html_edit.setPlainText(existing_html)
            self.tabs.setCurrentWidget(self.html_edit)
        else:
            self.html_edit.setPlainText(DEFAULT_EMAIL_TEMPLATE)
        for editor in (self.simple_edit, self.html_edit):
            editor.textChanged.connect(self._render_timer.start)
        self.tabs.currentChanged.connect(lambda *_: self._preview())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        self._save_button_widget = buttons.button(QDialogButtonBox.StandardButton.Save)
        self._save_button_widget.setProperty("accent", True)
        layout.addWidget(buttons)

    # -- form behaviour (FormDialog) ------------------------------------------------

    def help_anchor(self) -> str | None:
        return "placeholders"

    def save_form(self) -> None:
        self._on_save()

    def dirty_key(self) -> str:
        return "\x00".join(
            [
                str(self.tabs.currentIndex()),
                self.simple_edit.toPlainText(),
                self.html_edit.toPlainText(),
                str(self.linked_path()),
            ]
        )

    # -- behavior ----------------------------------------------------------------

    def _simple_is_empty(self) -> bool:
        on_simple = self.tabs.currentWidget() is self.simple_edit
        return on_simple and not self.simple_edit.toPlainText().strip()

    def _current_editor(self) -> QPlainTextEdit:
        return self.simple_edit if self.tabs.currentWidget() is self.simple_edit else self.html_edit

    def _insert(self, token: str) -> None:
        editor = self._current_editor()
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
            toast(self, f"Couldn't read {Path(path).name}: {e}", "error")
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

    def preview_is_test(self) -> bool:
        return not self.preview_production.isChecked()

    def _show_error(self, message: str) -> None:
        self.preview_error.setText(message)
        self.preview_error.setVisible(bool(message))

    def _preview(self) -> None:
        """Render the email as recipients get it. Called on its own as the template changes."""
        self._render_timer.stop()
        if self._simple_is_empty():
            self._show_error("")
            self.preview.setHtml(_EMPTY_PREVIEW)
            return
        is_test = self.preview_is_test()
        job = self._preview_job
        name = str(job.get("name") or "") or None
        context = sample_context(
            is_test=is_test,
            job_name=name,
            subject=job.get("subject") or None,
            sheet_names=job.get("sheets") or None,
            workbooks=job.get("workbooks") or None,
        )
        try:
            rendered = render_email(self.result_html(), context)
        except Exception as e:  # noqa: BLE001 — shown above the preview; the last good one stays
            self._show_error(_describe_template_error(e))
            return
        self._show_error("")
        subject = final_subject(
            job.get("subject") or None, context["job_name"], context, is_test=is_test
        )
        recipients = (job.get("recipients") or {}).get("testing" if is_test else "live") or {}
        scroll = self.preview.verticalScrollBar()
        position = scroll.value() if scroll is not None else 0
        self.preview.setHtml(_with_email_header(rendered, subject, recipients))
        if scroll is not None:
            scroll.setValue(position)  # typing must not jump the preview back to the top

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
        if self._simple_is_empty():
            self._show_error("The message is empty — write something, or switch to HTML.")
            self.simple_edit.setFocus()
            return
        if not source.strip():
            self._show_error("The template is empty.")
            return
        try:
            render_email(source, sample_context())  # syntax check before saving
        except Exception as e:  # noqa: BLE001
            self._show_error(_describe_template_error(e))
            self._current_editor().setFocus()
            return
        self.accept()


def _describe_template_error(error: Exception) -> str:
    """A placeholder mistake in words, with its line when Jinja knows it."""
    line = getattr(error, "lineno", None)
    message = explain_template_error(getattr(error, "message", None) or str(error))
    where = f"Line {line}: " if line else ""
    return f"The template has a mistake — {where}{message}"

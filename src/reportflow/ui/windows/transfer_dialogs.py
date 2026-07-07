"""Import/export flows for jobs and settings (Qt side; pure logic in ui.transfer)."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.transfer import (
    TransferError,
    copy_name,
    export_jobs,
    export_settings,
    parse_jobs_file,
    parse_settings_file,
)


class _SelectListDialog(QDialog):
    """A checkbox list of names with Select all / none. Used by both export and import."""

    def __init__(
        self,
        title: str,
        prompt: str,
        names: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(380, 380)
        layout = QVBoxLayout(self)
        label = QLabel(prompt)
        label.setWordWrap(True)
        layout.addWidget(label)

        self.list = QListWidget()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        layout.addWidget(self.list)

        toggle = QPushButton("Select all / none")
        toggle.clicked.connect(self._toggle)
        layout.addWidget(toggle)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle(self) -> None:
        all_checked = all(
            self.list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self.list.count())
        )
        state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)

    def _on_ok(self) -> None:
        if not self.selected():
            QMessageBox.information(self, "Nothing selected", "Tick at least one entry.")
            return
        self.accept()

    def selected(self) -> list[str]:
        return [
            self.list.item(i).text()
            for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.CheckState.Checked
        ]


# -- jobs ---------------------------------------------------------------------------


def export_jobs_flow(api: ApiClient, parent: QWidget) -> None:
    try:
        names = [j["name"] for j in api.list_jobs()]
    except ApiError as e:
        QMessageBox.warning(parent, "Export jobs", str(e))
        return
    if not names:
        QMessageBox.information(parent, "Export jobs", "There are no jobs to export.")
        return

    dlg = _SelectListDialog("Export jobs", "Choose the jobs to export:", names, parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    selected = dlg.selected()

    path, _ = QFileDialog.getSaveFileName(
        parent, "Export jobs", "reportflow-jobs.json", "JSON (*.json)"
    )
    if not path:
        return
    try:
        jobs = [api.get_job(name)["job"] for name in selected]
        Path(path).write_text(json.dumps(export_jobs(jobs), indent=2), encoding="utf-8")
    except (ApiError, OSError) as e:
        QMessageBox.warning(parent, "Export jobs", f"Export failed: {e}")
        return
    QMessageBox.information(parent, "Export jobs", f"Exported {len(jobs)} job(s) to:\n{path}")


def import_jobs_flow(api: ApiClient, parent: QWidget) -> bool:
    """Returns True when at least one job was imported (caller refreshes)."""
    path, _ = QFileDialog.getOpenFileName(parent, "Import jobs", "", "JSON (*.json)")
    if not path:
        return False
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        jobs = parse_jobs_file(data)
    except (OSError, json.JSONDecodeError, TransferError) as e:
        QMessageBox.warning(parent, "Import jobs", f"Cannot import this file: {e}")
        return False

    dlg = _SelectListDialog(
        "Import jobs",
        f"Found {len(jobs)} job(s) in the file. Choose which to import:",
        [j.name for j in jobs],
        parent,
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    chosen = {n.casefold() for n in dlg.selected()}

    try:
        existing = {j["name"] for j in api.list_jobs()}
    except ApiError as e:
        QMessageBox.warning(parent, "Import jobs", str(e))
        return False
    existing_fold = {e.casefold() for e in existing}

    imported, skipped = [], []
    for job in jobs:
        if job.name.casefold() not in chosen:
            continue
        payload = job.model_dump(mode="json")
        if job.name.casefold() in existing_fold:
            choice = QMessageBox(parent)
            choice.setWindowTitle("Job already exists")
            choice.setText(f"A job named {job.name!r} already exists.")
            overwrite = choice.addButton("Overwrite", QMessageBox.ButtonRole.AcceptRole)
            as_copy = choice.addButton("Import as copy", QMessageBox.ButtonRole.ActionRole)
            choice.addButton("Skip", QMessageBox.ButtonRole.RejectRole)
            choice.exec()
            clicked = choice.clickedButton()
            if clicked is overwrite:
                try:
                    api.update_job(job.name, payload)
                    imported.append(job.name)
                except ApiError as e:
                    QMessageBox.warning(parent, "Import jobs", f"{job.name}: {e}")
                    skipped.append(job.name)
            elif clicked is as_copy:
                new_name = copy_name(job.name, existing | set(imported))
                payload["name"] = new_name
                try:
                    api.create_job(payload)
                    imported.append(new_name)
                except ApiError as e:
                    QMessageBox.warning(parent, "Import jobs", f"{new_name}: {e}")
                    skipped.append(job.name)
            else:
                skipped.append(job.name)
        else:
            try:
                api.create_job(payload)
                imported.append(job.name)
            except ApiError as e:
                QMessageBox.warning(parent, "Import jobs", f"{job.name}: {e}")
                skipped.append(job.name)

    summary = f"Imported {len(imported)} job(s)."
    if skipped:
        summary += f"\nSkipped: {', '.join(skipped)}"
    QMessageBox.information(parent, "Import jobs", summary)
    return bool(imported)


# -- settings -------------------------------------------------------------------------


def export_settings_flow(api: ApiClient, parent: QWidget) -> None:
    try:
        config = api.get_config()
    except ApiError as e:
        QMessageBox.warning(parent, "Export settings", str(e))
        return
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export settings", "reportflow-settings.json", "JSON (*.json)"
    )
    if not path:
        return
    try:
        Path(path).write_text(json.dumps(export_settings(config), indent=2), encoding="utf-8")
    except OSError as e:
        QMessageBox.warning(parent, "Export settings", f"Export failed: {e}")
        return
    QMessageBox.information(
        parent,
        "Export settings",
        f"Settings exported to:\n{path}\n\nNote: the SMTP password is never exported — "
        "it stays encrypted on this machine.",
    )


def import_settings_flow(api: ApiClient, parent: QWidget) -> None:
    path, _ = QFileDialog.getOpenFileName(parent, "Import settings", "", "JSON (*.json)")
    if not path:
        return
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        sections = parse_settings_file(data)
    except (OSError, json.JSONDecodeError, TransferError) as e:
        QMessageBox.warning(parent, "Import settings", f"Cannot import this file: {e}")
        return

    confirm = QMessageBox.question(
        parent,
        "Import settings",
        f"Apply the {', '.join(sorted(sections))} settings from this file? "
        "Your jobs are not affected. The SMTP password (if any) must be re-entered "
        "in Settings afterwards.",
    )
    if confirm != QMessageBox.StandardButton.Yes:
        return
    try:
        api.update_settings(sections)
    except ApiError as e:
        QMessageBox.warning(parent, "Import settings", f"Import failed: {e}")
        return
    QMessageBox.information(parent, "Import settings", "Settings imported and applied.")

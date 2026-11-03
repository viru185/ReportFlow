"""VSTO evidence collection, privacy, and deterministic startup failures."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from reportflow.worker import diagnostics, excel


def test_current_pi_logs_are_collected_redacted_and_environment_restored(tmp_path, monkeypatch):
    temp = tmp_path / "temp"
    temp.mkdir()
    manifest = temp / "PIDataLink.vsto"
    manifest.write_text("manifest")
    monkeypatch.setenv("TEMP", str(temp))
    monkeypatch.setenv("TMP", str(temp))
    monkeypatch.setenv("VSTO_LOGALERTS", "0")
    monkeypatch.delenv("VSTO_SUPPRESSDISPLAYALERTS", raising=False)
    monkeypatch.setattr(diagnostics, "_registrations", lambda: [{"Manifest": str(manifest)}])
    monkeypatch.setattr(diagnostics, "windows_identity", lambda: r"EXAMPLE\report_service")
    monkeypatch.setattr(diagnostics.win32ts, "ProcessIdToSessionId", lambda _: 0)
    monkeypatch.setattr(
        diagnostics.VstoDiagnostics,
        "_events",
        lambda _: [{"message": 'VSTO failure Password="do not export me"; Token=private'}],
    )
    collector = diagnostics.VstoDiagnostics(tmp_path / "run")
    collector.start()
    assert os.environ["VSTO_LOGALERTS"] == "1"
    assert os.environ["VSTO_SUPPRESSDISPLAYALERTS"] == "1"
    recent = temp / "OSIsoft.PIDataLink.UI.vsto.log"
    recent.write_text(
        'Trust failure; Password="do not export me"; Token=private', encoding="utf-16"
    )
    unrelated = temp / "another-app.log"
    unrelated.write_text("unrelated")
    old = temp / "PIAFBuilder.vsto.log"
    old.write_text("old")
    os.utime(old, (time.time() - 60, time.time() - 60))
    collector.finish()
    assert os.environ["VSTO_LOGALERTS"] == "0"
    assert "VSTO_SUPPRESSDISPLAYALERTS" not in os.environ
    data = json.loads((collector.directory / "activation.json").read_text(encoding="utf-8"))
    assert data["account"] == r"EXAMPLE\report_service" and data["session_id"] == 0
    assert len(data["collected_logs"]) == 1
    text = Path(data["collected_logs"][0]).read_text(encoding="utf-8")
    assert "Trust failure" in text
    assert "do not export me" not in text and "private" not in text
    assert "REDACTED" in text
    assert "do not export me" not in json.dumps(data)


def test_pi_manifest_file_uri_and_xml_secret_redaction():
    assert diagnostics._manifest_path("file:///C:/PI%20System/PI.vsto|vstolocal") == Path(
        "C:/PI System/PI.vsto"
    )
    text = diagnostics.redact_diagnostic_text("<Password>secret value</Password> pwd=x; api_key=y")
    assert "secret value" not in text and "pwd=x" not in text and "api_key=y" not in text


def test_excel_environment_evidence_never_exports_other_variables(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "_excel_bits", lambda _: 64)
    monkeypatch.setattr(
        diagnostics.psutil,
        "Process",
        lambda _: SimpleNamespace(
            environ=lambda: {
                "VSTO_LOGALERTS": "1",
                "VSTO_SUPPRESSDISPLAYALERTS": "1",
                "PASSWORD": "private",
            }
        ),
    )
    collector = diagnostics.VstoDiagnostics(tmp_path)
    collector.excel(SimpleNamespace(pid=123, api=SimpleNamespace(Version="16.0", Build="123")))
    assert collector.evidence["excel"]["vsto_logging_enabled"]
    assert collector.evidence["excel"]["vsto_dialogs_suppressed"]
    assert "private" not in json.dumps(collector.evidence)


def test_access_denied_startup_is_not_retried(monkeypatch):
    create = Mock(side_effect=RuntimeError(-2147024891, "Access is denied"))
    monkeypatch.setattr(excel.xw, "App", create)
    monkeypatch.setattr(excel, "windows_identity", lambda: r"EXAMPLE\report_service")
    with pytest.raises(excel.ExcelJobError, match="0x80070005.*report_service"):
        excel.ExcelRun()._create_app_with_retry()
    assert create.call_count == 1


def test_transient_startup_error_retries(monkeypatch):
    app = SimpleNamespace(pid=123)
    create = Mock(side_effect=[RuntimeError(-2147023174, "RPC server is unavailable"), app])
    monkeypatch.setattr(excel.xw, "App", create)
    monkeypatch.setattr(excel.time, "sleep", lambda _: None)
    assert excel.ExcelRun()._create_app_with_retry() is app
    assert create.call_count == 2


def test_addin_false_connection_is_not_mistaken_for_success():
    class RefusingAddin:
        ProgId = "OSIsoft.PIDataLink.UI"
        Description = "PI DataLink"

        @property
        def Connect(self):
            return False

        @Connect.setter
        def Connect(self, value):
            pass

    addins = SimpleNamespace(Count=1, Item=lambda _: RefusingAddin())
    run = excel.ExcelRun()
    run._connect_com_addins(SimpleNamespace(api=SimpleNamespace(COMAddIns=addins)))
    assert not run.pi_datalink_connected and run.failed_addins == ["PI DataLink"]


def test_source_guard_survives_first_save_as(tmp_path):
    source = tmp_path / "source.xlsx"
    book = SimpleNamespace(api=SimpleNamespace(FullName=str(tmp_path / "local.xlsx")))
    run = excel.ExcelRun()
    run._source_paths[id(book)] = source.resolve()
    with pytest.raises(excel.ExcelJobError, match="refusing to overwrite"):
        run.save_output(book, source)

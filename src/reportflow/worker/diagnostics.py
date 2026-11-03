"""Collect VSTO activation evidence in the worker's actual Windows security context.

The outer COM exception hides the deployment failure. VSTO's own logs and the
Application event log expose it without requiring a service-account desktop login.
Only PI-related, current-run evidence and whitelisted registration values are saved.
"""

from __future__ import annotations

import json
import os
import re
import struct
import time
import winreg
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import psutil
import win32api
import win32con
import win32evtlog
import win32security
import win32ts
from loguru import logger


def windows_identity() -> str:
    """Read the token, rather than relying on possibly inherited USERNAME variables."""
    try:
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
            name, domain, _ = win32security.LookupAccountSid(None, sid)
            return f"{domain}\\{name}"
        finally:
            token.Close()
    except Exception:
        return f"{os.environ.get('USERDOMAIN', '?')}\\{os.environ.get('USERNAME', '?')}"


def is_pi_addin(name: str) -> bool:
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return any(part in key for part in ("pidatalink", "piafbuilder", "pibuilder"))


def redact_diagnostic_text(text: str) -> str:
    """Scrub common secret assignments before diagnostic text reaches disk or logs."""
    keys = r"password|passwd|pwd|secret|token|api[_-]?key|authorization"
    text = re.sub(
        rf"(?i)(\b(?:{keys})\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^;\s<>]+)",
        r"\1***REDACTED***",
        text,
    )
    text = re.sub(rf"(?is)(<({keys})\b[^>]*>).*?(</\2>)", r"\1***REDACTED***\3", text)
    return re.sub(r"(https?://)[^/\s@]+:[^/\s@]+@", r"\1***REDACTED***@", text)


def _manifest_path(manifest: str) -> Path | None:
    location = manifest.split("|", 1)[0]
    if location.lower().startswith("file:"):
        # PI installers also register file:\\D:\... URIs. Treat their leading
        # slashes as a local drive prefix, not a UNC host named "D:".
        location = unquote(location[5:]).replace("\\", "/")
        if location.lower().startswith("//localhost/"):
            location = location[len("//localhost") :]
        if re.match(r"^/*[a-zA-Z]:/", location):
            location = location.lstrip("/")
    elif "://" in location:
        return None
    return Path(location) if location else None


def _redact_evidence(value: Any) -> Any:
    # Redact before JSON escaping: quoted secrets inside an event message must not
    # escape the text scrubber because their quotes have become backslash-escaped.
    if isinstance(value, str):
        return redact_diagnostic_text(value)
    if isinstance(value, dict):
        return {key: _redact_evidence(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_evidence(item) for item in value]
    return value


def _registrations() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root, label in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        for view, bits in ((winreg.KEY_WOW64_32KEY, 32), (winreg.KEY_WOW64_64KEY, 64)):
            try:
                with winreg.OpenKey(
                    root, r"Software\Microsoft\Office\Excel\Addins", 0, winreg.KEY_READ | view
                ) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        progid = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, progid) as entry:
                            row: dict[str, Any] = {"root": label, "bits": bits, "progid": progid}
                            for name in ("FriendlyName", "Description", "Manifest", "LoadBehavior"):
                                try:
                                    row[name] = winreg.QueryValueEx(entry, name)[0]
                                except OSError:
                                    pass
                            if is_pi_addin(progid + str(row.get("FriendlyName", ""))):
                                manifest = _manifest_path(str(row.get("Manifest", "")))
                                if manifest:
                                    row["manifest_exists"] = manifest.is_file()
                                rows.append(row)
            except OSError:
                continue
    return rows


def _excel_bits(pid: int) -> int | None:
    try:
        with Path(psutil.Process(pid).exe()).open("rb") as stream:
            stream.seek(0x3C)
            offset = struct.unpack("<I", stream.read(4))[0]
            stream.seek(offset + 4)
            machine = struct.unpack("<H", stream.read(2))[0]
            return {0x14C: 32, 0x8664: 64, 0xAA64: 64}.get(machine)
    except (OSError, psutil.Error, struct.error):
        return None


def _runtime_versions() -> list[dict[str, Any]]:
    versions = []
    for view, bits in ((winreg.KEY_WOW64_32KEY, 32), (winreg.KEY_WOW64_64KEY, 64)):
        for version in ("v4", "v4R", "v4M"):
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    rf"Software\Microsoft\VSTO Runtime Setup\{version}",
                    0,
                    winreg.KEY_READ | view,
                ) as key:
                    entry: dict[str, Any] = {"bits": bits, "key": version}
                    for name in ("Version", "Install"):
                        try:
                            entry[name] = winreg.QueryValueEx(key, name)[0]
                        except OSError:
                            pass
                    versions.append(entry)
            except OSError:
                pass
    return versions


class VstoDiagnostics:
    def __init__(self, run_dir: Path) -> None:
        self.directory = run_dir / "pi_diagnostics"
        self.started = time.time()
        self.evidence: dict[str, Any] = {}
        self.folders: set[Path] = set()
        self._environment: dict[str, str | None] = {}

    def start(self) -> None:
        # Process-local only: children inherit it; machine/user settings are untouched.
        for name, value in (("VSTO_LOGALERTS", "1"), ("VSTO_SUPPRESSDISPLAYALERTS", "1")):
            self._environment[name] = os.environ.get(name)
            os.environ[name] = value
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.evidence = {
                "account": windows_identity(),
                "session_id": win32ts.ProcessIdToSessionId(os.getpid()),
                "profile": {
                    k: os.environ.get(k) for k in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP")
                },
                "registrations": _registrations(),
                "vsto_runtime": _runtime_versions(),
                "addins": [],
            }
            for row in self.evidence["registrations"]:
                manifest = _manifest_path(str(row.get("Manifest", "")))
                if manifest:
                    self.folders.add(manifest.parent)
            for key in ("TEMP", "TMP"):
                if os.environ.get(key):
                    self.folders.add(Path(os.environ[key]))
        except Exception as exc:
            logger.warning("PI diagnostic setup incomplete: {}", redact_diagnostic_text(str(exc)))

    def excel(self, app: Any) -> None:
        try:
            self.evidence["excel"] = {
                "version": str(app.api.Version),
                "build": str(app.api.Build),
                "pid": int(app.pid),
                "bits": _excel_bits(int(app.pid)),
            }
            try:
                child_environment = psutil.Process(int(app.pid)).environ()
                self.evidence["excel"]["vsto_logging_enabled"] = (
                    child_environment.get("VSTO_LOGALERTS") == "1"
                )
                self.evidence["excel"]["vsto_dialogs_suppressed"] = (
                    child_environment.get("VSTO_SUPPRESSDISPLAYALERTS") == "1"
                )
            except psutil.Error as exc:
                self.evidence["excel"]["environment_check_error"] = str(exc)
            # Counts identify per-user resiliency state without exporting opaque data
            # that can include unrelated add-ins or user document paths.
            version = str(app.api.Version)
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    rf"Software\Microsoft\Office\{version}\Excel\Resiliency\DisabledItems",
                ) as key:
                    self.evidence["excel"]["disabled_items_count"] = winreg.QueryInfoKey(key)[1]
            except OSError:
                self.evidence["excel"]["disabled_items_count"] = 0
        except Exception as exc:
            logger.debug("Excel diagnostic properties unavailable: {}", str(exc))

    def addin(self, details: dict[str, Any]) -> None:
        self.evidence.setdefault("addins", []).append(details)

    def _events(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        handle = win32evtlog.OpenEventLog(None, "Application")
        try:
            flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
            scanned = 0
            while scanned < 512:
                events = win32evtlog.ReadEventLog(handle, flags, 0)
                if not events:
                    break
                for event in events:
                    scanned += 1
                    if event.TimeGenerated.timestamp() < self.started - 1:
                        return rows
                    text = "\n".join(event.StringInserts or [])
                    if is_pi_addin(text) or "vsto" in event.SourceName.lower():
                        rows.append(
                            {
                                "source": event.SourceName,
                                "event_id": event.EventID,
                                "time": str(event.TimeGenerated),
                                "message": text,
                            }
                        )
        finally:
            win32evtlog.CloseEventLog(handle)
        return rows

    def finish(self) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            copied: list[str] = []
            for folder in sorted(self.folders, key=str):
                try:
                    for path in folder.glob("*.log"):
                        if not is_pi_addin(path.name) or path.stat().st_mtime < self.started:
                            continue
                        # Bounded reads keep unexpected add-in log growth from stalling teardown.
                        with path.open("rb") as stream:
                            stream.seek(max(0, path.stat().st_size - 2_000_000))
                            payload = stream.read(2_000_000)
                        encoding = (
                            "utf-16"
                            if payload.startswith((b"\xff\xfe", b"\xfe\xff"))
                            else "utf-8-sig"
                        )
                        target = self.directory / f"{len(copied) + 1}_{path.name}"
                        target.write_text(
                            redact_diagnostic_text(payload.decode(encoding, errors="replace")),
                            encoding="utf-8",
                        )
                        copied.append(str(target))
                except OSError as exc:
                    logger.debug("VSTO log collection unavailable: {}", str(exc))
            self.evidence["collected_logs"] = copied
            self.evidence["registrations_after"] = _registrations()
            try:
                self.evidence["events"] = self._events()
            except Exception as exc:
                self.evidence["event_collection_error"] = str(exc)
            target = self.directory / "activation.json"
            target.write_text(
                json.dumps(_redact_evidence(self.evidence), indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("PI activation diagnostics saved: {}", target)
        except Exception as exc:
            logger.warning(
                "Could not save PI activation diagnostics: {}", redact_diagnostic_text(str(exc))
            )
        finally:
            for name, previous in self._environment.items():
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous

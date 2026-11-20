"""Trust PI DataLink's VSTO add-ins for the Windows account ReportFlow runs as.

VSTO loads an add-in only when its deployment manifest is trusted for the CURRENT account:
either the signing certificate is in Trusted Publishers, or the add-in is on that account's
inclusion list (``HKCU\\Software\\Microsoft\\VSTO\\Security\\Inclusion``). A desktop user gets
the inclusion entry by clicking Install on VSTO's one-time trust prompt. A service account
never sees that prompt, so PI DataLink fails with "has not been granted trust … not on the
inclusion list" and every PI cell keeps the value last saved in the workbook — the reports
still go out, with stale data (Merian field logs, Oct–Nov 2026).

:func:`trust_pi_addins` writes the same entry the prompt would, and only for the PI add-ins an
administrator registered under HKLM. It must run in the account being trusted (the service
process), because the inclusion list lives in that account's own HKCU.

Registry access goes through :func:`_read_inclusion` / :func:`_write_inclusion` so the logic is
testable without touching the real registry.
"""

from __future__ import annotations

import re
import uuid
import winreg
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

INCLUSION_KEY = r"Software\Microsoft\VSTO\Security\Inclusion"
_ADDINS_KEY = r"Software\Microsoft\Office\Excel\Addins"
_DSIG = "{http://www.w3.org/2000/09/xmldsig#}"


def is_pi_addin(name: str) -> bool:
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return any(part in key for part in ("pidatalink", "piafbuilder", "pibuilder"))


def manifest_path(manifest: str) -> Path | None:
    """The local file behind an add-in's registered ``Manifest`` value (None if remote)."""
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


def pi_registrations() -> list[dict[str, Any]]:
    """PI add-in registrations for Excel, from HKCU and HKLM in both registry views."""
    rows: list[dict[str, Any]] = []
    for root, label in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        for view, bits in ((winreg.KEY_WOW64_32KEY, 32), (winreg.KEY_WOW64_64KEY, 64)):
            try:
                with winreg.OpenKey(root, _ADDINS_KEY, 0, winreg.KEY_READ | view) as key:
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
                                manifest = manifest_path(str(row.get("Manifest", "")))
                                if manifest:
                                    row["manifest_exists"] = manifest.is_file()
                                rows.append(row)
            except OSError:
                continue
    return rows


def manifest_public_key(path: Path) -> str | None:
    """The manifest signer's RSA public key in the inclusion list's format, or None.

    The ``.vsto`` deployment manifest is XML-signed; its StrongNameSignature carries the
    key as ``<RSAKeyValue>``. The inclusion list stores it the way .NET's
    ``RSA.ToXmlString(false)`` writes it: no namespace, no whitespace.
    """
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    signatures = list(root.iter(f"{_DSIG}Signature"))
    # Prefer the strong-name signature; the Authenticode one carries the same key.
    signatures.sort(key=lambda s: s.get("Id") != "StrongNameSignature")
    for signature in signatures:
        key = signature.find(f"{_DSIG}KeyInfo/{_DSIG}KeyValue/{_DSIG}RSAKeyValue")
        if key is None:
            continue
        modulus = key.findtext(f"{_DSIG}Modulus")
        exponent = key.findtext(f"{_DSIG}Exponent")
        if modulus and exponent:
            return (
                f"<RSAKeyValue><Modulus>{''.join(modulus.split())}</Modulus>"
                f"<Exponent>{''.join(exponent.split())}</Exponent></RSAKeyValue>"
            )
    return None


def manifest_urls(path: Path) -> list[str]:
    """The URL forms of a manifest: the one VSTO writes first, then the escaped spelling.

    Microsoft's own ``UserInclusionList.Add`` stores ``Uri.ToString()`` — spaces as-is
    (verified against the installed VSTO runtime, Nov 2026). The %20-escaped form is only
    used to recognise an entry written by something else.
    """
    posix = path.as_posix().lstrip("/")
    # .NET's Uri.AbsoluteUri escapes spaces but keeps sub-delimiters such as "(x86)".
    escaped = quote(posix, safe="/:!$&'()*+,;=@~")
    return list(dict.fromkeys([f"file:///{posix}", f"file:///{escaped}"]))


@dataclass
class PiAddin:
    name: str
    manifest: Path
    public_key: str | None
    urls: list[str] = field(default_factory=list)


def pi_addins() -> list[PiAddin]:
    """The PI add-ins an administrator installed (HKLM) whose manifest file exists."""
    found: dict[str, PiAddin] = {}
    for row in pi_registrations():
        if row.get("root") != "HKLM":
            continue  # trust is only ever granted to machine-wide (admin) installs
        path = manifest_path(str(row.get("Manifest", "")))
        if path is None or not path.is_file():
            continue
        key = str(path).casefold()
        if key not in found:  # the 32- and 64-bit views often point at the same file
            name = str(row.get("FriendlyName") or row.get("progid"))
            found[key] = PiAddin(name, path, manifest_public_key(path), manifest_urls(path))
    return list(found.values())


def _read_inclusion() -> list[dict[str, str]]:
    """The current account's inclusion list: ``[{"key", "url", "public_key"}]``."""
    entries: list[dict[str, str]] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INCLUSION_KEY) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                with winreg.OpenKey(key, winreg.EnumKey(key, i)) as entry:
                    try:
                        url = str(winreg.QueryValueEx(entry, "Url")[0])
                        public_key = str(winreg.QueryValueEx(entry, "PublicKey")[0])
                    except OSError:
                        continue
                    entries.append(
                        {"key": winreg.EnumKey(key, i), "url": url, "public_key": public_key}
                    )
    except OSError:
        pass  # no inclusion list yet
    return entries


def _write_inclusion(url: str, public_key: str) -> None:
    # Same shape UserInclusionList.Add writes: a bare lowercase GUID key, Url + PublicKey.
    subkey = f"{INCLUSION_KEY}\\{uuid.uuid4()}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, "Url", 0, winreg.REG_SZ, url)
        winreg.SetValueEx(key, "PublicKey", 0, winreg.REG_SZ, public_key)


def _delete_inclusion(name: str) -> None:
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{INCLUSION_KEY}\\{name}")


def _entries_for(addin: PiAddin, entries: list[dict[str, str]]) -> list[dict[str, str]]:
    urls = {u.casefold() for u in addin.urls}
    return [e for e in entries if e["url"].casefold() in urls]


def _is_trusted(addin: PiAddin, entries: list[dict[str, str]]) -> bool:
    # Same file AND same signing key: after a PI upgrade re-signs the manifest with a new
    # key, VSTO refuses the old entry again, so it no longer counts.
    return any(e["public_key"] == addin.public_key for e in _entries_for(addin, entries))


def trust_status() -> list[dict[str, Any]]:
    """``[{"name", "manifest", "trusted"}]`` for each admin-installed PI add-in."""
    entries = _read_inclusion()
    return [
        {"name": a.name, "manifest": str(a.manifest), "trusted": _is_trusted(a, entries)}
        for a in pi_addins()
    ]


def untrusted_pi_addins() -> list[str]:
    """Names of admin-installed PI add-ins this account has not trusted (for run warnings)."""
    return [row["name"] for row in trust_status() if not row["trusted"]]


def trust_pi_addins() -> list[dict[str, Any]]:
    """Put every admin-installed PI add-in on this account's inclusion list.

    Returns ``[{"name", "manifest", "result"}]`` with result "trusted", "already trusted",
    or "failed: <reason>".
    """
    entries = _read_inclusion()
    results: list[dict[str, Any]] = []
    for addin in pi_addins():
        row: dict[str, Any] = {"name": addin.name, "manifest": str(addin.manifest)}
        if _is_trusted(addin, entries):
            row["result"] = "already trusted"
        elif not addin.public_key:
            row["result"] = "failed: the add-in's manifest has no signing key"
        else:
            try:
                for stale in _entries_for(addin, entries):  # same file, old key
                    _delete_inclusion(stale["key"])
                _write_inclusion(addin.urls[0], addin.public_key)
            except OSError as e:
                row["result"] = f"failed: {e}"
            else:
                row["result"] = "trusted"
        results.append(row)
    return results

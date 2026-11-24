"""Excel's "Disabled Items" list, for the PI add-ins (0.16).

When Excel crashes, or is killed, while it loads an add-in, it remembers that under
``HKCU\\Software\\Microsoft\\Office\\<version>\\Excel\\Resiliency``: a crash marker in
``StartupItems``, then an entry in ``DisabledItems``. From then on that account's Excel never
loads the add-in, and ``COMAddIn.Connect = True`` fails with E_ABORT (0x80004004) — no prompt,
no message. On the HIL server PI DataLink stayed off from 29 Sep to 24 Nov 2026 after two Excel
crashes during busy starts; trusting it (``vsto_trust``) could not help, and PI DataLink reports
went out with last-saved values.

A desktop user re-enables an add-in under File → Options → Add-ins → Disabled Items. A service
account never opens Excel, so Settings → Service account → Fix PI DataLink removes the PI
add-ins' entries — in the service process, whose HKCU is the service account's. Nothing else on
the list is touched (it can also hold documents, with their paths).

Each entry is REG_BINARY: a DWORD kind, the byte lengths of a path and a name, then both in
UTF-16LE. Matching does not rely on that layout: an entry belongs to a PI add-in when any text
in it names one (:func:`reportflow.core.vsto_trust.is_pi_addin`).
"""

from __future__ import annotations

import re
import struct
import winreg
from dataclasses import dataclass

from reportflow.core.vsto_trust import is_pi_addin

OFFICE_KEY = r"Software\Microsoft\Office"
DISABLED = "DisabledItems"
STARTUP = "StartupItems"  # crash markers: the next Excel start turns these into DisabledItems
_PRINTABLE = re.compile(r"[\x20-\x7e]{3,}")


def addin_key(name: str) -> str:
    """A name reduced for matching: "PI DataLink", "pi datalink" and "PIDataLink" agree."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass(frozen=True)
class ResiliencyItem:
    version: str  # the Office version key, e.g. "16.0"
    kind: str  # DISABLED or STARTUP
    value: str  # the registry value's name
    name: str  # the add-in's name as Excel stored it ("pi datalink"), "" if unreadable
    path: str  # its file or manifest, "" if unreadable
    text: str  # every readable string in the entry, for matching

    @property
    def is_pi(self) -> bool:
        return is_pi_addin(self.text)

    @property
    def label(self) -> str:
        """The PI add-in's usual name ("PI DataLink"), else what Excel stored."""
        key = addin_key(self.text)
        if "pidatalink" in key:
            return "PI DataLink"
        if "piafbuilder" in key or "pibuilder" in key:
            return "PIAFBuilder"
        return self.name or self.value


def decode(blob: bytes) -> tuple[str, str, str]:
    """``(name, path, text)`` from one entry. ``text`` holds every readable string, read at
    both byte alignments, so an entry still matches if its layout differs from the usual."""
    name = path = ""
    if len(blob) >= 12:
        _kind, path_len, name_len = struct.unpack_from("<III", blob)
        end = 12 + path_len + name_len
        if path_len % 2 == 0 and name_len % 2 == 0 and end <= len(blob):
            path = blob[12 : 12 + path_len].decode("utf-16-le", "replace").rstrip("\x00")
            name = blob[12 + path_len : end].decode("utf-16-le", "replace").rstrip("\x00")
    found: list[str] = [name, path]
    for start in (0, 1):
        chunk = blob[start:]
        chunk = chunk[: len(chunk) - len(chunk) % 2]
        found += _PRINTABLE.findall(chunk.decode("utf-16-le", "replace"))
    return name, path, " ".join(s for s in found if s)


def _versions(base: str) -> list[str]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as key:
            names = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
    except OSError:
        return []
    return [n for n in names if re.fullmatch(r"\d+\.\d+", n)]


def read_items(*, base: str = OFFICE_KEY) -> list[ResiliencyItem]:
    """Every entry on this account's Excel Disabled Items and crash-marker lists."""
    items: list[ResiliencyItem] = []
    for version in _versions(base):
        for kind in (DISABLED, STARTUP):
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, rf"{base}\{version}\Excel\Resiliency\{kind}"
                ) as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        value, data, kind_of = winreg.EnumValue(key, i)
                        if kind_of != winreg.REG_BINARY or not isinstance(data, bytes):
                            continue
                        name, path, text = decode(data)
                        items.append(ResiliencyItem(version, kind, value, name, path, text))
            except OSError:
                continue
    return items


def disabled_pi_addins(*, base: str = OFFICE_KEY) -> list[str]:
    """The PI add-ins Excel has switched off for this account ("PI DataLink", …), by name."""
    labels = {i.label for i in read_items(base=base) if i.kind == DISABLED and i.is_pi}
    return sorted(labels, key=str.casefold)


def reenable_pi_addins(*, base: str = OFFICE_KEY) -> tuple[list[str], list[str]]:
    """Take the PI add-ins off Excel's lists for this account. Returns the add-ins re-enabled
    (they were on Disabled Items) and any failures ("PI DataLink: <reason>"). Crash markers of
    PI add-ins go too, so the next Excel start doesn't switch them off again."""
    enabled: list[str] = []
    failed: list[str] = []
    for item in read_items(base=base):
        if not item.is_pi:
            continue
        subkey = rf"{base}\{item.version}\Excel\Resiliency\{item.kind}"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, item.value)
        except OSError as e:
            if item.kind == DISABLED:
                failed.append(f"{item.label}: {e}")
            continue
        if item.kind == DISABLED:
            enabled.append(item.label)
    return sorted(set(enabled), key=str.casefold), failed

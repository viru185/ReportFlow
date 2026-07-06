"""Machine-scoped secret store backed by Windows DPAPI.

Why machine scope: the Service runs as LocalSystem and must read the SMTP password that the
interactive UI user stored. Per-user Credential Manager would not share across those accounts,
so we protect the secret to the MACHINE (``CRYPTPROTECT_LOCAL_MACHINE``) and keep the encrypted
blob under ProgramData, readable by any process on this machine (and only this machine).

``win32crypt`` is imported lazily so importing this module never hard-requires pywin32.
"""

from __future__ import annotations

from pathlib import Path

from reportflow.core import paths

_NAMESPACE = "ReportFlow"
_LOCAL_MACHINE = 0x4  # CRYPTPROTECT_LOCAL_MACHINE


def _secret_path(key: str) -> Path:
    safe = "".join(c for c in key if c.isalnum() or c in "._-")
    return paths.state_dir() / "secrets" / f"{safe}.bin"


def set_secret(key: str, value: str) -> None:
    import win32crypt

    blob = win32crypt.CryptProtectData(
        value.encode("utf-8"), _NAMESPACE, None, None, None, _LOCAL_MACHINE
    )
    path = _secret_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)


def get_secret(key: str) -> str | None:
    import win32crypt

    path = _secret_path(key)
    if not path.exists():
        return None
    _desc, data = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)
    return data.decode("utf-8")


def has_secret(key: str) -> bool:
    return _secret_path(key).exists()


def delete_secret(key: str) -> None:
    _secret_path(key).unlink(missing_ok=True)

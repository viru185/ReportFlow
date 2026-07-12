"""Validate a Windows account and reconfigure the ReportFlow service to run as it.

PI DataLink and other VSTO / Windows-integrated add-ins cannot load under LocalSystem
(the service shows as ``COMPUTERNAME$``), so the operator must run the service as a real
user that has the add-in installed and data access. The service is already privileged
(LocalSystem), so it can reconfigure its own NSSM ``ObjectName`` and restart itself — no
UAC prompt, no reinstall.

Nothing here ever logs the password.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from loguru import logger

from reportflow.core import paths

# Win32 LogonUser constants — validate credentials with a network logon (no interactive
# logon right required, no profile loaded).
_LOGON32_LOGON_NETWORK = 3
_LOGON32_PROVIDER_DEFAULT = 0

_SERVICE_NAME = "ReportFlow"

_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
)


class ServiceAccountError(Exception):
    """Raised when validation or applying the service account fails."""


def split_account(user: str) -> tuple[str, str]:
    """Split ``DOMAIN\\user`` / ``.\\user`` / ``user`` into ``(domain, name)``.

    A bare name (no backslash) uses ``"."`` — the local machine — as the domain.
    """
    user = user.strip()
    if "\\" in user:
        domain, name = user.split("\\", 1)
        return (domain.strip() or "."), name.strip()
    return ".", user


def _logon(name: str, domain: str, password: str) -> None:
    """Attempt a Windows logon; raise on invalid credentials. Isolated for testing."""
    import win32security  # lazy: Windows-only, keeps the module importable everywhere

    handle = win32security.LogonUser(
        name, domain, password, _LOGON32_LOGON_NETWORK, _LOGON32_PROVIDER_DEFAULT
    )
    handle.Close()


def validate_credentials(user: str, password: str) -> None:
    """Raise :class:`ServiceAccountError` unless ``user``/``password`` authenticate."""
    if not user.strip():
        raise ServiceAccountError("Enter a Windows account (DOMAIN\\user or .\\user).")
    if not password:
        raise ServiceAccountError("Enter the account's password.")
    domain, name = split_account(user)
    try:
        _logon(name, domain, password)
    except Exception as e:  # noqa: BLE001 — any logon failure is a validation failure
        # Never echo the underlying handle/exception detail that could leak specifics.
        logger.warning("Service-account validation failed for {!r}", f"{domain}\\{name}")
        raise ServiceAccountError(
            "Those credentials were rejected by Windows. Check the account name "
            "(DOMAIN\\user or .\\user) and password."
        ) from e


def nssm_path() -> Path:
    """Locate the bundled nssm.exe relative to the service exe (installer layout)."""
    exe_dir = paths.install_dir()
    candidates = [
        exe_dir.parent / "nssm" / "nssm.exe",  # {app}\service -> {app}\nssm
        exe_dir / "nssm" / "nssm.exe",
        exe_dir / "nssm.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    tried = "; ".join(str(c) for c in candidates)
    raise ServiceAccountError(f"nssm.exe not found — tried: {tried}. Reinstall ReportFlow.")


def apply_service_account(user: str, password: str, *, service_name: str = _SERVICE_NAME) -> str:
    """Set the service's logon account to ``user`` and restart it (detached).

    Returns the normalized ``DOMAIN\\user`` that was applied. Assumes the caller already
    validated the credentials. NSSM grants ``SeServiceLogonRight`` as a side effect of
    setting ``ObjectName``.
    """
    domain, name = split_account(user)
    account = f"{domain}\\{name}"
    nssm = nssm_path()

    result = subprocess.run(
        [str(nssm), "set", service_name, "ObjectName", account, password],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        # stderr may name the failing right/account but not the password.
        detail = (result.stderr or result.stdout or "").strip()
        raise ServiceAccountError(f"nssm could not set the service account: {detail}")

    logger.info("Service account set to {!r}; scheduling service restart", account)
    _schedule_restart(nssm, service_name)
    return account


def _schedule_restart(nssm: Path, service_name: str) -> None:
    """Restart the service via a detached shell so this (soon-to-be-killed) process's HTTP
    response flushes first. The 2s delay lets the API answer before NSSM stops us."""
    comspec = os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")
    command = f'timeout /t 2 /nobreak >nul & "{nssm}" restart {service_name}'
    subprocess.Popen(  # noqa: S603 — fixed, trusted arguments
        [comspec, "/c", command],
        creationflags=_DETACHED | getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )


def current_account() -> dict[str, object]:
    """The Windows identity the service runs as, plus whether it's the machine account."""
    username = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    return {
        "account": f"{domain}\\{username}".strip("\\"),
        "is_system": username.endswith("$"),
    }

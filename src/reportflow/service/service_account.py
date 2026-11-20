"""Validate a Windows account and reconfigure the ReportFlow service to run as it.

PI DataLink and other VSTO / Windows-integrated add-ins cannot load under LocalSystem
(the service shows as ``COMPUTERNAME$``), so the operator must run the service as a real
user that has the add-in installed and data access. The service is already privileged
(LocalSystem), so it can reconfigure its own NSSM ``ObjectName`` — no UAC prompt, no
reinstall.

A new logon account only takes effect when Windows starts the service again. The service
cannot restart itself from inside its own process tree: NSSM kills that tree on stop (and
the old ``cmd … timeout`` helper also died without a console), so the 0.11 restart never
happened in the field. Instead the service exits with :data:`RESTART_EXIT_CODE`; the
installer maps that code to "stop the service" (``nssm set ReportFlow AppExit 75 Exit``)
and enables service recovery for stops with an error (``sc failure`` + ``sc failureflag``),
so Windows starts the service again — now under the new account. No rights are needed at
runtime, which also covers a service already running as an ordinary user.

Nothing here ever logs the password.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from loguru import logger

from reportflow.core import paths

# Win32 LogonUser constants — validate credentials with a network logon (no interactive
# logon right required, no profile loaded).
_LOGON32_LOGON_NETWORK = 3
_LOGON32_PROVIDER_DEFAULT = 0

_SERVICE_NAME = "ReportFlow"

# Mapped by the installer to "stop the service so Windows recovery starts it again".
RESTART_EXIT_CODE = 75
# Long enough for the API's reply to reach the app before the process goes away.
_RESTART_DELAY_SECONDS = 1.5


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
        if "can't open service" in detail.lower() or "access is denied" in detail.lower():
            # Changing a service's account needs administrator rights. A service that already
            # runs as an ordinary user doesn't have them (field: "Can't open service!").
            raise ServiceAccountError(
                f"ReportFlow is running as {current_account()['account']}, which isn't "
                "allowed to change the service's account. Do it as an administrator: run the "
                "ReportFlow installer again (it asks for the service account) or "
                "scripts\\set-service-account.ps1."
            )
        raise ServiceAccountError(f"nssm could not set the service account: {detail}")

    logger.info("Service account set to {!r}; restarting the service", account)
    schedule_restart()
    return account


def schedule_restart(delay: float = _RESTART_DELAY_SECONDS) -> threading.Timer:
    """Exit with :data:`RESTART_EXIT_CODE` after ``delay`` seconds (see module docstring)."""
    timer = threading.Timer(delay, _exit_for_restart)
    timer.daemon = True
    timer.start()
    return timer


def _exit_for_restart() -> None:
    logger.info("Exiting with code {} so Windows restarts the service", RESTART_EXIT_CODE)
    os._exit(RESTART_EXIT_CODE)  # noqa: SLF001 — immediate, on purpose: no lingering threads


def current_account() -> dict[str, object]:
    """The Windows identity the service runs as, plus whether it's the machine account."""
    username = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    return {
        "account": f"{domain}\\{username}".strip("\\"),
        "is_system": username.endswith("$"),
    }

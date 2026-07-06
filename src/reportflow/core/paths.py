"""Filesystem layout resolution shared by all three processes.

Data root is ``%ProgramData%\\ReportFlow`` so the LocalSystem service and the interactive
UI user resolve to the SAME directory (never ``%APPDATA%``, which differs per account).

Environment override: set ``REPORTFLOW_DATA_DIR`` to relocate the data root (used by tests
and dev runs so we never touch the real ProgramData tree).
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

_ENV_DATA_DIR = "REPORTFLOW_DATA_DIR"
_APP_DIR_NAME = "ReportFlow"


@lru_cache(maxsize=1)
def data_root() -> Path:
    """Return the writable data root, honoring the ``REPORTFLOW_DATA_DIR`` override."""
    override = os.environ.get(_ENV_DATA_DIR)
    if override:
        return Path(override)
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    return Path(program_data) / _APP_DIR_NAME


def config_dir() -> Path:
    return data_root() / "config"


def logs_dir() -> Path:
    return data_root() / "logs"


def state_dir() -> Path:
    return data_root() / "state"


def runs_dir() -> Path:
    return data_root() / "runs"


def templates_dir() -> Path:
    return data_root() / "templates"


def config_file() -> Path:
    return config_dir() / "reportflow.toml"


def run_dir(run_id: str) -> Path:
    return runs_dir() / run_id


def install_dir() -> Path:
    """Directory the running executable / source tree lives in.

    Frozen (PyInstaller): the folder containing the executable. Source: the repo root
    (three levels up from this file: ``src/reportflow/core/paths.py`` -> repo root).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def ensure_dirs() -> None:
    """Create all data subdirectories. Idempotent; safe to call from any process."""
    for d in (config_dir(), logs_dir(), state_dir(), runs_dir(), templates_dir()):
        d.mkdir(parents=True, exist_ok=True)

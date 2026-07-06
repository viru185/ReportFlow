"""Load and atomically save the ReportFlow TOML configuration.

* Read with stdlib ``tomllib`` (Python 3.11+); write with ``tomli_w``.
* Saves are atomic (temp file in the same directory + ``os.replace``) so a crash mid-write
  can never leave a truncated config.
* Optional fields that are ``None`` are omitted from the file entirely.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import ValidationError

from reportflow.core import paths
from reportflow.core.config.models import AppConfig


class ConfigError(Exception):
    """Raised when configuration cannot be read, parsed, or validated."""


def _prune_empty(obj: Any) -> Any:
    """Recursively drop unset optional values (None, "", [], {}) so they can be omitted
    from the TOML. Meaningful falsy values (``False``, ``0``) are preserved."""
    if isinstance(obj, dict):
        pruned = {k: _prune_empty(v) for k, v in obj.items()}
        return {k: v for k, v in pruned.items() if not _is_empty(v)}
    if isinstance(obj, list):
        return [_prune_empty(v) for v in obj]
    return obj


def _is_empty(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def load_config(path: Path | None = None) -> AppConfig:
    """Read and validate the config. Raises :class:`ConfigError` on any problem."""
    cfg_path = path or paths.config_file()
    if not cfg_path.exists():
        raise ConfigError(f"configuration file not found: {cfg_path}")
    try:
        with cfg_path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"could not parse {cfg_path}: {exc}") from exc
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {cfg_path}:\n{exc}") from exc


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    """Atomically write ``config`` to disk and return the path written."""
    cfg_path = path or paths.config_file()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload = tomli_w.dumps(_prune_empty(data))

    tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, cfg_path)
    return cfg_path

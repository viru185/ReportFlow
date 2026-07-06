"""Redact secrets from diagnostic output and build the developer log bundle (zip)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from reportflow import __version__
from reportflow.core import paths
from reportflow.core.config.models import AppConfig

# Config keys whose values must never leave the machine, even though we don't currently
# store secrets in the TOML — defense in depth if that ever changes.
_SENSITIVE_KEYS = {"password", "passwd", "pwd", "secret", "token", "api_key", "apikey"}
_REDACTED = "***REDACTED***"


def _scrub(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: (_REDACTED if k.lower() in _SENSITIVE_KEYS else _scrub(v)) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def redact_config(config: AppConfig) -> dict[str, Any]:
    """Return a config snapshot safe to include in a support bundle (secrets scrubbed)."""
    return _scrub(config.model_dump(mode="json", by_alias=True, exclude_none=True))


def build_log_bundle(
    bundle_path: Path,
    config: AppConfig,
    *,
    run_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Zip logs + a redacted config snapshot + metadata for a support case."""
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    meta = {"reportflow_version": __version__, **(metadata or {})}

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("config_snapshot.json", json.dumps(redact_config(config), indent=2))
        zf.writestr("metadata.json", json.dumps(meta, indent=2))

        logs_root = paths.logs_dir()
        if logs_root.exists():
            for f in logs_root.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=str(Path("logs") / f.relative_to(logs_root)))

        runs_root = paths.runs_dir()
        selected = run_ids if run_ids is not None else _recent_run_dirs(runs_root)
        for rid in selected:
            run_dir = runs_root / rid
            if run_dir.exists():
                for f in run_dir.rglob("*"):
                    if f.is_file():
                        zf.write(f, arcname=str(Path("runs") / rid / f.relative_to(run_dir)))

    return bundle_path


def _recent_run_dirs(runs_root: Path, limit: int = 50) -> list[str]:
    if not runs_root.exists():
        return []
    dirs = [d for d in runs_root.iterdir() if d.is_dir()]
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return [d.name for d in dirs[:limit]]

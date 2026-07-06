"""First-run data seeding: create the ProgramData tree, a default config, and the default
email template if they don't already exist. Never overwrites existing files.
"""

from __future__ import annotations

from loguru import logger

from reportflow.core import paths
from reportflow.core.config.defaults import DEFAULT_EMAIL_TEMPLATE, default_config
from reportflow.core.config.loader import save_config


def seed_data_files() -> None:
    paths.ensure_dirs()

    cfg = paths.config_file()
    if not cfg.exists():
        save_config(default_config())
        logger.info("Seeded default config at {}", cfg)

    template = paths.templates_dir() / "email" / "default.html"
    if not template.exists():
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text(DEFAULT_EMAIL_TEMPLATE, encoding="utf-8")
        logger.info("Seeded default email template at {}", template)

"""ReportFlow — Windows Excel reporting automation (UI + Service + Worker).

The version is defined in exactly ONE place: ``pyproject.toml``. It is resolved here from
the installed package metadata (PyInstaller builds bundle that metadata via
``copy_metadata("reportflow")`` in the specs).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("reportflow")
except PackageNotFoundError:  # running from a raw source tree without installation
    __version__ = "0.0.0+unknown"

"""Small filesystem helpers for file dialogs: sensible starting locations."""

from __future__ import annotations

from pathlib import Path


def downloads_dir() -> Path:
    """The user's Downloads folder, falling back to the home directory."""
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def open_start_dir(current: str | None) -> str:
    """Where an 'open file' dialog should start: the selected file's folder if one is set,
    otherwise the Downloads folder."""
    if current:
        p = Path(current)
        folder = p if p.is_dir() else p.parent
        if folder.is_dir():
            return str(folder)
    return str(downloads_dir())


def save_start_path(current_dir: str | None, filename: str) -> str:
    """A default path for a 'save file' dialog: the given folder (or Downloads) + filename."""
    base = Path(current_dir) if current_dir and Path(current_dir).is_dir() else downloads_dir()
    return str(base / filename)

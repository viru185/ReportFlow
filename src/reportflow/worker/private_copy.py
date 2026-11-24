"""Open a private copy of each workbook, never the original (0.16).

When someone has the source workbook open, Excel gives a second opener read-only access — and
add-ins such as PI DataLink then may not refresh into it. The customer's server opened its
workbook read-only on 133 runs. And two jobs opening the same file at the same moment made
both hang.

So each run copies the latest SAVED version of the file into its own run folder
(``runs/<id>/inputs/<n>/<original name>`` — the name is kept for macros that read it) and opens
that. Copying works while someone has the file open (Excel opens files share-read). The copy
is deleted when the workbook is closed, and the launcher removes the run's ``inputs`` folder
whatever happens; "Export logs" never includes it.

A link to another workbook in the SAME folder is stored by Excel as a relative path, which
would now point into the run folder. Before the copy is opened, such links are rewritten to
point at the original folder (inside the copy's ``xl/externalLinks/_rels``) — no Excel
``ChangeLink``, which refreshes the values and can pop a dialog.
"""

from __future__ import annotations

import contextlib
import html
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from loguru import logger

INPUTS_DIR = "inputs"
_ZIP_SUFFIXES = (".xlsx", ".xlsm", ".xlsb", ".xltx", ".xltm")
_RELS = re.compile(r"^xl/externalLinks/_rels/[^/]+\.rels$")
_RELATIONSHIP = re.compile(r"<Relationship\b[^>]*>")
_TARGET = re.compile(r'\bTarget="([^"]*)"')
_COPY_ATTEMPTS = 5


class PrivateCopyError(RuntimeError):
    """The source workbook could not be copied (missing, or locked for reading)."""


def copy_for_run(source: Path, run_dir: Path, index: int) -> Path:
    """Copy ``source`` into the run folder and return the copy's path."""
    if not source.exists():
        raise PrivateCopyError(f"workbook template not found: {source}")
    target = run_dir / INPUTS_DIR / str(index) / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, _COPY_ATTEMPTS + 1):
        try:
            shutil.copyfile(source, target)  # no attributes: the copy is never read-only
            break
        except PermissionError as e:  # someone is saving it right now: try again shortly
            if attempt == _COPY_ATTEMPTS:
                raise PrivateCopyError(
                    f"could not read {source.name} — it may be being saved or locked by "
                    f"another program: {e}"
                ) from e
            time.sleep(1.0)
    relinked = relink_same_folder(target, source.parent)
    logger.info(
        "Working on a private copy of {} ({:,} bytes, saved {}){}",
        source,
        target.stat().st_size,
        time.strftime("%Y-%m-%d %H:%M", time.localtime(source.stat().st_mtime)),
        f"; {relinked} link(s) pointed back at its folder" if relinked else "",
    )
    return target


def _is_relative(target: str) -> bool:
    lowered = target.lower()
    if lowered.startswith(("file:", "http:", "https:", "ftp:", "\\\\", "/", "\\")):
        return False
    return not re.match(r"^[a-zA-Z]:", target)


def relink_same_folder(copy: Path, original_dir: Path) -> int:
    """Point relative external links inside ``copy`` at ``original_dir``. Returns how many
    were rewritten (0: the file is untouched)."""
    if copy.suffix.lower() not in _ZIP_SUFFIXES or not zipfile.is_zipfile(copy):
        return 0
    with zipfile.ZipFile(copy) as zf:
        names = [n for n in zf.namelist() if _RELS.match(n)]
        if not names:
            return 0
        changed: dict[str, str] = {}
        count = 0
        for name in names:
            text = zf.read(name).decode("utf-8")

            def fix(match: re.Match[str]) -> str:
                nonlocal count
                tag = match.group(0)
                if 'TargetMode="External"' not in tag:
                    return tag
                found = _TARGET.search(tag)
                if found is None:
                    return tag
                target = html.unescape(found.group(1))
                if not _is_relative(target):
                    return tag
                absolute = os.path.normpath(original_dir / target.replace("/", os.sep))
                count += 1
                new = html.escape(f"file:///{absolute}", quote=True)
                return tag[: found.start(1)] + new + tag[found.end(1) :]

            fixed = _RELATIONSHIP.sub(fix, text)
            if fixed != text:
                changed[name] = fixed
        if not changed:
            return 0
        rewritten = copy.with_name(copy.name + ".tmp")
        with zipfile.ZipFile(rewritten, "w") as out:
            for item in zf.infolist():
                data = (
                    changed[item.filename].encode("utf-8")
                    if item.filename in changed
                    else (zf.read(item.filename))
                )
                out.writestr(item, data)
    os.replace(rewritten, copy)
    return count


def remove_copy(copy: Path) -> None:
    """Delete a workbook copy (best effort: Excel can hold it a moment after closing)."""
    for _ in range(5):
        try:
            shutil.rmtree(copy.parent)
            break
        except FileNotFoundError:
            break
        except OSError:
            time.sleep(0.2)
    else:
        logger.debug("Could not delete the workbook copy {} yet", copy)
        return
    with contextlib.suppress(OSError):  # the run's last workbook: drop the empty ``inputs``
        copy.parent.parent.rmdir()


def remove_run_copies(run_dir: Path) -> None:
    """Delete everything under the run's ``inputs`` folder (stop, timeout, recovery)."""
    shutil.rmtree(run_dir / INPUTS_DIR, ignore_errors=True)

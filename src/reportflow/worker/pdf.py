"""Merge per-sheet exports without altering the workbook's print layout."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from pypdf import PdfWriter


def merge_pdfs(inputs: list[Path], output: Path, *, check_deadline: Callable[[str], None]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    temporary: Path | None = None
    try:
        for path in inputs:
            check_deadline(f"combining PDF {path.name}")
            writer.append(str(path))
        check_deadline("saving combined PDF")
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".pdf", delete=False) as stream:
            temporary = Path(stream.name)
            writer.write(stream)
        check_deadline("publishing combined PDF")
        os.replace(temporary, output)
    finally:
        writer.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)

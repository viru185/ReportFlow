"""PDF page order/layout and atomic publication on a failed merge."""

import pytest
from pypdf import PdfReader, PdfWriter

from reportflow.worker.pdf import merge_pdfs


def test_merge_preserves_sheet_order_page_sizes_and_multiple_pages(tmp_path):
    paths = []
    for i, widths in enumerate(([100, 110], [200])):
        path = tmp_path / f"{i}.pdf"
        with PdfWriter() as writer:
            for width in widths:
                writer.add_blank_page(width=width, height=300)
            writer.write(path)
        paths.append(path)
    output = tmp_path / "combined.pdf"
    merge_pdfs(paths, output, check_deadline=lambda _: None)
    assert [float(p.mediabox.width) for p in PdfReader(output).pages] == [100, 110, 200]


def test_failed_merge_does_not_publish_or_destroy_previous_report(tmp_path):
    output = tmp_path / "combined.pdf"
    output.write_bytes(b"previous report")
    with pytest.raises(FileNotFoundError):
        merge_pdfs([tmp_path / "missing.pdf"], output, check_deadline=lambda _: None)
    assert output.read_bytes() == b"previous report"

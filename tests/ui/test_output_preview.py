"""The Output tab's "Each run creates" card: the files of one run, where they go, emailed or not."""

from __future__ import annotations

from datetime import datetime

from reportflow.ui.windows.output_preview import plan_outputs

from .test_ui import FakeApi, _sample_job_dict

NOW = datetime(2026, 11, 21, 13, 45, 16)


def _plan(**kw):
    args = {
        "pattern": "",
        "job_name": "utkal pi vision report",
        "output_dir": "",
        "workbook_path": r"C:\Reports\Aditya_PI_Vision.xlsx",
        "included": [
            ("Query 01", True, True),
            ("Query 02", True, True),
            ("PI Vision", False, True),
        ],
        "combined_pdf": False,
        "workbook_count": 1,
        "now": NOW,
    }
    args.update(kw)
    return plan_outputs(**args)


def test_one_workbook_makes_a_copy_an_attachment_and_a_pdf_per_sheet():
    plan = _plan()
    assert plan.files() == [
        ("Full copy", "utkal pi vision report_20261121_134516.xlsx", "kept on disk"),
        ("Excel attachment", "utkal pi vision report_20261121_134516_email.xlsx", "emailed"),
        ("PDFs (3)", "utkal pi vision report_20261121_134516_<sheet>.pdf", "emailed"),
    ]
    assert plan.folder == "" and plan.workbook_folder == r"C:\Reports"
    assert not plan.overwrites


def test_several_workbooks_are_told_apart_by_name_and_counted():
    plan = _plan(workbook_count=8, pattern="{job}_{date}")
    assert plan.stem == "utkal pi vision report_20261121_Aditya_PI_Vision"
    assert plan.overwrites  # no time in the name: a second run that day overwrites


def test_combined_pdf_and_nothing_emailed():
    assert _plan(combined_pdf=True).files()[-1] == (
        "PDF",
        "utkal pi vision report_20261121_134516.pdf",
        "emailed",
    )
    bare = _plan(included=[("Query 01", False, False)])
    assert [what for what, *_ in bare.files()] == ["Full copy"]


def test_the_card_shows_the_chosen_workbooks_own_choices(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    job = _sample_job_dict()
    job["workbooks"] = [
        {
            "input_excel_path": "C:/data/Sales.xlsx",
            "sheets": [{"name": "Summary", "excel": True, "pdf": False, "hidden": False}],
        },
        {
            "input_excel_path": "C:/data/Stock.xlsx",
            "sheets": [{"name": "Levels", "excel": False, "pdf": True, "hidden": False}],
            "pdf_mode": "combined",
        },
    ]
    dlg = JobEditorDialog(FakeApi(sheets=["Summary", "Levels"]), job)
    qtbot.addWidget(dlg)
    card = dlg.output_example
    assert not card.workbook.isHidden() and card.sets.text() == "· one set per workbook (2)"
    assert "Excel attachment" in card.text() and "PDF" not in card.text()
    card.workbook.setCurrentIndex(1)  # Stock: no Excel attachment, one combined PDF
    assert "_Stock.pdf (emailed)" in card.text() and "Excel attachment" not in card.text()
    assert dlg._current_wb == 0  # picking on the card doesn't change the General tab
    dlg._show_workbook(1)  # the General tab's choice moves the card along
    assert card.selected() == 1


def test_a_row_without_a_tag_shows_no_empty_pill(qtbot):
    from reportflow.ui.windows.output_preview import OutputPreview

    card = OutputPreview()
    qtbot.addWidget(card)
    card.show_plan(_plan(output_dir=r"C:\Reports\out"))
    assert card.folder.tag.isHidden()  # "Saved in" has no tag
    assert not card.rows[0].tag.isHidden() and card.rows[0].tag.text() == "kept on disk"

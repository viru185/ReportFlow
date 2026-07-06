"""Shared core library for ReportFlow.

Must not import PySide6 (UI) or xlwings/pywin32 (worker) so it stays importable from
every process, including the frozen Service and UI executables.
"""

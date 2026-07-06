"""Excel Worker process.

Short-lived and disposable: performs the Excel automation for exactly one job run via
xlwings/COM, writes a structured result, and exits. This is the ONLY package that may import
xlwings / pywin32.
"""

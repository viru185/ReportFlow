"""Windows Service control plane: local API + scheduler + worker launcher.

Control-plane only — it must never open Excel itself. It launches one disposable worker
process per job run.
"""

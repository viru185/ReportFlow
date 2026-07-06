"""DPAPI secret store round-trip (Windows only; no Excel)."""

from __future__ import annotations

from reportflow.core import secrets


def test_set_get_delete(temp_data_root):
    assert secrets.get_secret("smtp_password") is None
    assert secrets.has_secret("smtp_password") is False

    secrets.set_secret("smtp_password", "hunter2-éü")
    assert secrets.has_secret("smtp_password") is True
    assert secrets.get_secret("smtp_password") == "hunter2-éü"

    secrets.delete_secret("smtp_password")
    assert secrets.get_secret("smtp_password") is None


def test_overwrite(temp_data_root):
    secrets.set_secret("k", "one")
    secrets.set_secret("k", "two")
    assert secrets.get_secret("k") == "two"


def test_encrypted_blob_is_not_plaintext(temp_data_root):
    secrets.set_secret("smtp_password", "PLAINTEXTVALUE")
    blob = secrets._secret_path("smtp_password").read_bytes()
    assert b"PLAINTEXTVALUE" not in blob

"""Updater logic tests (version compare + release parsing; network mocked)."""

from __future__ import annotations

import httpx
import pytest

from reportflow import __about__ as about
from reportflow.ui import updater
from reportflow.ui.updater import check_latest, is_newer, parse_version


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v0.3.0", (0, 3, 0)),
        ("0.3.0", (0, 3, 0)),
        ("V1.2.10", (1, 2, 10)),
        ("v1.2.3-rc1", (1, 2, 3)),
        ("garbage", ()),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("v0.3.0", "0.2.1", True),
        ("v0.2.1", "0.2.1", False),
        ("v0.2.0", "0.2.1", False),
        ("v1.0.0", "0.9.9", True),
        ("v0.2.10", "0.2.9", True),
        ("junk", "0.2.1", False),
    ],
)
def test_is_newer(latest, current, newer):
    assert is_newer(latest, current) is newer


def _release(tag: str, with_asset: bool = True) -> dict:
    assets = []
    if with_asset:
        assets = [
            {
                "name": f"ReportFlow-Setup-{tag.lstrip('v')}.exe",
                "browser_download_url": f"https://example.com/{tag}.exe",
                "size": 12345,
            },
            {"name": "reportflow-ui.zip", "browser_download_url": "https://x/z.zip"},
        ]
    return {"tag_name": tag, "body": "notes here", "assets": assets}


def _mock_get(monkeypatch, payload, status=200):
    def fake_get(url, **kw):
        request = httpx.Request("GET", url)
        return httpx.Response(status, json=payload, request=request)

    monkeypatch.setattr(updater.httpx, "get", fake_get)


def test_check_latest_finds_newer(monkeypatch):
    _mock_get(monkeypatch, _release("v99.0.0"))
    info = check_latest()
    assert info is not None
    assert info.version == "99.0.0"
    assert info.installer_url == "https://example.com/v99.0.0.exe"
    assert info.size == 12345
    assert "notes" in info.notes


def test_check_latest_same_version_returns_none(monkeypatch):
    _mock_get(monkeypatch, _release(f"v{about.VERSION}"))
    assert check_latest() is None


def test_check_latest_no_installer_asset(monkeypatch):
    _mock_get(monkeypatch, _release("v99.0.0", with_asset=False))
    info = check_latest()
    assert info is not None and info.installer_url is None


def test_check_latest_swallows_errors(monkeypatch):
    def boom(url, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(updater.httpx, "get", boom)
    assert check_latest() is None

    _mock_get(monkeypatch, {}, status=403)  # rate limited
    assert check_latest() is None

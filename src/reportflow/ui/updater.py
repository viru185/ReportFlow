"""Update check against GitHub releases (pure logic — UI lives in update_dialog).

Network failures (offline, GitHub unreachable, rate-limited) always resolve to "no
update" so the startup check is silent when the internet is unavailable. Unlike the
local API client, these requests DO honor system proxies (trust_env default) — internet
traffic should use them.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from reportflow import __about__ as about

RELEASES_API = "https://api.github.com/repos/viru185/ReportFlow/releases/latest"


@dataclass
class UpdateInfo:
    version: str  # e.g. "0.3.0"
    notes: str
    installer_url: str | None
    size: int | None


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.3.0' / '0.3.0' -> (0, 3, 0). 'v1.2.3-rc1' -> (1, 2, 3); junk -> ()."""
    text = text.strip().lstrip("vV")
    parts: list[int] = []
    for piece in text.split("."):
        digits = ""
        for ch in piece:  # leading digits only — '3-rc1' means 3, not 31
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    lt, ct = parse_version(latest), parse_version(current)
    return bool(lt) and bool(ct) and lt > ct


def _extract(release: dict) -> UpdateInfo | None:
    tag = release.get("tag_name") or ""
    if not is_newer(tag, about.VERSION):
        return None
    installer_url: str | None = None
    size: int | None = None
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("ReportFlow-Setup-") and name.endswith(".exe"):
            installer_url = asset.get("browser_download_url")
            size = asset.get("size")
            break
    return UpdateInfo(
        version=tag.lstrip("vV"),
        notes=(release.get("body") or "").strip(),
        installer_url=installer_url,
        size=size,
    )


def check_latest(timeout: float = 8.0) -> UpdateInfo | None:
    """Return UpdateInfo when a newer release exists; None otherwise (incl. any error)."""
    try:
        resp = httpx.get(
            RELEASES_API,
            timeout=timeout,
            follow_redirects=True,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code != 200:
            return None
        return _extract(resp.json())
    except Exception:  # noqa: BLE001 — offline/unreachable == no update, silently
        return None

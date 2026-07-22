"""Thin HTTP client for the local ReportFlow Service API."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def default_base_url() -> str:
    """Read the API base URL from local config, falling back to the default."""
    try:
        from reportflow.core.config.loader import load_config

        return load_config().ui.api_base_url
    except Exception:  # noqa: BLE001 — config may be missing/unreadable from the UI
        return "http://127.0.0.1:8787"


class ApiClient:
    def __init__(self, base_url: str | None = None, *, timeout: float = 30.0) -> None:
        self.base_url = (base_url or default_base_url()).rstrip("/")
        # trust_env=False: NEVER route localhost API calls through HTTP(S)_PROXY /
        # corporate proxies — browsers bypass proxies for localhost but httpx does not,
        # which made the UI get proxy 403s while the service was perfectly reachable.
        self._client = httpx.Client(timeout=timeout, trust_env=False)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        try:
            resp = self._client.request(method, f"{self.base_url}{path}", **kw)
        except httpx.HTTPError as e:
            logger.warning("API {} {} unreachable: {}", method, path, e)
            raise ApiError(f"service not reachable at {self.base_url}: {e}") from e
        if resp.status_code >= 400:
            detail = _safe_detail(resp)
            logger.warning("API {} {} -> {}: {}", method, path, resp.status_code, detail)
            raise ApiError(detail, resp.status_code)
        logger.debug("API {} {} -> {}", method, path, resp.status_code)
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    # -- system --
    def health(self) -> dict:
        return self._request("GET", "/health")

    def system_status(self) -> dict:
        return self._request("GET", "/system/status")

    def get_config(self) -> dict:
        return self._request("GET", "/config")

    def send_dev_logs(self, note: str = "") -> dict:
        return self._request("POST", "/system/send-dev-logs", json={"note": note})

    def export_logs(self, note: str = "") -> dict:
        return self._request("POST", "/system/export-logs", json={"note": note})

    def purge_logs(self, older_than_days: int | None = None, *, everything: bool = False) -> dict:
        payload: dict[str, Any] = {"all": everything}
        if older_than_days is not None:
            payload["older_than_days"] = older_than_days
        return self._request("POST", "/system/purge-logs", json=payload)

    def get_service_account(self) -> dict:
        return self._request("GET", "/system/service-account")

    def set_service_account(self, user: str, password: str) -> dict:
        return self._request(
            "POST", "/system/service-account", json={"user": user, "password": password}
        )

    # -- jobs --
    def list_jobs(self) -> list[dict]:
        return self._request("GET", "/jobs")

    def get_job(self, name: str) -> dict:
        return self._request("GET", f"/jobs/{name}")

    def create_job(self, job: dict) -> dict:
        return self._request("POST", "/jobs", json=job)

    def update_job(self, name: str, job: dict) -> dict:
        return self._request("PUT", f"/jobs/{name}", json=job)

    def delete_job(self, name: str) -> dict:
        return self._request("DELETE", f"/jobs/{name}")

    def run_job(self, name: str) -> dict:
        return self._request("POST", f"/jobs/{name}/run")

    def dry_run_job(self, name: str) -> dict:
        return self._request("POST", f"/jobs/{name}/dry-run")

    def set_job_stage(self, name: str, stage: str) -> dict:
        return self._request("POST", f"/jobs/{name}/stage", json={"stage": stage})

    # -- runs --
    def list_runs(self, job: str | None = None, limit: int = 50) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if job:
            params["job"] = job
        return self._request("GET", "/runs", params=params)

    def get_run(self, run_id: str) -> dict:
        return self._request("GET", f"/runs/{run_id}")

    def get_run_log(self, run_id: str) -> dict:
        return self._request("GET", f"/runs/{run_id}/log")

    # -- workbook / email --
    def workbook_sheets(self, path: str) -> list[str]:
        return self._request("POST", "/workbook/sheets", json={"path": path})["sheets"]

    def email_preview(self, job_name: str | None = None) -> str:
        payload = {"job_name": job_name} if job_name else {}
        return self._request("POST", "/email/preview", json=payload)["html"]

    def get_email_template(self, job_name: str) -> dict:
        return self._request("GET", f"/jobs/{job_name}/email-template")

    def put_email_template(self, job_name: str, content: str) -> dict:
        return self._request("PUT", f"/jobs/{job_name}/email-template", json={"content": content})

    # -- settings / secrets / logs --
    def update_settings(self, sections: dict) -> dict:
        return self._request("PUT", "/settings", json=sections)

    def smtp_password_status(self) -> bool:
        return bool(self._request("GET", "/system/smtp-password")["set"])

    def set_smtp_password(self, password: str) -> dict:
        return self._request("POST", "/system/smtp-password", json={"password": password})

    def clear_smtp_password(self) -> dict:
        return self._request("DELETE", "/system/smtp-password")

    def smtp_test(self, smtp: dict) -> dict:
        return self._request("POST", "/system/smtp-test", json=smtp)

    def system_logs(self, process: str = "service", tail: int = 500) -> str:
        return self._request("GET", "/system/logs", params={"process": process, "tail": tail})[
            "log"
        ]


def _safe_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and "detail" in data:
            return str(data["detail"])
    except Exception:  # noqa: BLE001
        pass
    return f"HTTP {resp.status_code}"

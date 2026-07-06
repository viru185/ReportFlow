"""Thin HTTP client for the local ReportFlow Service API."""

from __future__ import annotations

from typing import Any

import httpx


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
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        try:
            resp = self._client.request(method, f"{self.base_url}{path}", **kw)
        except httpx.HTTPError as e:
            raise ApiError(f"service not reachable: {e}") from e
        if resp.status_code >= 400:
            detail = _safe_detail(resp)
            raise ApiError(detail, resp.status_code)
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

    def send_dev_logs(self) -> dict:
        return self._request("POST", "/system/send-dev-logs")

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

    def test_job(self, name: str) -> dict:
        return self._request("POST", f"/jobs/{name}/test")

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


def _safe_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and "detail" in data:
            return str(data["detail"])
    except Exception:  # noqa: BLE001
        pass
    return f"HTTP {resp.status_code}"

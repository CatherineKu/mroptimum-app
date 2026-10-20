"""Low-level authenticated client for the shared CloudMR Brain API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .errors import BrainAPIError, ConfigurationError


@dataclass
class BrainCredentials:
    root: str
    email: str
    password: str


class CloudMRBrainClient:
    def __init__(self, credentials: BrainCredentials, session: requests.Session | None = None):
        if not all([credentials.root, credentials.email, credentials.password]):
            raise ConfigurationError("CloudMR Brain credentials are not configured")
        self.root = credentials.root.rstrip("/")
        self.credentials = credentials
        self.session = session or requests.Session()
        self._id_token: str | None = None

    def submit(self, payload: dict) -> dict:
        return self._request("POST", "/api/pipeline/queue_job", json=payload)

    def list_files(self, cloudapp_name: str) -> list[dict]:
        """List files visible to this authenticated Brain identity.

        This deliberately returns Brain's raw response only to the trusted tool
        layer. ``MROToolService`` is responsible for allowlisting fields before
        anything reaches an LLM or chat client.
        """
        response = self._request(
            "GET",
            "/api/data",
            params={"cloudapp_name": cloudapp_name},
        )
        if isinstance(response, list):
            return response
        # Tolerate either of the response wrappers used by older Brain clients.
        if isinstance(response, dict):
            for key in ("data", "items", "files"):
                if isinstance(response.get(key), list):
                    return response[key]
        raise BrainAPIError("CloudMR Brain returned an invalid file-list response")

    def list_computing_units(self, app_name: str, mode: str) -> list[dict]:
        """Return the authenticated user's currently visible computing units.

        The trusted tool layer uses this immediately before a Mode 2
        submission, rather than allowing Brain to auto-select an obsolete
        registration from a mode-only request.
        """
        response = self._request(
            "GET",
            "/api/computing-unit/list",
            params={"app_name": app_name, "mode": mode},
        )
        if not isinstance(response, dict):
            raise BrainAPIError("CloudMR Brain returned an invalid computing-unit response")

        units = response.get("computingUnits")
        if not isinstance(units, list):
            units = response.get(mode, [])
        if not isinstance(units, list):
            raise BrainAPIError("CloudMR Brain returned an invalid computing-unit list")
        return [unit for unit in units if isinstance(unit, dict) and unit.get("mode") == mode]

    def get_pipeline(self, pipeline_id: str) -> dict:
        response = self._request("GET", f"/api/pipeline/{pipeline_id}")
        # The current Brain API returns [true, details] for this endpoint.
        if isinstance(response, list) and len(response) == 2 and response[0] is True:
            return response[1]
        return response

    def _authenticate(self) -> str:
        response = self.session.post(
            f"{self.root}/api/auth/login",
            json={"email": self.credentials.email, "password": self.credentials.password},
            timeout=20,
        )
        body = self._decode(response)
        token = body.get("id_token") if isinstance(body, dict) else None
        if not response.ok or not token:
            raise BrainAPIError("CloudMR Brain authentication failed")
        self._id_token = token
        return token

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        token = self._id_token or self._authenticate()
        response = self.session.request(
            method,
            f"{self.root}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
            **kwargs,
        )
        if response.status_code == 401:
            self._id_token = None
            response = self.session.request(
                method,
                f"{self.root}{path}",
                headers={"Authorization": f"Bearer {self._authenticate()}"},
                timeout=30,
                **kwargs,
            )
        body = self._decode(response)
        if not response.ok:
            raise BrainAPIError(f"CloudMR Brain request failed (HTTP {response.status_code})")
        return body

    @staticmethod
    def _decode(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"message": response.text[:500]}

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

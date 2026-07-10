from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from music_ai_control_plane import Settings
from music_ai_control_plane.storage import MemoryObjectStore

PRIMARY_TOKEN = "primary-tenant-token-0123456789abcdef"
SECONDARY_TOKEN = "secondary-tenant-token-0123456789abcd"
PEPPER = "control-plane-test-pepper-0123456789abcdef"


@dataclass(slots=True)
class Harness:
    app: FastAPI
    client: TestClient
    settings: Settings
    store: MemoryObjectStore
    primary_token: str
    primary_tenant_id: UUID
    secondary_token: str
    secondary_tenant_id: UUID

    def headers(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.primary_token}"}

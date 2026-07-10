from __future__ import annotations

from pathlib import Path

import pytest
from control_plane_testkit import (
    PEPPER,
    PRIMARY_TOKEN,
    SECONDARY_TOKEN,
    Harness,
)
from fastapi.testclient import TestClient
from music_ai_control_plane import Settings, create_app
from music_ai_control_plane.models import Tenant
from music_ai_control_plane.security import ALL_SCOPES, ensure_bootstrap_credential
from music_ai_control_plane.storage import MemoryObjectStore
from sqlalchemy import select


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'control-plane.db'}",
        object_store_root=tmp_path / "objects",
        token_pepper=PEPPER,
        raw_audio_ttl_seconds=900,
        bootstrap_tenant_slug="primary",
        bootstrap_tenant_name="Primary Tenant",
        bootstrap_api_token=PRIMARY_TOKEN,
    )
    store = MemoryObjectStore()
    app = create_app(settings, store)
    with TestClient(app) as client:
        with app.state.database.session() as session:
            primary = session.scalar(select(Tenant).where(Tenant.slug == "primary"))
            assert primary is not None
            secondary = ensure_bootstrap_credential(
                session,
                tenant_slug="secondary",
                tenant_name="Secondary Tenant",
                token=SECONDARY_TOKEN,
                pepper=PEPPER,
                scopes=ALL_SCOPES,
            )
        yield Harness(
            app=app,
            client=client,
            settings=settings,
            store=store,
            primary_token=PRIMARY_TOKEN,
            primary_tenant_id=primary.id,
            secondary_token=SECONDARY_TOKEN,
            secondary_tenant_id=secondary.id,
        )

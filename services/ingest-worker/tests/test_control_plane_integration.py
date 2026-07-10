from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from ingest_testkit import (
    SOURCE_PAYLOAD,
    FixtureF0Provider,
    FixtureSeparationProvider,
    make_analysis,
    make_authorized_models,
    make_job,
    make_stems,
)
from music_ai_control_plane import Settings, create_app
from music_ai_control_plane.models import SongManifestRecord, StoredAsset, Tenant
from music_ai_control_plane.storage import MemoryObjectStore
from music_ai_ingest.pipeline import IngestPipeline
from music_ai_ingest.publisher import ControlPlanePublisher
from sqlalchemy import func, select

TOKEN = "ingest-integration-token-0123456789abcdef"
PEPPER = "ingest-integration-pepper-0123456789abcdef"


def test_pipeline_publishes_idempotently_through_real_control_plane(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'control-plane.db'}",
        object_store_root=tmp_path / "objects",
        token_pepper=PEPPER,
        bootstrap_tenant_slug="ingest-test",
        bootstrap_tenant_name="Ingest Test",
        bootstrap_api_token=TOKEN,
    )
    store = MemoryObjectStore()
    app = create_app(settings, store)

    with TestClient(app) as client:
        with app.state.database.session() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == "ingest-test"))
            assert tenant is not None

        digest = hashlib.sha256(SOURCE_PAYLOAD).hexdigest()
        response = client.post(
            "/v1/songs",
            headers=_headers(),
            json={
                "display_name": "Synthetic integration song",
                "rights_basis": "Synthetic test fixture",
                "source_sha256": digest,
                "source_byte_length": len(SOURCE_PAYLOAD),
                "source_media_type": "audio/wav",
            },
        )
        assert response.status_code == 200
        song_id = UUID(response.json()["id"])
        response = client.put(
            f"/v1/songs/{song_id}/content",
            headers={**_headers(), "Content-Type": "audio/wav"},
            content=SOURCE_PAYLOAD,
        )
        assert response.status_code == 200

        job = make_job(
            tenant_id=tenant.id,
            song_id=song_id,
            produced_at=datetime.now(UTC),
        )
        authorizer, separation_binding, f0_binding, _ = make_authorized_models(tmp_path / "models")
        publisher = ControlPlanePublisher(
            "http://testserver",
            TOKEN,
            client=client,
        )
        pipeline = IngestPipeline(
            separation_provider=FixtureSeparationProvider(
                separation_binding,
                make_stems(job),
            ),
            f0_provider=FixtureF0Provider(f0_binding, make_analysis(job)),
            authorizer=authorizer,
            publisher=publisher,
        )

        first = pipeline.run(job)
        second = pipeline.run(job)

        assert first == second
        assert first.manifest.gate_status == "accepted"
        response = client.get(f"/v1/songs/{song_id}", headers=_headers())
        assert response.status_code == 200
        assert response.json()["state"] == "accepted"
        assert len(store.objects) == 4

        with app.state.database.session() as session:
            asset_count = session.scalar(
                select(func.count()).select_from(StoredAsset).where(StoredAsset.song_id == song_id)
            )
            manifest_count = session.scalar(
                select(func.count())
                .select_from(SongManifestRecord)
                .where(SongManifestRecord.song_id == song_id)
            )
            assert asset_count == 3
            assert manifest_count == 1


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}

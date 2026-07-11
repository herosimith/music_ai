from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from music_ai_contracts.models import ArtifactPointer
from music_ai_control_plane import Settings, create_app
from music_ai_control_plane.models import ScoreRecord, StoredAsset, Tenant
from music_ai_control_plane.storage import MemoryObjectStore
from music_ai_scoring_service.publisher import ControlPlaneScoringPublisher
from music_ai_scoring_service.types import ScoringJob
from scoring_service_testkit import (
    make_manifest,
    make_phrase,
    make_pipeline,
    make_transport,
)
from sqlalchemy import func, select

TOKEN = "scoring-integration-token-0123456789abcdef"
PEPPER = "scoring-integration-pepper-0123456789abcdef"


def test_scoring_pipeline_archives_evidence_and_publishes_idempotently(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'control-plane.db'}",
        object_store_root=tmp_path / "objects",
        token_pepper=PEPPER,
        bootstrap_tenant_slug="scoring-test",
        bootstrap_tenant_name="Scoring Test",
        bootstrap_api_token=TOKEN,
    )
    store = MemoryObjectStore()
    app = create_app(settings, store)
    with TestClient(app) as client:
        with app.state.database.session() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == "scoring-test"))
            assert tenant is not None

        source = b"synthetic-scoring-song-source"
        source_sha256 = hashlib.sha256(source).hexdigest()
        response = client.post(
            "/v1/songs",
            headers=_headers(),
            json={
                "display_name": "Synthetic scoring song",
                "rights_basis": "Synthetic test fixture",
                "source_sha256": source_sha256,
                "source_byte_length": len(source),
                "source_media_type": "audio/wav",
            },
        )
        assert response.status_code == 200, response.text
        song_id = UUID(response.json()["id"])
        response = client.put(
            f"/v1/songs/{song_id}/content",
            headers={**_headers(), "Content-Type": "audio/wav"},
            content=source,
        )
        assert response.status_code == 200

        source_pointer = ArtifactPointer(
            artifact_id=f"song-source:{song_id}",
            kind="source",
            sha256=source_sha256,
        )
        vocal_pointer = _publish_reference_asset(
            client,
            song_id,
            kind="vocal",
            payload=b"reference-vocal",
            media_type="audio/wav",
            model_release="separator.test.v1",
        )
        f0_pointer = _publish_reference_asset(
            client,
            song_id,
            kind="f0",
            payload=b'{"reference":"f0"}',
            media_type="application/json",
            model_release="reference-f0.test.v1",
        )
        manifest_time = datetime.now(UTC)
        manifest = make_manifest(
            tenant_id=tenant.id,
            song_id=song_id,
            artifacts=[source_pointer, vocal_pointer, f0_pointer],
        ).model_copy(update={"produced_at": manifest_time})
        response = client.post(
            f"/internal/v1/songs/{song_id}/manifests",
            headers=_headers(),
            json=manifest.model_dump(mode="json"),
        )
        assert response.status_code == 200
        manifest_id = UUID(response.json()["id"])

        response = client.post(
            "/v1/sessions",
            headers=_headers(),
            json={
                "song_id": str(song_id),
                "manifest_record_id": str(manifest_id),
                "calibration_version": manifest.versions.calibration_version,
            },
        )
        assert response.status_code == 200
        session_id = UUID(response.json()["id"])

        phrase, phrase_payload = make_phrase(
            tenant_id=tenant.id,
            session_id=session_id,
        )
        capture_time = datetime.now(UTC) - timedelta(seconds=1)
        phrase = phrase.model_copy(update={"captured_at": capture_time})
        response = client.post(
            "/v1/phrases",
            headers=_headers(),
            json=phrase.model_dump(mode="json"),
        )
        assert response.status_code == 200, response.text
        response = client.put(
            f"/v1/phrases/{phrase.phrase_id}/content",
            headers={**_headers(), "Content-Type": "application/octet-stream"},
            content=phrase_payload,
        )
        assert response.status_code == 200

        transport = make_transport(
            tenant_id=tenant.id,
            session_id=session_id,
            phrase_id=phrase.phrase_id,
        )
        transport = transport.model_copy(
            update={
                "events": [
                    event.model_copy(
                        update={"captured_at": capture_time - timedelta(seconds=1 - index)}
                    )
                    for index, event in enumerate(transport.events)
                ],
                "produced_at": capture_time + timedelta(milliseconds=100),
            }
        )
        score_time = datetime.now(UTC) + timedelta(milliseconds=10)
        job = ScoringJob(
            phrase=phrase,
            audio_payload=phrase_payload,
            transport=transport,
            manifest=manifest,
            manifest_record_id=manifest_id,
            region_ids=[manifest.scorable_regions[0].region_id],
            produced_at=score_time,
        )
        pipeline, _, _ = make_pipeline(tmp_path / "models")
        computation = pipeline.run(job)
        publisher = ControlPlaneScoringPublisher(
            "http://testserver",
            TOKEN,
            client=client,
        )

        first_score_id, first_evidence = publisher.publish(song_id, manifest_id, computation)
        second_score_id, second_evidence = publisher.publish(song_id, manifest_id, computation)

        assert first_score_id == second_score_id
        assert first_evidence == second_evidence
        response = client.get(f"/v1/sessions/{session_id}/scores", headers=_headers())
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [str(first_score_id)]
        assert response.json()[0]["score"]["user_features_sha256"] == computation.evidence[1].sha256

        with app.state.database.session() as session:
            evidence_kinds = set(
                session.scalars(
                    select(StoredAsset.kind).where(
                        StoredAsset.song_id == song_id,
                        StoredAsset.kind.in_(["transport", "user_features"]),
                    )
                )
            )
            score_count = session.scalar(
                select(func.count()).select_from(ScoreRecord).where(ScoreRecord.song_id == song_id)
            )
            assert evidence_kinds == {"transport", "user_features"}
            assert score_count == 1


def _publish_reference_asset(
    client: TestClient,
    song_id: UUID,
    *,
    kind: str,
    payload: bytes,
    media_type: str,
    model_release: str,
) -> ArtifactPointer:
    digest = hashlib.sha256(payload).hexdigest()
    response = client.post(
        f"/internal/v1/songs/{song_id}/assets",
        headers=_headers(),
        json={
            "kind": kind,
            "sha256": digest,
            "byte_length": len(payload),
            "media_type": media_type,
            "model_release": model_release,
        },
    )
    assert response.status_code == 200
    asset_id = UUID(response.json()["id"])
    response = client.put(
        f"/internal/v1/assets/{asset_id}/content",
        headers={**_headers(), "Content-Type": media_type},
        content=payload,
    )
    assert response.status_code == 200
    return ArtifactPointer(
        artifact_id=str(asset_id),
        kind=kind,
        sha256=digest,
        model_release=model_release,
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}

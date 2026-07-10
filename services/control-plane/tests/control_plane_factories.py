from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from control_plane_testkit import Harness
from music_ai_contracts.models import (
    ArtifactPointer,
    GateStatus,
    NumericMetric,
    PhraseAudioV1,
    ReferenceSource,
    ScorableRegion,
    ScoreV1,
    SongManifestV1,
    VersionStamp,
)

CALIBRATION_VERSION = "calibration.test.v1"


def create_ready_song(
    harness: Harness,
    *,
    token: str | None = None,
    tenant_id: UUID | None = None,
    source_payload: bytes = b"synthetic-song-source",
) -> tuple[UUID, SongManifestV1, UUID]:
    selected_token = token or harness.primary_token
    selected_tenant = tenant_id or harness.primary_tenant_id
    headers = harness.headers(selected_token)
    source_sha = hashlib.sha256(source_payload).hexdigest()
    response = harness.client.post(
        "/v1/songs",
        headers=headers,
        json={
            "display_name": "Synthetic Song",
            "rights_basis": "Synthetic test fixture",
            "source_sha256": source_sha,
            "source_byte_length": len(source_payload),
            "source_media_type": "audio/wav",
        },
    )
    assert response.status_code == 200, response.text
    song_id = UUID(response.json()["id"])
    response = harness.client.put(
        f"/v1/songs/{song_id}/content",
        headers={**headers, "Content-Type": "audio/wav"},
        content=source_payload,
    )
    assert response.status_code == 200, response.text

    pointers = [
        ArtifactPointer(
            artifact_id=f"song-source:{song_id}",
            kind="source",
            sha256=source_sha,
        )
    ]
    for kind in ("vocal", "accompaniment", "f0"):
        payload = f"{kind}-artifact".encode()
        digest = hashlib.sha256(payload).hexdigest()
        response = harness.client.post(
            f"/internal/v1/songs/{song_id}/assets",
            headers=headers,
            json={
                "kind": kind,
                "sha256": digest,
                "byte_length": len(payload),
                "media_type": "application/octet-stream",
                "model_release": "reference.test.v1",
            },
        )
        assert response.status_code == 200, response.text
        asset_id = response.json()["id"]
        response = harness.client.put(
            f"/internal/v1/assets/{asset_id}/content",
            headers={**headers, "Content-Type": "application/octet-stream"},
            content=payload,
        )
        assert response.status_code == 200, response.text
        pointers.append(
            ArtifactPointer(
                artifact_id=asset_id,
                kind=kind,
                sha256=digest,
                model_release="reference.test.v1",
            )
        )

    manifest = SongManifestV1(
        schema_version="song-manifest.v1",
        tenant_id=selected_tenant,
        song_id=song_id,
        reference_source=ReferenceSource.INDEPENDENT_STEMS,
        rights_basis="Synthetic test fixture",
        source_sha256=source_sha,
        sample_rate=48_000,
        duration_samples=96_000,
        gate_status=GateStatus.ACCEPTED,
        scorable_vocal_coverage=1.0,
        quality_issues=[],
        artifacts=pointers,
        scorable_regions=[
            ScorableRegion(
                region_id="note-01",
                start_sample=0,
                end_sample=48_000,
                target_f0_hz=440.0,
                reference_confidence=0.98,
                monophonic_confidence=0.97,
            )
        ],
        versions=VersionStamp(
            pipeline_version="reference-pipeline.test.v1",
            model_release="reference.test.v1",
            score_version="score.v1",
            calibration_version=CALIBRATION_VERSION,
        ),
        produced_at=datetime.now(UTC),
    )
    response = harness.client.post(
        f"/internal/v1/songs/{song_id}/manifests",
        headers=headers,
        json=manifest.model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    return song_id, manifest, UUID(response.json()["id"])


def create_phrase_and_score(
    harness: Harness,
    song_id: UUID,
    manifest_record_id: UUID,
    *,
    token: str | None = None,
    tenant_id: UUID | None = None,
    write_score: bool = True,
) -> tuple[UUID, UUID, ScoreV1, str]:
    selected_token = token or harness.primary_token
    selected_tenant = tenant_id or harness.primary_tenant_id
    headers = harness.headers(selected_token)
    response = harness.client.post(
        "/v1/sessions",
        headers=headers,
        json={
            "song_id": str(song_id),
            "manifest_record_id": str(manifest_record_id),
            "calibration_version": CALIBRATION_VERSION,
        },
    )
    assert response.status_code == 200, response.text
    session_id = UUID(response.json()["id"])

    audio = b"\x00\x01" * 960
    phrase_id = uuid4()
    phrase = PhraseAudioV1(
        schema_version="phrase-audio.v1",
        tenant_id=selected_tenant,
        session_id=session_id,
        phrase_id=phrase_id,
        sequence=0,
        sample_start=0,
        sample_end=960,
        sample_rate=48_000,
        channels=1,
        codec="pcm_s16le",
        sha256=hashlib.sha256(audio).hexdigest(),
        byte_length=len(audio),
        calibration_version=CALIBRATION_VERSION,
        captured_at=datetime.now(UTC),
        idempotency_key=f"phrase-{phrase_id}",
    )
    response = harness.client.post(
        "/v1/phrases",
        headers=headers,
        json=phrase.model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    response = harness.client.put(
        f"/v1/phrases/{phrase_id}/content",
        headers={**headers, "Content-Type": "application/octet-stream"},
        content=audio,
    )
    assert response.status_code == 200, response.text

    score = ScoreV1(
        schema_version="score.v1",
        tenant_id=selected_tenant,
        session_id=session_id,
        phrase_id=phrase_id,
        song_id=song_id,
        reference_source=ReferenceSource.INDEPENDENT_STEMS,
        scored_coverage=1.0,
        metrics={
            "timeline_coverage": NumericMetric(
                value=1.0,
                unit="ratio",
                confidence=1.0,
                coverage=1.0,
            )
        },
        corrections=[],
        abstained_reason=None,
        versions=VersionStamp(
            pipeline_version="scoring-core.v1",
            model_release="user-f0.test.v1",
            score_version="score.v1",
            calibration_version=CALIBRATION_VERSION,
        ),
        produced_at=datetime.now(UTC),
    )
    idempotency_key = f"score-{phrase_id}"
    if write_score:
        response = harness.client.post(
            "/internal/v1/scores",
            headers={
                **headers,
                "Idempotency-Key": idempotency_key,
                "Reference-Manifest-Id": str(manifest_record_id),
            },
            json=score.model_dump(mode="json"),
        )
        assert response.status_code == 200, response.text
    return session_id, phrase_id, score, idempotency_key

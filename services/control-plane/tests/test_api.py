from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from control_plane_factories import create_phrase_and_score, create_ready_song
from control_plane_testkit import PEPPER, Harness
from music_ai_contracts.models import GateStatus
from music_ai_control_plane.models import (
    ApiCredential,
    DeletionRequest,
    DeletionStatus,
    DeletionTask,
    ImmutableManifestError,
    ImmutableScoreError,
    PhraseArtifact,
    PracticeSession,
    ScoreRecord,
    Song,
    SongManifestRecord,
    StoredAsset,
)
from music_ai_control_plane.security import ensure_bootstrap_credential
from music_ai_control_plane.service import ControlPlaneService
from music_ai_control_plane.storage import MemoryObjectStore
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


def test_health_is_public_but_resources_require_authentication(harness: Harness) -> None:
    assert harness.client.get("/health").json() == {"status": "ok"}
    assert harness.client.get("/ready").json() == {"status": "ok"}

    response = harness.client.get("/v1/songs/11111111-1111-4111-8111-111111111111")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"

    response = harness.client.get(
        "/v1/songs/11111111-1111-4111-8111-111111111111",
        headers=harness.headers("short-token"),
    )
    assert response.status_code == 401
    with harness.app.state.database.session() as session:
        credential = session.scalar(select(ApiCredential))
        assert credential is not None
        assert credential.token_digest != harness.primary_token
        assert len(credential.token_digest) == 64


def test_end_to_end_score_write_is_idempotent_and_version_bound(harness: Harness) -> None:
    song_id, manifest, manifest_id = create_ready_song(harness)
    session_id, phrase_id, score, idempotency_key = create_phrase_and_score(
        harness,
        song_id,
        manifest_id,
    )

    response = harness.client.post(
        "/internal/v1/scores",
        headers={
            **harness.headers(),
            "Idempotency-Key": idempotency_key,
            "Reference-Manifest-Id": str(manifest_id),
        },
        json=score.model_dump(mode="json"),
    )
    assert response.status_code == 200
    first_id = response.json()["id"]

    listed = harness.client.get(
        f"/v1/sessions/{session_id}/scores",
        headers=harness.headers(),
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [first_id]
    assert listed.json()[0]["phrase_id"] == str(phrase_id)
    assert listed.json()[0]["manifest_record_id"] == str(manifest_id)

    coached = harness.client.post(
        f"/v1/scores/{first_id}/coach?locale=en",
        headers=harness.headers(),
    )
    assert coached.status_code == 200
    assert coached.json()["provider"] == "rules.v1"
    assert coached.json()["used_fallback"] is False
    assert coached.json()["actions"][0]["action_type"] == "text"
    assert "No issue" in coached.json()["actions"][0]["message"]
    repeated = harness.client.post(
        f"/v1/scores/{first_id}/coach?locale=en",
        headers=harness.headers(),
    )
    assert repeated.status_code == 200
    assert repeated.json() == coached.json()

    isolated = harness.client.post(
        f"/v1/scores/{first_id}/coach",
        headers=harness.headers(harness.secondary_token),
    )
    assert isolated.status_code == 404

    changed_manifest = manifest.model_copy(
        update={
            "produced_at": datetime.now(UTC),
            "scorable_regions": [
                manifest.scorable_regions[0].model_copy(update={"target_f0_hz": 442.0})
            ],
        }
    )
    response = harness.client.post(
        f"/internal/v1/songs/{song_id}/manifests",
        headers=harness.headers(),
        json=changed_manifest.model_dump(mode="json"),
    )
    assert response.status_code == 200
    newer_manifest_id = response.json()["id"]
    assert newer_manifest_id != str(manifest_id)

    response = harness.client.post(
        "/internal/v1/scores",
        headers={
            **harness.headers(),
            "Idempotency-Key": idempotency_key,
            "Reference-Manifest-Id": newer_manifest_id,
        },
        json=score.model_dump(mode="json"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"

    changed_score = score.model_copy(update={"produced_at": datetime.now(UTC)})
    response = harness.client.post(
        "/internal/v1/scores",
        headers={
            **harness.headers(),
            "Idempotency-Key": idempotency_key,
            "Reference-Manifest-Id": str(manifest_id),
        },
        json=changed_score.model_dump(mode="json"),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_score_evidence_must_be_bound_registered_and_available(harness: Harness) -> None:
    song_id, _, manifest_id = create_ready_song(harness)
    _, _, score, idempotency_key = create_phrase_and_score(
        harness,
        song_id,
        manifest_id,
        write_score=False,
    )
    headers = {
        **harness.headers(),
        "Reference-Manifest-Id": str(manifest_id),
    }

    missing = score.model_copy(update={"user_features_sha256": None})
    response = harness.client.post(
        "/internal/v1/scores",
        headers={**headers, "Idempotency-Key": f"{idempotency_key}-missing"},
        json=missing.model_dump(mode="json"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"

    unregistered = score.model_copy(update={"user_features_sha256": "f" * 64})
    response = harness.client.post(
        "/internal/v1/scores",
        headers={**headers, "Idempotency-Key": f"{idempotency_key}-unknown"},
        json=unregistered.model_dump(mode="json"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"

    with harness.app.state.database.session() as session:
        asset = session.scalar(
            select(StoredAsset).where(
                StoredAsset.song_id == song_id,
                StoredAsset.kind == "user_features",
            )
        )
        assert asset is not None and asset.object_key is not None
        harness.store.delete(asset.object_key)
    response = harness.client.post(
        "/internal/v1/scores",
        headers={**headers, "Idempotency-Key": idempotency_key},
        json=score.model_dump(mode="json"),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_session_reference_does_not_follow_a_newer_rejected_manifest(
    harness: Harness,
) -> None:
    song_id, manifest, accepted_manifest_id = create_ready_song(harness)
    _, _, score, idempotency_key = create_phrase_and_score(
        harness,
        song_id,
        accepted_manifest_id,
        write_score=False,
    )
    rejected = manifest.model_copy(
        update={
            "gate_status": GateStatus.REJECTED,
            "scorable_vocal_coverage": 0.0,
            "scorable_regions": [],
            "produced_at": datetime.now(UTC),
        }
    )
    response = harness.client.post(
        f"/internal/v1/songs/{song_id}/manifests",
        headers=harness.headers(),
        json=rejected.model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert (
        harness.client.get(f"/v1/songs/{song_id}", headers=harness.headers()).json()["state"]
        == "rejected"
    )

    response = harness.client.post(
        "/internal/v1/scores",
        headers={
            **harness.headers(),
            "Idempotency-Key": idempotency_key,
            "Reference-Manifest-Id": str(accepted_manifest_id),
        },
        json=score.model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert response.json()["manifest_record_id"] == str(accepted_manifest_id)


def test_cross_tenant_resource_access_is_indistinguishable_from_missing(
    harness: Harness,
) -> None:
    source = b"shared-source-is-private-per-tenant"
    song_id, _, _ = create_ready_song(harness, source_payload=source)
    secondary_headers = harness.headers(harness.secondary_token)

    for method, path in (
        ("get", f"/v1/songs/{song_id}"),
        ("delete", f"/v1/songs/{song_id}"),
    ):
        response = getattr(harness.client, method)(path, headers=secondary_headers)
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    response = harness.client.post(
        "/v1/sessions",
        headers=secondary_headers,
        json={
            "song_id": str(song_id),
            "manifest_record_id": "11111111-1111-4111-8111-111111111111",
            "calibration_version": "calibration.test.v1",
        },
    )
    assert response.status_code == 404

    digest = hashlib.sha256(source).hexdigest()
    response = harness.client.post(
        "/v1/songs",
        headers=secondary_headers,
        json={
            "display_name": "Tenant-local copy",
            "rights_basis": "Synthetic test fixture",
            "source_sha256": digest,
            "source_byte_length": len(source),
            "source_media_type": "audio/wav",
        },
    )
    assert response.status_code == 200
    assert response.json()["id"] != str(song_id)


def test_database_composite_foreign_keys_reject_cross_tenant_relationships(
    harness: Harness,
) -> None:
    primary_song, _, _ = create_ready_song(harness, source_payload=b"primary-fk-source")
    secondary_song, _, secondary_manifest = create_ready_song(
        harness,
        token=harness.secondary_token,
        tenant_id=harness.secondary_tenant_id,
        source_payload=b"secondary-fk-source",
    )
    assert primary_song != secondary_song
    with harness.app.state.database.session() as session:
        session.add(
            PracticeSession(
                tenant_id=harness.primary_tenant_id,
                song_id=secondary_song,
                manifest_record_id=secondary_manifest,
                calibration_version="calibration.test.v1",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_manifest_cannot_reference_unregistered_artifacts(harness: Harness) -> None:
    song_id, manifest, _ = create_ready_song(harness)
    changed_pointers = list(manifest.artifacts)
    changed_pointers[1] = changed_pointers[1].model_copy(
        update={"artifact_id": "11111111-1111-4111-8111-111111111111"}
    )
    changed = manifest.model_copy(
        update={"artifacts": changed_pointers, "produced_at": datetime.now(UTC)}
    )
    response = harness.client.post(
        f"/internal/v1/songs/{song_id}/manifests",
        headers=harness.headers(),
        json=changed.model_dump(mode="json"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_uploads_enforce_server_metadata_hash_length_type_and_unknown_fields(
    harness: Harness,
) -> None:
    payload = b"declared-song-content"
    digest = hashlib.sha256(payload).hexdigest()
    request = {
        "display_name": "Upload checks",
        "rights_basis": "Synthetic test fixture",
        "source_sha256": digest,
        "source_byte_length": len(payload),
        "source_media_type": "audio/wav",
    }
    response = harness.client.post("/v1/songs", headers=harness.headers(), json=request)
    assert response.status_code == 200
    song_id = response.json()["id"]
    assert response.json()["upload_path"] == f"/v1/songs/{song_id}/content"

    response = harness.client.put(
        f"/v1/songs/{song_id}/content",
        headers={**harness.headers(), "Content-Type": "audio/mpeg"},
        content=payload,
    )
    assert response.status_code == 415

    response = harness.client.put(
        f"/v1/songs/{song_id}/content",
        headers={**harness.headers(), "Content-Type": "audio/wav"},
        content=payload[:-1],
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"

    response = harness.client.put(
        f"/v1/songs/{song_id}/content",
        headers={**harness.headers(), "Content-Type": "audio/wav"},
        content=payload,
    )
    assert response.status_code == 200
    assert response.json()["upload_path"] is None

    stored_key = next(iter(harness.store.objects))
    harness.store.delete(stored_key)
    response = harness.client.put(
        f"/v1/songs/{song_id}/content",
        headers={**harness.headers(), "Content-Type": "audio/wav"},
        content=payload,
    )
    assert response.status_code == 200
    assert harness.store.exists(stored_key)

    response = harness.client.post(
        "/v1/songs",
        headers=harness.headers(),
        json={**request, "object_key": "../../escape"},
    )
    assert response.status_code == 422


def test_plain_ogg_song_source_is_accepted(harness: Harness) -> None:
    payload = b"OggS" + b"\x00" * 128
    digest = hashlib.sha256(payload).hexdigest()
    response = harness.client.post(
        "/v1/songs",
        headers=harness.headers(),
        json={
            "display_name": "Plain Ogg source",
            "rights_basis": "Synthetic test fixture",
            "source_sha256": digest,
            "source_byte_length": len(payload),
            "source_media_type": "audio/ogg",
        },
    )
    assert response.status_code == 200

    response = harness.client.put(
        f"/v1/songs/{response.json()['id']}/content",
        headers={**harness.headers(), "Content-Type": "audio/ogg"},
        content=payload,
    )

    assert response.status_code == 200
    assert response.json()["state"] == "uploaded"
    assert next(iter(harness.store.objects.values())) == payload


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"OggS" + b"\x00" * 256 + b"musicex\x00", "mgg.key_unavailable"),
        (b"\x01\x02" + b"\x00" * 256 + b"QTag", "mgg.encrypted_unsupported"),
        (b"\x01\x02" + b"\x00" * 256 + b"STag", "mgg.encrypted_unsupported"),
    ],
)
def test_encrypted_mgg_is_rejected_before_object_storage(
    harness: Harness,
    payload: bytes,
    expected_code: str,
) -> None:
    digest = hashlib.sha256(payload).hexdigest()
    response = harness.client.post(
        "/v1/songs",
        headers=harness.headers(),
        json={
            "display_name": "Encrypted MGG source",
            "rights_basis": "Synthetic test fixture",
            "source_sha256": digest,
            "source_byte_length": len(payload),
            "source_media_type": "audio/ogg",
        },
    )
    assert response.status_code == 200
    song_id = response.json()["id"]

    response = harness.client.put(
        f"/v1/songs/{song_id}/content",
        headers={**harness.headers(), "Content-Type": "audio/ogg"},
        content=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code
    assert harness.store.objects == {}
    song = harness.client.get(f"/v1/songs/{song_id}", headers=harness.headers())
    assert song.json()["state"] == "pending_upload"


def test_opaque_payload_declared_as_ogg_is_rejected_before_storage(harness: Harness) -> None:
    payload = b"not-an-ogg-container"
    digest = hashlib.sha256(payload).hexdigest()
    response = harness.client.post(
        "/v1/songs",
        headers=harness.headers(),
        json={
            "display_name": "Opaque Ogg source",
            "rights_basis": "Synthetic test fixture",
            "source_sha256": digest,
            "source_byte_length": len(payload),
            "source_media_type": "audio/ogg",
        },
    )
    assert response.status_code == 200

    response = harness.client.put(
        f"/v1/songs/{response.json()['id']}/content",
        headers={**harness.headers(), "Content-Type": "audio/ogg"},
        content=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "media.invalid_container"
    assert harness.store.objects == {}


def test_raw_audio_ttl_removes_object_but_preserves_derived_score(harness: Harness) -> None:
    song_id, _, manifest_id = create_ready_song(harness)
    session_id, phrase_id, score, idempotency_key = create_phrase_and_score(
        harness,
        song_id,
        manifest_id,
    )
    with harness.app.state.database.session() as session:
        phrase = session.get(PhraseArtifact, phrase_id)
        assert phrase is not None and phrase.object_key is not None
        phrase_key = phrase.object_key
        phrase.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert harness.store.exists(phrase_key)

    response = harness.client.post(
        "/internal/v1/maintenance/expire",
        headers=harness.headers(),
    )
    assert response.status_code == 200
    assert response.json() == {
        "expired_audio": 1,
        "completed_tasks": 1,
        "failed_tasks": 0,
    }
    assert not harness.store.exists(phrase_key)

    response = harness.client.get(
        f"/v1/sessions/{session_id}/scores",
        headers=harness.headers(),
    )
    assert response.status_code == 200
    assert len(response.json()) == 1

    response = harness.client.post(
        "/internal/v1/scores",
        headers={
            **harness.headers(),
            "Idempotency-Key": idempotency_key,
            "Reference-Manifest-Id": str(manifest_id),
        },
        json=score.model_dump(mode="json"),
    )
    assert response.status_code == 200

    response = harness.client.put(
        f"/v1/phrases/{phrase_id}/content",
        headers={**harness.headers(), "Content-Type": "application/octet-stream"},
        content=b"\x00\x01" * 960,
    )
    assert response.status_code == 409


def test_object_deletion_retries_without_persisting_provider_details(harness: Harness) -> None:
    song_id, _, manifest_id = create_ready_song(harness)
    _, phrase_id, _, _ = create_phrase_and_score(harness, song_id, manifest_id)
    with harness.app.state.database.session() as session:
        phrase = session.get(PhraseArtifact, phrase_id)
        assert phrase is not None and phrase.object_key is not None
        phrase_key = phrase.object_key
        phrase.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    class FailOnceStore(MemoryObjectStore):
        failed = False

        def delete(self, key: str) -> None:
            if not self.failed:
                self.failed = True
                raise RuntimeError(f"provider-secret for {key}")
            super().delete(key)

    flaky = FailOnceStore()
    flaky.objects = harness.store.objects
    harness.app.state.object_store = flaky
    response = harness.client.post(
        "/internal/v1/maintenance/expire",
        headers=harness.headers(),
    )
    assert response.status_code == 200
    assert response.json()["expired_audio"] == 1
    assert response.json()["completed_tasks"] == 0
    assert flaky.exists(phrase_key)

    retry_at = datetime.now(UTC) + timedelta(seconds=10)
    with harness.app.state.database.session() as session:
        task = session.scalar(
            select(DeletionTask).where(DeletionTask.tenant_id == harness.primary_tenant_id)
        )
        deletion = session.scalar(
            select(DeletionRequest).where(DeletionRequest.tenant_id == harness.primary_tenant_id)
        )
        assert task is not None and deletion is not None
        assert task.last_error == "RuntimeError: object deletion failed"
        assert "provider-secret" not in task.last_error
        service = ControlPlaneService(session, flaky, harness.settings)
        assert service.process_deletions(harness.primary_tenant_id, now=retry_at) == (1, 0)
        assert service.get_deletion(harness.primary_tenant_id, deletion.id).status == "completed"
    assert not flaky.exists(phrase_key)


def test_song_deletion_tombstones_first_then_clears_all_objects(harness: Harness) -> None:
    primary_song, _, primary_manifest = create_ready_song(
        harness,
        source_payload=b"primary-delete-source",
    )
    session_id, _, _, _ = create_phrase_and_score(
        harness,
        primary_song,
        primary_manifest,
    )
    secondary_song, _, _ = create_ready_song(
        harness,
        token=harness.secondary_token,
        tenant_id=harness.secondary_tenant_id,
        source_payload=b"secondary-preserved-source",
    )
    assert len(harness.store.objects) == 11

    response = harness.client.delete(
        f"/v1/songs/{primary_song}",
        headers=harness.headers(),
    )
    assert response.status_code == 202
    deletion_id = response.json()["id"]
    assert response.json()["status"] == "pending"
    assert (
        harness.client.get(f"/v1/songs/{primary_song}", headers=harness.headers()).status_code
        == 404
    )

    response = harness.client.post(
        "/internal/v1/maintenance/expire",
        headers=harness.headers(),
    )
    assert response.status_code == 200
    assert response.json()["completed_tasks"] == 7
    assert len(harness.store.objects) == 4
    assert (
        harness.client.get(
            f"/v1/songs/{secondary_song}",
            headers=harness.headers(harness.secondary_token),
        ).status_code
        == 200
    )

    response = harness.client.get(
        f"/v1/deletions/{deletion_id}",
        headers=harness.headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["last_error"] is None

    response = harness.client.delete(
        f"/v1/songs/{primary_song}",
        headers=harness.headers(),
    )
    assert response.status_code == 202
    assert response.json()["id"] == deletion_id
    assert (
        harness.client.get(
            f"/v1/sessions/{session_id}/scores",
            headers=harness.headers(),
        ).status_code
        == 404
    )

    with harness.app.state.database.session() as session:
        score = session.scalar(select(ScoreRecord).where(ScoreRecord.song_id == primary_song))
        manifest = session.scalar(
            select(SongManifestRecord).where(SongManifestRecord.song_id == primary_song)
        )
        assert score is None
        assert manifest is None


def test_deletion_reconciliation_finishes_tasks_completed_by_other_workers(
    harness: Harness,
) -> None:
    song_id, _, _ = create_ready_song(harness)
    response = harness.client.delete(
        f"/v1/songs/{song_id}",
        headers=harness.headers(),
    )
    assert response.status_code == 202
    deletion_id = UUID(response.json()["id"])

    completed_at = datetime.now(UTC)
    with harness.app.state.database.session() as session:
        tasks = list(
            session.scalars(
                select(DeletionTask).where(
                    DeletionTask.tenant_id == harness.primary_tenant_id,
                    DeletionTask.request_id == deletion_id,
                )
            )
        )
        assert tasks
        for task in tasks:
            if task.object_key is not None:
                harness.store.delete(task.object_key)
            task.object_key = None
            task.status = DeletionStatus.COMPLETED
            task.completed_at = completed_at
        session.commit()

    with harness.app.state.database.session() as session:
        service = ControlPlaneService(session, harness.store, harness.settings)
        assert service.process_deletions(harness.primary_tenant_id) == (0, 0)
        deletion = service.get_deletion(harness.primary_tenant_id, deletion_id)
        assert deletion.status == DeletionStatus.COMPLETED
        assert session.scalar(select(Song).where(Song.id == song_id)) is None


def test_score_and_manifest_history_reject_mutation_outside_privacy_purge(
    harness: Harness,
) -> None:
    song_id, _, manifest_id = create_ready_song(harness)
    create_phrase_and_score(harness, song_id, manifest_id)
    with harness.app.state.database.session() as session:
        score = session.scalar(select(ScoreRecord).where(ScoreRecord.song_id == song_id))
        assert score is not None
        score.payload = {"tampered": True}
        with pytest.raises(ImmutableScoreError):
            session.commit()
        session.rollback()

        manifest = session.scalar(
            select(SongManifestRecord).where(SongManifestRecord.song_id == song_id)
        )
        assert manifest is not None
        manifest.model_release = "tampered"
        with pytest.raises(ImmutableManifestError):
            session.commit()


def test_missing_scope_returns_forbidden(harness: Harness) -> None:
    limited_token = "limited-token-0123456789abcdefghijkl"
    with harness.app.state.database.session() as session:
        ensure_bootstrap_credential(
            session,
            tenant_slug="limited",
            tenant_name="Limited Tenant",
            token=limited_token,
            pepper=PEPPER,
            scopes=frozenset(),
        )
    response = harness.client.post(
        "/v1/songs",
        headers=harness.headers(limited_token),
        json={
            "display_name": "Denied",
            "rights_basis": "Synthetic fixture",
            "source_sha256": "a" * 64,
            "source_byte_length": 1,
            "source_media_type": "audio/wav",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"

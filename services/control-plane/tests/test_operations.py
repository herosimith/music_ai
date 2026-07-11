from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from control_plane_factories import create_phrase_and_score, create_ready_song
from control_plane_testkit import PEPPER, Harness
from music_ai_control_plane.database import Database
from music_ai_control_plane.maintenance import run_maintenance_once
from music_ai_control_plane.models import ApiCredential, PhraseArtifact, Tenant
from music_ai_control_plane.provision import provision_tenant
from music_ai_control_plane.security import authenticate
from sqlalchemy import select


def test_provision_tenant_stores_only_a_peppered_credential(harness: Harness) -> None:
    token = "production-operator-token-0123456789abcdef"
    tenant_id = provision_tenant(
        harness.settings,
        tenant_slug="provisioned",
        tenant_name="Provisioned Tenant",
        credential_name="initial operator",
        token=token,
    )

    database = Database(harness.settings.database_url)
    try:
        with database.session() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id))
            credential = session.scalar(
                select(ApiCredential).where(ApiCredential.tenant_id == tenant_id)
            )
            actor = authenticate(session, token=token, pepper=PEPPER)
            assert tenant is not None
            assert credential is not None
            assert credential.name == "initial operator"
            assert credential.token_digest != token
            assert token not in repr(credential.__dict__)
            assert actor.tenant_id == tenant_id
    finally:
        database.dispose()


def test_provision_tenant_rejects_invalid_operator_metadata(harness: Harness) -> None:
    with pytest.raises(ValueError, match="tenant slug"):
        provision_tenant(
            harness.settings,
            tenant_slug="INVALID TENANT",
            tenant_name="Invalid",
            credential_name="operator",
            token="production-operator-token-0123456789abcdef",
        )
    with pytest.raises(ValueError, match="credential name"):
        provision_tenant(
            harness.settings,
            tenant_slug="valid-tenant",
            tenant_name="Valid Tenant",
            credential_name="",
            token="production-operator-token-0123456789abcdef",
        )


def test_global_maintenance_expires_audio_for_every_tenant(harness: Harness) -> None:
    primary_song, _, primary_manifest = create_ready_song(harness)
    _, primary_phrase, _, _ = create_phrase_and_score(
        harness,
        primary_song,
        primary_manifest,
        write_score=False,
    )
    secondary_song, _, secondary_manifest = create_ready_song(
        harness,
        token=harness.secondary_token,
        tenant_id=harness.secondary_tenant_id,
        source_payload=b"secondary-synthetic-song-source",
    )
    _, secondary_phrase, _, _ = create_phrase_and_score(
        harness,
        secondary_song,
        secondary_manifest,
        token=harness.secondary_token,
        tenant_id=harness.secondary_tenant_id,
        write_score=False,
    )
    database = harness.app.state.database
    with database.session() as session:
        phrases = list(
            session.scalars(
                select(PhraseArtifact).where(
                    PhraseArtifact.id.in_([primary_phrase, secondary_phrase])
                )
            )
        )
        for phrase in phrases:
            phrase.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    summary = run_maintenance_once(harness.settings, harness.store)

    assert summary.tenants == 2
    assert summary.expired_audio == 2
    assert summary.completed_tasks == 2
    assert summary.failed_tasks == 0

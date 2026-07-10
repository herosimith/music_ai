from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from music_ai_control_plane.database import Base, UTCDateTime, utc_now


class SongState(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    ACCEPTED = "accepted"
    PRACTICE_ONLY = "practice_only"
    REJECTED = "rejected"
    DELETED = "deleted"


class AudioState(StrEnum):
    PENDING = "pending"
    STORED = "stored"
    DELETED = "deleted"


class DeletionStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class DeletionResource(StrEnum):
    SONG = "song"
    PHRASE_AUDIO = "phrase_audio"


def enum_column(enum_type: type[StrEnum]) -> Enum:
    return Enum(
        enum_type,
        values_callable=lambda values: [item.value for item in values],
        create_constraint=True,
        native_enum=False,
        validate_strings=True,
    )


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ApiCredential(Base):
    __tablename__ = "api_credentials"
    __table_args__ = (Index("ix_api_credentials_tenant", "tenant_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Song(Base):
    __tablename__ = "songs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_sha256", name="uq_song_tenant_source"),
        UniqueConstraint("tenant_id", "id", name="uq_song_tenant_identity"),
        Index("ix_songs_tenant_state", "tenant_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    rights_basis: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_byte_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_media_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_object_key: Mapped[str | None] = mapped_column(String(600), nullable=True)
    source_uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    state: Mapped[SongState] = mapped_column(
        enum_column(SongState), default=SongState.PENDING_UPLOAD, nullable=False
    )
    manifest_payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "song_id",
            "id",
            name="uq_session_tenant_song_identity",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "song_id"],
            ["songs.tenant_id", "songs.id"],
            name="fk_session_tenant_song",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "song_id", "manifest_record_id"],
            [
                "song_manifest_records.tenant_id",
                "song_manifest_records.song_id",
                "song_manifest_records.id",
            ],
            name="fk_session_tenant_song_manifest",
        ),
        Index("ix_sessions_tenant_song", "tenant_id", "song_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    song_id: Mapped[UUID] = mapped_column(nullable=False)
    manifest_record_id: Mapped[UUID] = mapped_column(nullable=False)
    calibration_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class PhraseArtifact(Base):
    __tablename__ = "phrase_artifacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_phrase_tenant_idempotency"),
        UniqueConstraint("tenant_id", "session_id", "sequence", name="uq_phrase_sequence"),
        UniqueConstraint(
            "tenant_id",
            "session_id",
            "id",
            name="uq_phrase_tenant_session_identity",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "song_id", "session_id"],
            [
                "practice_sessions.tenant_id",
                "practice_sessions.song_id",
                "practice_sessions.id",
            ],
            name="fk_phrase_tenant_song_session",
        ),
        Index("ix_phrases_tenant_session", "tenant_id", "session_id"),
        Index("ix_phrases_expiry", "audio_state", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(nullable=False)
    song_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_start: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_end: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    codec: Mapped[str] = mapped_column(String(20), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    calibration_version: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    audio_state: Mapped[AudioState] = mapped_column(
        enum_column(AudioState), default=AudioState.PENDING, nullable=False
    )
    object_key: Mapped[str | None] = mapped_column(String(600), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    audio_deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class SongManifestRecord(Base):
    __tablename__ = "song_manifest_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "song_id", "payload_sha256", name="uq_manifest_payload"),
        UniqueConstraint(
            "tenant_id",
            "song_id",
            "id",
            name="uq_manifest_tenant_song_identity",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "song_id"],
            ["songs.tenant_id", "songs.id"],
            name="fk_manifest_tenant_song",
        ),
        Index("ix_manifests_tenant_song", "tenant_id", "song_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    song_id: Mapped[UUID] = mapped_column(nullable=False)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    model_release: Mapped[str] = mapped_column(String(128), nullable=False)
    score_version: Mapped[str] = mapped_column(String(128), nullable=False)
    calibration_version: Mapped[str] = mapped_column(String(128), nullable=False)
    produced_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ScoreRecord(Base):
    __tablename__ = "score_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_score_tenant_idempotency"),
        ForeignKeyConstraint(
            ["tenant_id", "song_id", "manifest_record_id"],
            [
                "song_manifest_records.tenant_id",
                "song_manifest_records.song_id",
                "song_manifest_records.id",
            ],
            name="fk_score_tenant_song_manifest",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "song_id", "session_id"],
            [
                "practice_sessions.tenant_id",
                "practice_sessions.song_id",
                "practice_sessions.id",
            ],
            name="fk_score_tenant_song_session",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "session_id", "phrase_id"],
            [
                "phrase_artifacts.tenant_id",
                "phrase_artifacts.session_id",
                "phrase_artifacts.id",
            ],
            name="fk_score_tenant_session_phrase",
        ),
        Index("ix_scores_tenant_session", "tenant_id", "session_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    song_id: Mapped[UUID] = mapped_column(nullable=False)
    manifest_record_id: Mapped[UUID] = mapped_column(nullable=False)
    session_id: Mapped[UUID] = mapped_column(nullable=False)
    phrase_id: Mapped[UUID] = mapped_column(nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    score_version: Mapped[str] = mapped_column(String(128), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    model_release: Mapped[str] = mapped_column(String(128), nullable=False)
    calibration_version: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    produced_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class StoredAsset(Base):
    __tablename__ = "stored_assets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "object_key", name="uq_asset_tenant_key"),
        ForeignKeyConstraint(
            ["tenant_id", "song_id"],
            ["songs.tenant_id", "songs.id"],
            name="fk_asset_tenant_song",
        ),
        Index("ix_assets_tenant_song", "tenant_id", "song_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    song_id: Mapped[UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(600), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[AudioState] = mapped_column(
        enum_column(AudioState), default=AudioState.PENDING, nullable=False
    )
    model_release: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            name="uq_deletion_resource",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_deletion_tenant_identity"),
        Index("ix_deletions_tenant", "tenant_id", "requested_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    resource_type: Mapped[DeletionResource] = mapped_column(
        enum_column(DeletionResource), nullable=False
    )
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[DeletionStatus] = mapped_column(
        enum_column(DeletionStatus), default=DeletionStatus.PENDING, nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class DeletionTask(Base):
    __tablename__ = "deletion_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["deletion_requests.tenant_id", "deletion_requests.id"],
            name="fk_deletion_task_tenant_request",
            ondelete="CASCADE",
        ),
        Index("ix_deletion_tasks_status", "status", "next_attempt_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    object_key: Mapped[str | None] = mapped_column(String(600), nullable=True)
    status: Mapped[DeletionStatus] = mapped_column(
        enum_column(DeletionStatus), default=DeletionStatus.PENDING, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ImmutableScoreError(RuntimeError):
    pass


class ImmutableManifestError(RuntimeError):
    pass


def _changed_fields(target) -> set[str]:
    return {attribute.key for attribute in inspect(target).attrs if attribute.history.has_changes()}


@event.listens_for(ScoreRecord, "before_update")
def prevent_score_mutation(mapper: Mapper, connection, target: ScoreRecord) -> None:
    changed = _changed_fields(target)
    purge_fields = {"payload", "payload_sha256", "idempotency_key", "deleted_at"}
    is_privacy_purge = (
        changed <= purge_fields
        and target.deleted_at is not None
        and target.payload is None
        and target.payload_sha256 is None
        and target.idempotency_key is None
    )
    if changed and not is_privacy_purge:
        raise ImmutableScoreError(f"score records are immutable: {sorted(changed)}")


@event.listens_for(SongManifestRecord, "before_update")
def prevent_manifest_mutation(
    mapper: Mapper,
    connection,
    target: SongManifestRecord,
) -> None:
    changed = _changed_fields(target)
    purge_fields = {"payload", "payload_sha256", "deleted_at"}
    is_privacy_purge = (
        changed <= purge_fields
        and target.deleted_at is not None
        and target.payload is None
        and target.payload_sha256 is None
    )
    if changed and not is_privacy_purge:
        raise ImmutableManifestError(f"manifest records are immutable: {sorted(changed)}")

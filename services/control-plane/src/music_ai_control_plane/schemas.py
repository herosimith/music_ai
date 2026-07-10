from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from music_ai_contracts.models import ScoreV1, SongManifestV1
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from music_ai_control_plane.models import (
    AudioState,
    DeletionResource,
    DeletionStatus,
    SongState,
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SongCreate(ApiModel):
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    rights_basis: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    source_sha256: Sha256
    source_byte_length: int = Field(gt=0, le=100_000_000)
    source_media_type: Literal["audio/flac", "audio/mpeg", "audio/wav"]


class SongView(ApiModel):
    id: UUID
    display_name: str
    state: SongState
    created_at: AwareDatetime
    updated_at: AwareDatetime
    upload_path: str | None = None


class SessionCreate(ApiModel):
    song_id: UUID
    manifest_record_id: UUID
    calibration_version: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class SessionView(ApiModel):
    id: UUID
    song_id: UUID
    manifest_record_id: UUID
    calibration_version: str
    created_at: AwareDatetime
    ended_at: AwareDatetime | None


class PhraseView(ApiModel):
    id: UUID
    session_id: UUID
    sequence: int
    audio_state: AudioState
    expires_at: AwareDatetime
    upload_path: str | None


class ScoreRecordView(ApiModel):
    id: UUID
    session_id: UUID
    phrase_id: UUID
    song_id: UUID
    manifest_record_id: UUID
    payload_sha256: Sha256
    score: ScoreV1
    created_at: AwareDatetime


class ManifestRecordView(ApiModel):
    id: UUID
    song_id: UUID
    payload_sha256: Sha256
    manifest: SongManifestV1
    created_at: AwareDatetime


class AssetCreate(ApiModel):
    kind: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.-]+$", max_length=80)]
    sha256: Sha256
    byte_length: int = Field(gt=0, le=100_000_000)
    media_type: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    model_release: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None


class AssetView(ApiModel):
    id: UUID
    song_id: UUID
    kind: str
    state: AudioState
    upload_path: str | None


class DeletionView(ApiModel):
    id: UUID
    resource_type: DeletionResource
    resource_id: UUID
    reason: str
    status: DeletionStatus
    requested_at: AwareDatetime
    completed_at: AwareDatetime | None
    last_error: str | None


class MaintenanceResult(ApiModel):
    expired_audio: int = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    failed_tasks: int = Field(ge=0)


class HealthView(ApiModel):
    status: str


class ErrorView(ApiModel):
    code: str
    message: str

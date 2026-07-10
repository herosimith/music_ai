from __future__ import annotations

import hashlib
from itertools import pairwise
from typing import Annotated, Literal
from uuid import UUID

from music_ai_contracts.models import (
    ArtifactPointer,
    GateStatus,
    QualityIssue,
    ReferenceF0Frame,
    ReferenceRegionCandidate,
    ScorableRegion,
    SongManifestV1,
)
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class InternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class IngestJob(InternalModel):
    tenant_id: UUID
    song_id: UUID
    rights_basis: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    source_sha256: Sha256
    source_media_type: Literal["audio/flac", "audio/mpeg", "audio/wav"]
    source_payload: bytes = Field(min_length=1, max_length=100_000_000, repr=False)
    sample_rate: int = Field(ge=8_000, le=192_000)
    duration_samples: int = Field(gt=0)
    calibration_version: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    produced_at: AwareDatetime

    @model_validator(mode="after")
    def validate_source_digest(self) -> IngestJob:
        actual = hashlib.sha256(self.source_payload).hexdigest()
        if actual != self.source_sha256:
            raise ValueError("source payload SHA-256 does not match the ingest job")
        return self


class StemResult(InternalModel):
    vocal_wav: bytes = Field(min_length=1, max_length=100_000_000, repr=False)
    accompaniment_wav: bytes = Field(min_length=1, max_length=100_000_000, repr=False)
    sample_rate: int = Field(ge=8_000, le=192_000)
    duration_samples: int = Field(gt=0)
    vocal_presence_coverage: UnitInterval
    separation_confidence: UnitInterval
    accompaniment_leakage: UnitInterval


class ReferenceAnalysis(InternalModel):
    sample_rate: int = Field(ge=8_000, le=192_000)
    duration_samples: int = Field(gt=0)
    hop_samples: int = Field(gt=0, le=16_384)
    frames: list[ReferenceF0Frame] = Field(default_factory=list, max_length=1_000_000)
    candidates: list[ReferenceRegionCandidate] = Field(default_factory=list, max_length=100_000)

    @model_validator(mode="after")
    def validate_timeline(self) -> ReferenceAnalysis:
        indices = [frame.sample_index for frame in self.frames]
        if indices != sorted(set(indices)):
            raise ValueError("reference frame sample indices must be strictly increasing")
        if any(current - previous != self.hop_samples for previous, current in pairwise(indices)):
            raise ValueError("reference frame sample indices must be contiguous by hop_samples")
        if indices and indices[-1] >= self.duration_samples:
            raise ValueError("reference frames must stay within the analysis duration")

        starts = [candidate.start_sample for candidate in self.candidates]
        if starts != sorted(starts):
            raise ValueError("reference candidates must be sorted by start_sample")
        for previous, current in pairwise(self.candidates):
            if current.start_sample < previous.end_sample:
                raise ValueError("reference candidates must not overlap")
        if any(candidate.end_sample > self.duration_samples for candidate in self.candidates):
            raise ValueError("reference candidates must stay within the analysis duration")
        return self


RegionCandidate = ReferenceRegionCandidate


class ArtifactBlob(InternalModel):
    kind: Literal["vocal", "accompaniment", "f0"]
    media_type: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    payload: bytes = Field(min_length=1, max_length=100_000_000, repr=False)
    model_release: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    sha256: Sha256

    @model_validator(mode="after")
    def validate_digest(self) -> ArtifactBlob:
        if hashlib.sha256(self.payload).hexdigest() != self.sha256:
            raise ValueError("artifact payload SHA-256 does not match its descriptor")
        return self


class PublishedArtifact(InternalModel):
    artifact_id: UUID
    kind: Literal["vocal", "accompaniment", "f0"]
    sha256: Sha256
    model_release: Annotated[str, StringConstraints(min_length=1, max_length=128)]

    def pointer(self) -> ArtifactPointer:
        return ArtifactPointer(
            artifact_id=str(self.artifact_id),
            kind=self.kind,
            sha256=self.sha256,
            model_release=self.model_release,
        )


class GateOutcome(InternalModel):
    status: GateStatus
    coverage: UnitInterval
    issues: list[QualityIssue] = Field(default_factory=list, max_length=100)
    regions: list[ScorableRegion] = Field(default_factory=list, max_length=100_000)


class IngestResult(InternalModel):
    manifest_record_id: UUID
    manifest: SongManifestV1
    artifacts: list[PublishedArtifact]

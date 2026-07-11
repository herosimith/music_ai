from __future__ import annotations

import hashlib
from dataclasses import dataclass
from itertools import pairwise
from typing import Annotated, Literal
from uuid import UUID

from music_ai_contracts.models import (
    GateStatus,
    PhraseAudioV1,
    ScoreV1,
    SongManifestV1,
    TransportEvidenceV1,
    UserFeaturesV1,
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
PositiveHertz = Annotated[float, Field(gt=0.0, le=20_000.0, allow_inf_nan=False)]


class InternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ScoringJob(InternalModel):
    phrase: PhraseAudioV1
    audio_payload: bytes = Field(min_length=1, max_length=100_000_000, repr=False)
    transport: TransportEvidenceV1
    manifest: SongManifestV1
    manifest_record_id: UUID
    region_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=128)]] | None
    produced_at: AwareDatetime

    @model_validator(mode="after")
    def validate_identities(self) -> ScoringJob:
        if (
            self.phrase.tenant_id != self.manifest.tenant_id
            or self.transport.tenant_id != self.phrase.tenant_id
            or self.transport.session_id != self.phrase.session_id
            or self.transport.phrase_id != self.phrase.phrase_id
        ):
            raise ValueError("scoring job resources do not share one identity")
        if (
            self.phrase.calibration_version != self.manifest.versions.calibration_version
            or self.transport.calibration_version != self.phrase.calibration_version
        ):
            raise ValueError("scoring job calibration versions do not match")
        if self.phrase.sample_rate != self.manifest.sample_rate:
            raise ValueError("phrase and manifest sample rates do not match")
        if (
            self.produced_at < self.phrase.captured_at
            or self.produced_at < self.transport.produced_at
        ):
            raise ValueError("scoring job cannot predate its captured evidence")
        if self.manifest.gate_status == GateStatus.ACCEPTED:
            if not self.region_ids:
                raise ValueError("accepted references require exact phrase region_ids")
            if len(self.region_ids) != len(set(self.region_ids)):
                raise ValueError("phrase region_ids must be unique")
            known = {region.region_id for region in self.manifest.scorable_regions}
            if not set(self.region_ids) <= known:
                raise ValueError("phrase region_ids contain an unknown manifest region")
        elif self.region_ids is not None:
            raise ValueError("non-scoring references cannot select region_ids")
        return self


@dataclass(frozen=True, slots=True)
class DecodedPhrase:
    samples: tuple[int, ...]
    sample_rate: int
    source_sha256: str

    @property
    def frame_count(self) -> int:
        return len(self.samples)


class PitchFrame(InternalModel):
    offset_samples: int = Field(ge=0)
    voiced: bool
    f0_hz: PositiveHertz | None = None
    f0_confidence: UnitInterval

    @model_validator(mode="after")
    def validate_voicing(self) -> PitchFrame:
        if self.voiced and self.f0_hz is None:
            raise ValueError("voiced pitch frames require f0_hz")
        if not self.voiced and self.f0_hz is not None:
            raise ValueError("unvoiced pitch frames cannot contain f0_hz")
        return self


class PitchAnalysis(InternalModel):
    hop_samples: int = Field(gt=0, le=16_384)
    frames: list[PitchFrame] = Field(min_length=1, max_length=1_000_000)

    @model_validator(mode="after")
    def validate_offsets(self) -> PitchAnalysis:
        offsets = [frame.offset_samples for frame in self.frames]
        if offsets[0] != 0:
            raise ValueError("pitch frames must start at offset zero")
        if offsets != sorted(set(offsets)) or any(
            current - previous != self.hop_samples for previous, current in pairwise(offsets)
        ):
            raise ValueError("pitch frame offsets must be contiguous by hop_samples")
        return self


class LeakageFrame(InternalModel):
    offset_samples: int = Field(ge=0)
    leakage_confidence: UnitInterval


class LeakageAnalysis(InternalModel):
    hop_samples: int = Field(gt=0, le=16_384)
    frames: list[LeakageFrame] = Field(min_length=1, max_length=1_000_000)

    @model_validator(mode="after")
    def validate_offsets(self) -> LeakageAnalysis:
        offsets = [frame.offset_samples for frame in self.frames]
        if offsets[0] != 0:
            raise ValueError("leakage frames must start at offset zero")
        if offsets != sorted(set(offsets)) or any(
            current - previous != self.hop_samples for previous, current in pairwise(offsets)
        ):
            raise ValueError("leakage frame offsets must be contiguous by hop_samples")
        return self


class EvidenceBlob(InternalModel):
    kind: Literal["transport", "user_features"]
    payload: bytes = Field(min_length=1, max_length=100_000_000, repr=False)
    sha256: Sha256
    model_release: Annotated[str, StringConstraints(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def validate_digest(self) -> EvidenceBlob:
        if hashlib.sha256(self.payload).hexdigest() != self.sha256:
            raise ValueError("evidence payload SHA-256 does not match its descriptor")
        return self


class ArchivedEvidence(InternalModel):
    artifact_id: UUID
    kind: Literal["transport", "user_features"]
    sha256: Sha256


class ScoringComputation(InternalModel):
    features: UserFeaturesV1
    score: ScoreV1
    evidence: list[EvidenceBlob] = Field(min_length=2, max_length=2)
    idempotency_key: Sha256

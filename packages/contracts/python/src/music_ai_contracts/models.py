from __future__ import annotations

from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    model_validator,
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
VersionName = Annotated[str, StringConstraints(min_length=1, max_length=128)]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
PositiveHertz = Annotated[float, Field(gt=0.0, le=20_000.0, allow_inf_nan=False)]
MetricName = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{1,63}$"),
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ReferenceSource(StrEnum):
    CANONICAL_NOTES = "canonical_notes"
    INDEPENDENT_STEMS = "independent_stems"
    EXTRACTED_RECORDING = "extracted_recording"


class GateStatus(StrEnum):
    ACCEPTED = "accepted"
    PRACTICE_ONLY = "practice_only"
    REJECTED = "rejected"


class CorrectionType(StrEnum):
    SHARP = "sharp"
    FLAT = "flat"
    OCTAVE_ERROR = "octave_error"
    EARLY = "early"
    LATE = "late"
    SHORT = "short"
    LONG = "long"
    MISSED = "missed"
    UNSTABLE = "unstable"


class VersionStamp(ContractModel):
    pipeline_version: VersionName
    model_release: VersionName
    score_version: VersionName
    calibration_version: VersionName


class EvidencePointer(ContractModel):
    artifact_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    start_sample: Annotated[int, Field(ge=0)]
    end_sample: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def validate_range(self) -> EvidencePointer:
        if self.end_sample <= self.start_sample:
            raise ValueError("end_sample must be greater than start_sample")
        return self


class TransportSyncV1(ContractModel):
    schema_version: Literal["transport.v1"]
    tenant_id: UUID
    session_id: UUID
    seq: Annotated[int, Field(ge=0)]
    revision: Annotated[int, Field(ge=0)]
    captured_at: AwareDatetime
    playhead_samples: Annotated[int, Field(ge=0)]
    microphone_sample_index: Annotated[int, Field(ge=0)]
    sample_rate: Annotated[int, Field(ge=8_000, le=192_000)]
    drift_ppm: Annotated[float, Field(ge=-2_000, le=2_000, allow_inf_nan=False)]


class PhraseAudioV1(ContractModel):
    schema_version: Literal["phrase-audio.v1"]
    tenant_id: UUID
    session_id: UUID
    phrase_id: UUID
    sequence: Annotated[int, Field(ge=0)]
    sample_start: Annotated[int, Field(ge=0)]
    sample_end: Annotated[int, Field(gt=0)]
    sample_rate: Annotated[int, Field(ge=8_000, le=192_000)]
    channels: Literal[1] = 1
    codec: Literal["pcm_s16le", "wav_pcm_s16le"]
    sha256: Sha256
    byte_length: Annotated[int, Field(gt=0, le=100_000_000)]
    calibration_version: VersionName
    captured_at: AwareDatetime
    idempotency_key: Annotated[str, StringConstraints(min_length=16, max_length=128)]

    @model_validator(mode="after")
    def validate_audio_shape(self) -> PhraseAudioV1:
        if self.sample_end <= self.sample_start:
            raise ValueError("sample_end must be greater than sample_start")
        payload_bytes = (self.sample_end - self.sample_start) * self.channels * 2
        if self.codec == "pcm_s16le" and self.byte_length != payload_bytes:
            raise ValueError("raw PCM byte_length must match the declared sample range")
        if self.codec == "wav_pcm_s16le" and not (
            payload_bytes + 44 <= self.byte_length <= payload_bytes + 4_096
        ):
            raise ValueError("WAV byte_length must contain PCM payload and a bounded header")
        return self


class QualityIssue(ContractModel):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.-]+$", max_length=80)]
    severity: Literal["info", "warning", "blocking"]
    message_key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.-]+$", max_length=120)]
    evidence: list[EvidencePointer] = Field(default_factory=list, max_length=20)


class ArtifactPointer(ContractModel):
    artifact_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    kind: Literal["source", "vocal", "accompaniment", "f0", "alignment", "notes"]
    sha256: Sha256
    model_release: VersionName | None = None


class ScorableRegion(ContractModel):
    region_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    start_sample: Annotated[int, Field(ge=0)]
    end_sample: Annotated[int, Field(gt=0)]
    target_f0_hz: PositiveHertz
    reference_confidence: UnitInterval
    monophonic_confidence: UnitInterval
    ornament: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> ScorableRegion:
        if self.end_sample <= self.start_sample:
            raise ValueError("end_sample must be greater than start_sample")
        return self


class SongManifestV1(ContractModel):
    schema_version: Literal["song-manifest.v1"]
    tenant_id: UUID
    song_id: UUID
    reference_source: ReferenceSource
    rights_basis: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    source_sha256: Sha256
    sample_rate: Annotated[int, Field(ge=8_000, le=192_000)]
    duration_samples: Annotated[int, Field(gt=0)]
    gate_status: GateStatus
    scorable_vocal_coverage: UnitInterval
    quality_issues: list[QualityIssue] = Field(default_factory=list, max_length=100)
    artifacts: list[ArtifactPointer] = Field(min_length=1, max_length=30)
    scorable_regions: list[ScorableRegion] = Field(default_factory=list, max_length=100_000)
    versions: VersionStamp
    produced_at: AwareDatetime

    @model_validator(mode="after")
    def validate_gate_semantics(self) -> SongManifestV1:
        if self.gate_status in {GateStatus.REJECTED, GateStatus.PRACTICE_ONLY} and (
            self.scorable_regions or self.scorable_vocal_coverage != 0
        ):
            raise ValueError("non-scoring songs cannot contain scorable regions")
        if self.gate_status == GateStatus.ACCEPTED and (
            not self.scorable_regions or self.scorable_vocal_coverage <= 0
        ):
            raise ValueError("accepted songs require scorable regions and positive coverage")
        if self.gate_status == GateStatus.ACCEPTED and any(
            issue.severity == "blocking" for issue in self.quality_issues
        ):
            raise ValueError("accepted songs cannot contain blocking quality issues")
        if any(region.end_sample > self.duration_samples for region in self.scorable_regions):
            raise ValueError("scorable regions must stay within the song duration")
        region_ids = [region.region_id for region in self.scorable_regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("scorable region IDs must be unique")

        artifact_kinds = {artifact.kind for artifact in self.artifacts}
        required_artifacts = {
            ReferenceSource.CANONICAL_NOTES: {"notes"},
            ReferenceSource.INDEPENDENT_STEMS: {"vocal", "accompaniment", "f0"},
            ReferenceSource.EXTRACTED_RECORDING: {"vocal", "f0"},
        }[self.reference_source]
        if not required_artifacts.issubset(artifact_kinds):
            raise ValueError("reference source is missing required artifacts")
        return self


class ReferenceF0Frame(ContractModel):
    sample_index: Annotated[int, Field(ge=0)]
    voiced: bool
    f0_hz: PositiveHertz | None = None
    f0_confidence: UnitInterval
    monophonic_confidence: UnitInterval

    @model_validator(mode="after")
    def validate_voicing(self) -> ReferenceF0Frame:
        if self.voiced and self.f0_hz is None:
            raise ValueError("voiced reference frames require f0_hz")
        if not self.voiced and self.f0_hz is not None:
            raise ValueError("unvoiced reference frames cannot contain f0_hz")
        return self


class ReferenceRegionCandidate(ContractModel):
    start_sample: Annotated[int, Field(ge=0)]
    end_sample: Annotated[int, Field(gt=0)]
    ornament: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> ReferenceRegionCandidate:
        if self.end_sample <= self.start_sample:
            raise ValueError("candidate end_sample must be greater than start_sample")
        return self


class ReferenceF0V1(ContractModel):
    schema_version: Literal["reference-f0.v1"]
    tenant_id: UUID
    song_id: UUID
    sample_rate: Annotated[int, Field(ge=8_000, le=192_000)]
    duration_samples: Annotated[int, Field(gt=0)]
    hop_samples: Annotated[int, Field(gt=0, le=16_384)]
    source_vocal_sha256: Sha256
    pipeline_version: VersionName
    model_release: VersionName
    vocal_presence_coverage: UnitInterval
    separation_confidence: UnitInterval
    accompaniment_leakage: UnitInterval
    frames: list[ReferenceF0Frame] = Field(default_factory=list, max_length=1_000_000)
    candidates: list[ReferenceRegionCandidate] = Field(default_factory=list, max_length=100_000)
    produced_at: AwareDatetime

    @model_validator(mode="after")
    def validate_frame_timeline(self) -> ReferenceF0V1:
        indices = [frame.sample_index for frame in self.frames]
        if indices != sorted(set(indices)):
            raise ValueError("reference frame sample_index values must be strictly increasing")
        if any(current - previous != self.hop_samples for previous, current in pairwise(indices)):
            raise ValueError(
                "reference frame sample_index values must be contiguous by hop_samples"
            )
        if indices and indices[-1] >= self.duration_samples:
            raise ValueError("reference frames must stay within the song duration")
        starts = [candidate.start_sample for candidate in self.candidates]
        if starts != sorted(starts):
            raise ValueError("reference candidates must be sorted by start_sample")
        for previous, current in pairwise(self.candidates):
            if current.start_sample < previous.end_sample:
                raise ValueError("reference candidates must not overlap")
        if any(candidate.end_sample > self.duration_samples for candidate in self.candidates):
            raise ValueError("reference candidates must stay within the song duration")
        return self


class UserFeatureFrame(ContractModel):
    sample_index: Annotated[
        int,
        Field(
            ge=0,
            description=(
                "Sample position on the calibrated reference timeline. The audio-to-features "
                "stage derives it from capture samples and transport sync evidence."
            ),
        ),
    ]
    voiced: bool
    f0_hz: PositiveHertz | None = None
    f0_confidence: UnitInterval
    energy_dbfs: Annotated[float, Field(ge=-160.0, le=12.0, allow_inf_nan=False)]
    leakage_confidence: UnitInterval

    @model_validator(mode="after")
    def validate_voicing(self) -> UserFeatureFrame:
        if self.voiced and self.f0_hz is None:
            raise ValueError("voiced frames require f0_hz")
        if not self.voiced and self.f0_hz is not None:
            raise ValueError("unvoiced frames cannot contain f0_hz")
        return self


class UserFeaturesV1(ContractModel):
    schema_version: Literal["user-features.v1"]
    tenant_id: UUID
    session_id: UUID
    phrase_id: UUID
    sample_rate: Annotated[int, Field(ge=8_000, le=192_000)]
    hop_samples: Annotated[int, Field(gt=0, le=16_384)]
    source_audio_sha256: Sha256
    frames: list[UserFeatureFrame] = Field(min_length=1, max_length=1_000_000)
    versions: VersionStamp
    produced_at: AwareDatetime

    @model_validator(mode="after")
    def validate_frame_order(self) -> UserFeaturesV1:
        indices = [frame.sample_index for frame in self.frames]
        if indices != sorted(set(indices)):
            raise ValueError("feature frame sample_index values must be strictly increasing")
        if any(current - previous != self.hop_samples for previous, current in pairwise(indices)):
            raise ValueError("feature frame sample_index values must be contiguous by hop_samples")
        return self


class NumericMetric(ContractModel):
    value: Annotated[float, Field(allow_inf_nan=False)]
    unit: Literal["cents", "milliseconds", "ratio", "hertz", "semitones"]
    confidence: UnitInterval
    coverage: UnitInterval


class CorrectionEventV1(ContractModel):
    schema_version: Literal["correction-event.v1"]
    tenant_id: UUID
    session_id: UUID
    phrase_id: UUID
    correction_id: UUID
    correction_type: CorrectionType
    start_sample: Annotated[int, Field(ge=0)]
    end_sample: Annotated[int, Field(gt=0)]
    severity: UnitInterval
    confidence: UnitInterval
    reference_confidence: UnitInterval
    observed: NumericMetric | None = None
    reference: NumericMetric | None = None
    evidence: list[EvidencePointer] = Field(min_length=1, max_length=20)
    score_version: VersionName
    produced_at: AwareDatetime

    @model_validator(mode="after")
    def validate_range(self) -> CorrectionEventV1:
        if self.end_sample <= self.start_sample:
            raise ValueError("end_sample must be greater than start_sample")
        return self


class ScoreV1(ContractModel):
    schema_version: Literal["score.v1"]
    tenant_id: UUID
    session_id: UUID
    phrase_id: UUID
    song_id: UUID
    reference_source: ReferenceSource
    scored_coverage: UnitInterval
    metrics: dict[MetricName, NumericMetric] = Field(default_factory=dict, max_length=100)
    corrections: list[CorrectionEventV1] = Field(default_factory=list, max_length=10_000)
    abstained_reason: (
        Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.-]+$", max_length=120)] | None
    ) = None
    versions: VersionStamp
    produced_at: AwareDatetime

    @model_validator(mode="after")
    def validate_abstention(self) -> ScoreV1:
        if self.abstained_reason is not None:
            if self.scored_coverage != 0 or self.metrics or self.corrections:
                raise ValueError("abstained scores cannot contain metrics or corrections")
        elif self.scored_coverage <= 0:
            raise ValueError("non-abstained scores require positive coverage")
        for correction in self.corrections:
            if (
                correction.tenant_id != self.tenant_id
                or correction.session_id != self.session_id
                or correction.phrase_id != self.phrase_id
            ):
                raise ValueError("correction event identity must match its score")
            if correction.score_version != self.versions.score_version:
                raise ValueError("correction score_version must match its score")
        return self


class SampleRangeArguments(ContractModel):
    start_sample: Annotated[int, Field(ge=0)]
    end_sample: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def validate_range(self) -> SampleRangeArguments:
        if self.end_sample <= self.start_sample:
            raise ValueError("end_sample must be greater than start_sample")
        return self


class LoopArguments(SampleRangeArguments):
    repetitions: Annotated[int, Field(ge=1, le=8)] = 3


class SlowArguments(SampleRangeArguments):
    speed: Annotated[float, Field(ge=0.5, le=1.0, allow_inf_nan=False)]


class TransposeArguments(ContractModel):
    semitones: Annotated[int, Field(ge=-12, le=12)]


class ReferenceToneArguments(ContractModel):
    f0_hz: PositiveHertz
    duration_ms: Annotated[int, Field(ge=100, le=5_000)]


class CompareTakeArguments(ContractModel):
    take_ids: list[UUID] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_distinct_takes(self) -> CompareTakeArguments:
        if len(set(self.take_ids)) != 2:
            raise ValueError("compare_take requires two distinct take IDs")
        return self


class TextArguments(ContractModel):
    pass


class CoachActionBase(ContractModel):
    schema_version: Literal["coach-action.v1"]
    tenant_id: UUID
    action_id: UUID
    session_id: UUID
    phrase_id: UUID
    source_correction_ids: list[UUID] = Field(default_factory=list, max_length=100)
    message: Annotated[str, StringConstraints(min_length=1, max_length=1_000)]
    provider: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    score_version: VersionName
    produced_at: AwareDatetime


class LoopCoachAction(CoachActionBase):
    action_type: Literal["loop"]
    arguments: LoopArguments


class SlowCoachAction(CoachActionBase):
    action_type: Literal["slow"]
    arguments: SlowArguments


class TransposeCoachAction(CoachActionBase):
    action_type: Literal["transpose"]
    arguments: TransposeArguments


class ReferenceToneCoachAction(CoachActionBase):
    action_type: Literal["reference_tone"]
    arguments: ReferenceToneArguments


class CompareTakeCoachAction(CoachActionBase):
    action_type: Literal["compare_take"]
    arguments: CompareTakeArguments


class TextCoachAction(CoachActionBase):
    action_type: Literal["text"]
    arguments: TextArguments


CoachAction = Annotated[
    LoopCoachAction
    | SlowCoachAction
    | TransposeCoachAction
    | ReferenceToneCoachAction
    | CompareTakeCoachAction
    | TextCoachAction,
    Field(discriminator="action_type"),
]


class CoachActionV1(RootModel[CoachAction]):
    root: CoachAction


CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "transport.v1": TransportSyncV1,
    "phrase-audio.v1": PhraseAudioV1,
    "song-manifest.v1": SongManifestV1,
    "reference-f0.v1": ReferenceF0V1,
    "user-features.v1": UserFeaturesV1,
    "correction-event.v1": CorrectionEventV1,
    "score.v1": ScoreV1,
    "coach-action.v1": CoachActionV1,
}

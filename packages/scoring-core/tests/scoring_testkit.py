from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from music_ai_contracts.models import (
    ArtifactPointer,
    GateStatus,
    ReferenceSource,
    ScorableRegion,
    SongManifestV1,
    UserFeatureFrame,
    UserFeaturesV1,
    VersionStamp,
)

SAMPLE_RATE = 48_000
HOP_SAMPLES = 480
REGION_START = 48_000
REGION_END = 96_000
TARGET_F0_HZ = 440.0
PRODUCED_AT = datetime(2026, 7, 11, 5, 0, tzinfo=UTC)
TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
SESSION_ID = UUID("22222222-2222-4222-8222-222222222222")
PHRASE_ID = UUID("33333333-3333-4333-8333-333333333333")
SONG_ID = UUID("44444444-4444-4444-8444-444444444444")

PitchPattern = float | Callable[[int], float]


def make_region(
    *,
    region_id: str = "note-01",
    start_sample: int = REGION_START,
    end_sample: int = REGION_END,
    target_f0_hz: float = TARGET_F0_HZ,
    reference_confidence: float = 0.98,
    monophonic_confidence: float = 0.97,
    ornament: bool = False,
) -> ScorableRegion:
    return ScorableRegion(
        region_id=region_id,
        start_sample=start_sample,
        end_sample=end_sample,
        target_f0_hz=target_f0_hz,
        reference_confidence=reference_confidence,
        monophonic_confidence=monophonic_confidence,
        ornament=ornament,
    )


def make_manifest(
    *,
    regions: Sequence[ScorableRegion] | None = None,
    gate_status: GateStatus = GateStatus.ACCEPTED,
    tenant_id: UUID = TENANT_ID,
    score_version: str = "score.v1",
    calibration_version: str = "calibration.test.v1",
    reference_source: ReferenceSource = ReferenceSource.INDEPENDENT_STEMS,
    extra_artifacts: Sequence[ArtifactPointer] = (),
) -> SongManifestV1:
    selected_regions = list(regions) if regions is not None else [make_region()]
    if gate_status != GateStatus.ACCEPTED:
        selected_regions = []
    duration_samples = (
        max(
            (region.end_sample for region in selected_regions),
            default=REGION_END,
        )
        + SAMPLE_RATE
    )
    artifacts = [
        ArtifactPointer(
            artifact_id="songs/test/source.wav",
            kind="source",
            sha256="b" * 64,
        )
    ]
    if reference_source == ReferenceSource.CANONICAL_NOTES:
        artifacts.append(
            ArtifactPointer(
                artifact_id="songs/test/notes.json",
                kind="notes",
                sha256="6" * 64,
                model_release="notes.test.v1",
            )
        )
    else:
        artifacts.extend(
            [
                ArtifactPointer(
                    artifact_id="songs/test/vocal.wav",
                    kind="vocal",
                    sha256="c" * 64,
                    model_release="separator.test.v1",
                ),
                ArtifactPointer(
                    artifact_id="songs/test/f0.json",
                    kind="f0",
                    sha256="e" * 64,
                    model_release="reference-f0.test.v1",
                ),
            ]
        )
        if reference_source == ReferenceSource.INDEPENDENT_STEMS:
            artifacts.append(
                ArtifactPointer(
                    artifact_id="songs/test/accompaniment.wav",
                    kind="accompaniment",
                    sha256="d" * 64,
                    model_release="separator.test.v1",
                )
            )
    artifacts.extend(extra_artifacts)
    return SongManifestV1(
        schema_version="song-manifest.v1",
        tenant_id=tenant_id,
        song_id=SONG_ID,
        reference_source=reference_source,
        rights_basis="Synthetic test fixture",
        source_sha256="b" * 64,
        sample_rate=SAMPLE_RATE,
        duration_samples=duration_samples,
        gate_status=gate_status,
        scorable_vocal_coverage=1.0 if selected_regions else 0.0,
        quality_issues=[],
        artifacts=artifacts,
        scorable_regions=selected_regions,
        versions=VersionStamp(
            pipeline_version="reference-pipeline.test.v1",
            model_release="reference-f0.test.v1",
            score_version=score_version,
            calibration_version=calibration_version,
        ),
        produced_at=PRODUCED_AT,
    )


def make_features(
    *,
    frame_start: int = REGION_START - 12_000,
    frame_end: int = REGION_END + 12_000,
    voiced_ranges: Sequence[tuple[int, int]] | None = None,
    cents: PitchPattern = 0.0,
    target_f0_hz: float = TARGET_F0_HZ,
    f0_confidence: float = 0.99,
    leakage_confidence: float = 0.01,
    voiced_energy_dbfs: float = -18.0,
    unvoiced_energy_dbfs: float = -80.0,
    tenant_id: UUID = TENANT_ID,
    sample_rate: int = SAMPLE_RATE,
    score_version: str = "score.v1",
    calibration_version: str = "calibration.test.v1",
    source_audio_sha256: str = "a" * 64,
) -> UserFeaturesV1:
    ranges = list(voiced_ranges) if voiced_ranges is not None else [(REGION_START, REGION_END)]

    def cents_at(sample_index: int) -> float:
        return cents(sample_index) if callable(cents) else cents

    frames: list[UserFeatureFrame] = []
    for sample_index in range(frame_start, frame_end, HOP_SAMPLES):
        voiced = any(start <= sample_index < end for start, end in ranges)
        pitch_cents = cents_at(sample_index)
        frames.append(
            UserFeatureFrame(
                sample_index=sample_index,
                voiced=voiced,
                f0_hz=(target_f0_hz * 2 ** (pitch_cents / 1_200) if voiced else None),
                f0_confidence=f0_confidence if voiced else 0.0,
                energy_dbfs=voiced_energy_dbfs if voiced else unvoiced_energy_dbfs,
                leakage_confidence=leakage_confidence,
            )
        )
    return UserFeaturesV1(
        schema_version="user-features.v1",
        tenant_id=tenant_id,
        session_id=SESSION_ID,
        phrase_id=PHRASE_ID,
        sample_rate=sample_rate,
        hop_samples=HOP_SAMPLES,
        source_audio_sha256=source_audio_sha256,
        frames=frames,
        versions=VersionStamp(
            pipeline_version="features-pipeline.test.v1",
            model_release="user-f0.test.v1",
            score_version=score_version,
            calibration_version=calibration_version,
        ),
        produced_at=PRODUCED_AT,
    )

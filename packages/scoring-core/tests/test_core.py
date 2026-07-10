from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from music_ai_contracts.models import (
    ArtifactPointer,
    CorrectionType,
    GateStatus,
    ReferenceSource,
)
from music_ai_scoring import DEFAULT_POLICY, ScoringInvariantError, score_phrase

from .factories import (
    HOP_SAMPLES,
    PRODUCED_AT,
    REGION_END,
    REGION_START,
    SAMPLE_RATE,
    make_features,
    make_manifest,
    make_region,
)


def correction_types(score) -> set[CorrectionType]:
    return {correction.correction_type for correction in score.corrections}


def test_perfect_phrase_is_scored_deterministically() -> None:
    manifest = make_manifest()
    features = make_features()

    first = score_phrase(manifest, features, produced_at=PRODUCED_AT)
    second = score_phrase(manifest, features, produced_at=PRODUCED_AT)

    assert first.model_dump_json() == second.model_dump_json()
    assert first.abstained_reason is None
    assert first.scored_coverage == 1.0
    assert first.corrections == []
    assert first.metrics["pitch_center"].value == pytest.approx(0.0, abs=1e-6)
    assert first.metrics["onset_offset"].value == 0.0
    assert first.metrics["duration_delta"].value == 0.0
    assert first.versions.pipeline_version == "scoring-core.v1"


@pytest.mark.parametrize(
    ("cents", "expected_type"),
    [
        (100.0, CorrectionType.SHARP),
        (-70.0, CorrectionType.FLAT),
        (1_200.0, CorrectionType.OCTAVE_ERROR),
        (-1_200.0, CorrectionType.OCTAVE_ERROR),
        (600.0, CorrectionType.SHARP),
        (-600.0, CorrectionType.FLAT),
        (1_150.0, CorrectionType.OCTAVE_ERROR),
        (1_300.0, CorrectionType.OCTAVE_ERROR),
    ],
)
def test_pitch_corrections_preserve_signed_octave_information(
    cents: float,
    expected_type: CorrectionType,
) -> None:
    score = score_phrase(make_manifest(), make_features(cents=cents), produced_at=PRODUCED_AT)

    pitch_corrections = [
        event
        for event in score.corrections
        if event.correction_type
        in {CorrectionType.SHARP, CorrectionType.FLAT, CorrectionType.OCTAVE_ERROR}
    ]
    assert [event.correction_type for event in pitch_corrections] == [expected_type]
    assert pitch_corrections[0].observed is not None
    assert pitch_corrections[0].observed.value == pytest.approx(cents, abs=1e-6)
    assert len(pitch_corrections[0].evidence) == 2
    assert pitch_corrections[0].evidence[0].artifact_id == "songs/test/f0.json"


def test_quiet_complete_silence_is_missed_not_abstained() -> None:
    score = score_phrase(
        make_manifest(),
        make_features(voiced_ranges=[]),
        produced_at=PRODUCED_AT,
    )

    assert score.abstained_reason is None
    assert correction_types(score) == {CorrectionType.MISSED}
    assert score.scored_coverage == 1.0


def test_loud_unpitched_input_is_not_called_missed() -> None:
    score = score_phrase(
        make_manifest(),
        make_features(voiced_ranges=[], unvoiced_energy_dbfs=-12.0),
        produced_at=PRODUCED_AT,
    )

    assert score.abstained_reason == "input.insufficient_pitch_confidence"
    assert score.corrections == []


def test_contaminated_silence_abstains_instead_of_becoming_missed() -> None:
    features = make_features(voiced_ranges=[])
    region_frame_indexes = [
        index
        for index, frame in enumerate(features.frames)
        if REGION_START <= frame.sample_index < REGION_END
    ]
    changed_frames = list(features.frames)
    for index in region_frame_indexes[:49]:
        changed_frames[index] = changed_frames[index].model_copy(update={"leakage_confidence": 0.9})
    features = features.model_copy(update={"frames": changed_frames})

    score = score_phrase(make_manifest(), features, produced_at=PRODUCED_AT)

    assert score.abstained_reason == "input.accompaniment_leakage"
    assert score.corrections == []


def test_low_f0_confidence_is_not_called_missed() -> None:
    score = score_phrase(
        make_manifest(),
        make_features(f0_confidence=0.2),
        produced_at=PRODUCED_AT,
    )

    assert score.abstained_reason == "input.insufficient_pitch_confidence"
    assert score.corrections == []


def test_accompaniment_leakage_abstains() -> None:
    score = score_phrase(
        make_manifest(),
        make_features(leakage_confidence=0.9),
        produced_at=PRODUCED_AT,
    )
    assert score.abstained_reason == "input.accompaniment_leakage"


def test_incomplete_reference_timeline_abstains() -> None:
    score = score_phrase(
        make_manifest(),
        make_features(frame_start=REGION_START, frame_end=REGION_START + 24_000),
        produced_at=PRODUCED_AT,
    )
    assert score.abstained_reason == "input.incomplete_phrase"


@pytest.mark.parametrize(
    ("region", "expected_reason"),
    [
        (make_region(reference_confidence=0.5), "reference.no_high_confidence_regions"),
        (make_region(monophonic_confidence=0.5), "reference.no_high_confidence_regions"),
        (make_region(ornament=True), "reference.no_high_confidence_regions"),
    ],
)
def test_non_authoritative_reference_regions_are_excluded(region, expected_reason: str) -> None:
    score = score_phrase(
        make_manifest(regions=[region]),
        make_features(),
        produced_at=PRODUCED_AT,
    )
    assert score.abstained_reason == expected_reason


def test_practice_only_reference_abstains_before_scoring() -> None:
    score = score_phrase(
        make_manifest(gate_status=GateStatus.PRACTICE_ONLY),
        make_features(),
        produced_at=PRODUCED_AT,
    )
    assert score.abstained_reason == "reference.practice_only"


@pytest.mark.parametrize(
    ("start_offset_ms", "duration_delta_ms", "expected_type"),
    [
        (120, 0, CorrectionType.LATE),
        (-120, 0, CorrectionType.EARLY),
        (0, -150, CorrectionType.SHORT),
        (0, 150, CorrectionType.LONG),
    ],
)
def test_timing_and_duration_are_independent(
    start_offset_ms: int,
    duration_delta_ms: int,
    expected_type: CorrectionType,
) -> None:
    start = REGION_START + start_offset_ms * SAMPLE_RATE // 1_000
    duration = REGION_END - REGION_START + duration_delta_ms * SAMPLE_RATE // 1_000
    end = start + duration
    score = score_phrase(
        make_manifest(),
        make_features(voiced_ranges=[(start, end)]),
        produced_at=PRODUCED_AT,
    )

    assert correction_types(score) == {expected_type}
    assert score.metrics["onset_offset"].value == pytest.approx(start_offset_ms, abs=10)
    assert score.metrics["duration_delta"].value == pytest.approx(duration_delta_ms, abs=10)


def test_neighboring_same_pitch_region_does_not_create_false_long_note() -> None:
    first = make_region(region_id="note-01", start_sample=48_000, end_sample=72_000)
    second = make_region(region_id="note-02", start_sample=72_000, end_sample=96_000)
    score = score_phrase(
        make_manifest(regions=[first, second]),
        make_features(voiced_ranges=[(48_000, 96_000)]),
        produced_at=PRODUCED_AT,
        region_ids=["note-01"],
    )

    assert CorrectionType.LONG not in correction_types(score)
    assert score.metrics["duration_delta"].value == 0.0


def test_region_selection_is_explicit_for_phrase_scoring() -> None:
    first = make_region(region_id="note-01")
    second = make_region(region_id="note-02", start_sample=144_000, end_sample=192_000)
    manifest = make_manifest(regions=[first, second])
    features = make_features()

    whole_manifest_score = score_phrase(manifest, features, produced_at=PRODUCED_AT)
    phrase_score = score_phrase(
        manifest,
        features,
        produced_at=PRODUCED_AT,
        region_ids=["note-01"],
    )

    assert whole_manifest_score.abstained_reason == "input.incomplete_phrase"
    assert phrase_score.abstained_reason is None
    assert phrase_score.scored_coverage == 1.0


@pytest.mark.parametrize("region_ids", [[], ["missing"], ["note-01", "note-01"]])
def test_invalid_region_selection_fails_closed(region_ids: list[str]) -> None:
    with pytest.raises(ScoringInvariantError):
        score_phrase(
            make_manifest(),
            make_features(),
            produced_at=PRODUCED_AT,
            region_ids=region_ids,
        )


def test_string_is_not_accepted_as_region_id_sequence() -> None:
    with pytest.raises(ScoringInvariantError, match="sequence of region IDs"):
        score_phrase(
            make_manifest(),
            make_features(),
            produced_at=PRODUCED_AT,
            region_ids="note-01",
        )


def test_unstable_non_vibrato_pitch_is_corrected() -> None:
    def unstable(sample_index: int) -> float:
        return 60.0 if ((sample_index - REGION_START) // HOP_SAMPLES) % 4 < 2 else -60.0

    score = score_phrase(
        make_manifest(),
        make_features(cents=unstable),
        produced_at=PRODUCED_AT,
    )
    assert correction_types(score) == {CorrectionType.UNSTABLE}
    assert score.metrics["long_tone_stability"].value == pytest.approx(60.0, abs=1.0)


def test_controlled_vibrato_is_measured_not_called_unstable() -> None:
    def vibrato(sample_index: int) -> float:
        seconds = (sample_index - REGION_START) / SAMPLE_RATE
        return 40.0 * math.sin(2 * math.pi * 5.0 * seconds)

    score = score_phrase(
        make_manifest(),
        make_features(cents=vibrato),
        produced_at=PRODUCED_AT,
    )
    assert CorrectionType.UNSTABLE not in correction_types(score)
    assert score.metrics["vibrato_rate"].value == pytest.approx(5.0, abs=0.5)
    assert score.metrics["vibrato_depth"].value == pytest.approx(40.0, abs=5.0)


def test_correction_identity_is_stable_and_input_bound() -> None:
    manifest = make_manifest()
    features = make_features(cents=100.0)
    first = score_phrase(manifest, features, produced_at=PRODUCED_AT)
    repeated = score_phrase(manifest, features, produced_at=PRODUCED_AT)
    changed_input = score_phrase(
        manifest,
        make_features(cents=100.0, source_audio_sha256="f" * 64),
        produced_at=PRODUCED_AT,
    )

    assert first.corrections[0].correction_id == repeated.corrections[0].correction_id
    assert first.corrections[0].correction_id != changed_input.corrections[0].correction_id


def test_optional_alignment_artifact_does_not_break_correction_lineage() -> None:
    alignment = ArtifactPointer(
        artifact_id="songs/test/alignment.json",
        kind="alignment",
        sha256="9" * 64,
        model_release="alignment.test.v1",
    )
    score = score_phrase(
        make_manifest(extra_artifacts=[alignment]),
        make_features(cents=60.0),
        produced_at=PRODUCED_AT,
    )

    correction = next(
        event for event in score.corrections if event.correction_type == CorrectionType.SHARP
    )
    assert correction.evidence[0].artifact_id == "songs/test/f0.json"


def test_canonical_reference_uses_notes_as_authoritative_evidence() -> None:
    alignment = ArtifactPointer(
        artifact_id="songs/test/alignment.json",
        kind="alignment",
        sha256="9" * 64,
        model_release="alignment.test.v1",
    )
    score = score_phrase(
        make_manifest(
            reference_source=ReferenceSource.CANONICAL_NOTES,
            extra_artifacts=[alignment],
        ),
        make_features(cents=-60.0),
        produced_at=PRODUCED_AT,
    )

    correction = next(
        event for event in score.corrections if event.correction_type == CorrectionType.FLAT
    )
    assert correction.evidence[0].artifact_id == "songs/test/notes.json"


@pytest.mark.parametrize(
    ("manifest", "features", "produced_at", "message"),
    [
        (
            make_manifest(),
            make_features(tenant_id=UUID("77777777-7777-4777-8777-777777777777")),
            PRODUCED_AT,
            "different tenants",
        ),
        (
            make_manifest(),
            make_features(sample_rate=44_100),
            PRODUCED_AT,
            "different sample rates",
        ),
        (
            make_manifest(score_version="score.v2"),
            make_features(),
            PRODUCED_AT,
            "manifest score_version",
        ),
        (
            make_manifest(),
            make_features(score_version="score.v2"),
            PRODUCED_AT,
            "feature score_version",
        ),
        (
            make_manifest(),
            make_features(calibration_version="calibration.test.v2"),
            PRODUCED_AT,
            "calibration versions",
        ),
        (
            make_manifest(),
            make_features(),
            datetime(2026, 7, 11, 5, 0),
            "timezone",
        ),
        (
            make_manifest(),
            make_features(),
            PRODUCED_AT - timedelta(seconds=1),
            "cannot precede",
        ),
    ],
)
def test_input_invariants_fail_closed(manifest, features, produced_at, message: str) -> None:
    with pytest.raises(ScoringInvariantError, match=message):
        score_phrase(manifest, features, produced_at=produced_at)


def test_default_policy_fingerprint_is_committed() -> None:
    assert DEFAULT_POLICY.fingerprint() == (
        "bf1891a5fe6794d11a17e352fb3b3e22eea1cde04bc2483f92122871d51d0ae3"
    )


def test_mutated_policy_cannot_reuse_an_approved_score_version() -> None:
    policy = replace(DEFAULT_POLICY, pitch_tolerance_cents=30.0)
    with pytest.raises(ScoringInvariantError, match="fingerprint is not approved"):
        score_phrase(
            make_manifest(),
            make_features(),
            produced_at=PRODUCED_AT,
            policy=policy,
        )


def test_unregistered_score_version_cannot_emit_results() -> None:
    policy = replace(DEFAULT_POLICY, score_version="score.v2")
    with pytest.raises(ScoringInvariantError, match="version is not registered"):
        score_phrase(
            make_manifest(score_version="score.v2"),
            make_features(score_version="score.v2"),
            produced_at=PRODUCED_AT,
            policy=policy,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"min_pitch_coverage": float("nan")}, "confidence and coverage"),
        ({"octave_tolerance_cents": 600.0}, "half an octave"),
        ({"vibrato_min_depth_cents": 130.0}, "depth bounds"),
    ],
)
def test_invalid_policy_is_rejected(changes: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(DEFAULT_POLICY, **changes)

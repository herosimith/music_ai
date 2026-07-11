from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from typing import Literal
from uuid import UUID, uuid5

from music_ai_contracts.models import (
    ArtifactPointer,
    CorrectionEventV1,
    CorrectionType,
    EvidencePointer,
    GateStatus,
    NumericMetric,
    ReferenceSource,
    ScorableRegion,
    ScoreV1,
    SongManifestV1,
    UserFeatureFrame,
    UserFeaturesV1,
    VersionStamp,
)

from music_ai_scoring.config import (
    APPROVED_POLICY_FINGERPRINTS,
    DEFAULT_POLICY,
    ScoringPolicy,
)

CORRECTION_NAMESPACE = UUID("89d31f48-5193-4f46-a80b-8c5a86f9e096")
MetricUnit = Literal["cents", "milliseconds", "ratio", "hertz", "semitones"]


class ScoringInvariantError(ValueError):
    pass


def score_phrase(
    manifest: SongManifestV1,
    features: UserFeaturesV1,
    *,
    produced_at: datetime,
    policy: ScoringPolicy = DEFAULT_POLICY,
    region_ids: Sequence[str] | None = None,
) -> ScoreV1:
    _validate_inputs(manifest, features, produced_at, policy)
    versions = VersionStamp(
        pipeline_version=policy.pipeline_version,
        model_release=features.versions.model_release,
        score_version=policy.score_version,
        calibration_version=features.versions.calibration_version,
    )

    if manifest.gate_status != GateStatus.ACCEPTED:
        return _abstain(
            manifest,
            features,
            produced_at,
            versions,
            f"reference.{manifest.gate_status.value}",
        )

    if region_ids is not None:
        if isinstance(region_ids, (str, bytes)):
            raise ScoringInvariantError("region_ids must be a sequence of region IDs")
        if not region_ids:
            raise ScoringInvariantError("region_ids must not be empty")
        if len(region_ids) != len(set(region_ids)):
            raise ScoringInvariantError("region_ids must be unique")
        known_region_ids = {region.region_id for region in manifest.scorable_regions}
        unknown_region_ids = set(region_ids) - known_region_ids
        if unknown_region_ids:
            unknown = ", ".join(sorted(unknown_region_ids))
            raise ScoringInvariantError(f"unknown scorable region IDs: {unknown}")
        requested_region_ids = set(region_ids)
    else:
        requested_region_ids = None

    regions = [
        region
        for region in manifest.scorable_regions
        if (requested_region_ids is None or region.region_id in requested_region_ids)
        if region.reference_confidence >= policy.min_reference_confidence
        and region.monophonic_confidence >= policy.min_monophonic_confidence
        and not region.ornament
    ]
    if not regions:
        return _abstain(
            manifest,
            features,
            produced_at,
            versions,
            "reference.no_high_confidence_regions",
        )

    total_reference_samples = sum(region.end_sample - region.start_sample for region in regions)
    covered_samples = sum(_covered_samples(region, features) for region in regions)
    timeline_coverage = covered_samples / total_reference_samples
    if timeline_coverage < policy.min_timeline_coverage:
        return _abstain(
            manifest,
            features,
            produced_at,
            versions,
            "input.incomplete_phrase",
        )

    relevant_frames = _frames_for_regions(features.frames, regions)
    if (
        relevant_frames
        and statistics.median(frame.leakage_confidence for frame in relevant_frames)
        > policy.max_leakage_confidence
    ):
        return _abstain(
            manifest,
            features,
            produced_at,
            versions,
            "input.accompaniment_leakage",
        )

    corrections: list[CorrectionEventV1] = []
    all_pitch_errors: list[float] = []
    pitch_frame_count = 0
    expected_frame_count = 0
    voiced_frame_count = 0
    assessed_samples = 0
    stability_values: list[float] = []
    vibrato_rates: list[float] = []
    vibrato_depths: list[float] = []
    onset_offsets: list[float] = []
    duration_deltas: list[float] = []
    assessment_confidences: list[float] = []
    resolved_pitch_regions = 0
    long_tone_regions = 0
    leakage_blocked_regions = 0

    for region in regions:
        region_frames = [
            frame
            for frame in features.frames
            if region.start_sample <= frame.sample_index < region.end_sample
        ]
        expected = max(
            1,
            math.ceil((region.end_sample - region.start_sample) / features.hop_samples),
        )
        expected_frame_count += expected
        if len(region_frames) / expected < policy.min_timeline_coverage:
            continue

        low_leakage_frames = [
            frame
            for frame in region_frames
            if frame.leakage_confidence <= policy.max_leakage_confidence
        ]
        voiced_frames = [frame for frame in low_leakage_frames if frame.voiced]
        clean_coverage = min(len(low_leakage_frames) / expected, 1.0)
        voiced_frame_count += len(voiced_frames)
        voiced_coverage = len(voiced_frames) / expected
        timing_frames = _timing_frames(
            region,
            features,
            policy,
            manifest.scorable_regions,
        )

        if voiced_coverage <= policy.missed_voiced_coverage:
            quiet_observation = low_leakage_frames and (
                statistics.median(frame.energy_dbfs for frame in low_leakage_frames)
                <= policy.missed_max_energy_dbfs
            )
            timing_coverage = min(len(timing_frames) / expected, 1.0)
            if (
                not timing_frames
                and quiet_observation
                and clean_coverage >= policy.min_timeline_coverage
            ):
                assessed_samples += region.end_sample - region.start_sample
                missed_confidence = min(region.reference_confidence, clean_coverage)
                assessment_confidences.append(missed_confidence)
                corrections.append(
                    _correction(
                        manifest,
                        features,
                        region,
                        CorrectionType.MISSED,
                        produced_at,
                        policy,
                        confidence=missed_confidence,
                        severity=1.0,
                        observed=None,
                        reference=_metric(
                            region.target_f0_hz,
                            "hertz",
                            region.reference_confidence,
                            1.0,
                        ),
                    )
                )
                continue
            if timing_coverage < policy.min_pitch_coverage:
                if clean_coverage < policy.min_timeline_coverage:
                    leakage_blocked_regions += 1
                continue

        pitch_frames = [
            frame
            for frame in voiced_frames
            if frame.f0_hz is not None and frame.f0_confidence >= policy.min_user_f0_confidence
        ]
        pitch_coverage = min(len(pitch_frames) / expected, 1.0)
        if pitch_coverage < policy.min_pitch_coverage and timing_frames:
            pitch_frames = timing_frames
            pitch_coverage = min(len(pitch_frames) / expected, 1.0)
        if pitch_coverage < policy.min_pitch_coverage:
            continue

        assessed_samples += region.end_sample - region.start_sample
        resolved_pitch_regions += 1
        pitch_frame_count += min(len(pitch_frames), expected)
        pitch_errors = [_cents(frame.f0_hz, region.target_f0_hz) for frame in pitch_frames]
        all_pitch_errors.extend(pitch_errors)
        confidence = min(
            region.reference_confidence,
            statistics.median(frame.f0_confidence for frame in pitch_frames),
        )
        assessment_confidences.append(confidence)
        signed_error = _quantize(statistics.median(pitch_errors))
        pitch_type = _pitch_correction_type(signed_error, policy)
        if pitch_type is not None:
            corrections.append(
                _correction(
                    manifest,
                    features,
                    region,
                    pitch_type,
                    produced_at,
                    policy,
                    confidence=confidence,
                    severity=(
                        1.0
                        if pitch_type == CorrectionType.OCTAVE_ERROR
                        else min(abs(signed_error) / 200.0, 1.0)
                    ),
                    observed=_metric(signed_error, "cents", confidence, pitch_coverage),
                    reference=_metric(0.0, "cents", region.reference_confidence, 1.0),
                    evidence_start_sample=pitch_frames[0].sample_index,
                    evidence_end_sample=pitch_frames[-1].sample_index + features.hop_samples,
                )
            )

        if timing_frames:
            observed_start = timing_frames[0].sample_index
            observed_end = timing_frames[-1].sample_index + features.hop_samples
            onset_ms = _samples_to_ms(
                observed_start - region.start_sample,
                features.sample_rate,
            )
            duration_delta_ms = _samples_to_ms(
                (observed_end - observed_start) - (region.end_sample - region.start_sample),
                features.sample_rate,
            )
            onset_offsets.append(onset_ms)
            duration_deltas.append(duration_delta_ms)
            if abs(onset_ms) > policy.onset_tolerance_ms:
                corrections.append(
                    _timing_correction(
                        manifest,
                        features,
                        region,
                        CorrectionType.EARLY if onset_ms < 0 else CorrectionType.LATE,
                        onset_ms,
                        produced_at,
                        policy,
                        confidence,
                        pitch_coverage,
                        observed_start,
                        observed_end,
                    )
                )
            if abs(duration_delta_ms) > policy.duration_tolerance_ms:
                corrections.append(
                    _timing_correction(
                        manifest,
                        features,
                        region,
                        CorrectionType.SHORT if duration_delta_ms < 0 else CorrectionType.LONG,
                        duration_delta_ms,
                        produced_at,
                        policy,
                        confidence,
                        pitch_coverage,
                        observed_start,
                        observed_end,
                    )
                )

        region_duration_ms = _samples_to_ms(
            region.end_sample - region.start_sample,
            features.sample_rate,
        )
        if region_duration_ms >= policy.stability_min_duration_ms and len(pitch_errors) >= 8:
            long_tone_regions += 1
            residuals = _linear_detrend(pitch_errors)
            stability = statistics.pstdev(residuals)
            vibrato = _vibrato_descriptor(
                pitch_frames,
                residuals,
                features.sample_rate,
                features.hop_samples,
                policy,
            )
            if vibrato is not None:
                rate, depth = vibrato
                vibrato_rates.append(rate)
                vibrato_depths.append(depth)
            else:
                stability_values.append(stability)
                if stability > policy.stability_threshold_cents:
                    corrections.append(
                        _correction(
                            manifest,
                            features,
                            region,
                            CorrectionType.UNSTABLE,
                            produced_at,
                            policy,
                            confidence=confidence,
                            severity=min(
                                0.25 + (stability - policy.stability_threshold_cents) / 100,
                                1.0,
                            ),
                            observed=_metric(stability, "cents", confidence, pitch_coverage),
                            reference=_metric(
                                policy.stability_threshold_cents,
                                "cents",
                                1.0,
                                1.0,
                            ),
                            evidence_start_sample=pitch_frames[0].sample_index,
                            evidence_end_sample=(
                                pitch_frames[-1].sample_index + features.hop_samples
                            ),
                        )
                    )

    if assessed_samples == 0:
        reason = (
            "input.accompaniment_leakage"
            if leakage_blocked_regions == len(regions)
            else "input.insufficient_pitch_confidence"
        )
        return _abstain(
            manifest,
            features,
            produced_at,
            versions,
            reason,
        )

    scored_coverage = assessed_samples / total_reference_samples
    if not 0 < scored_coverage <= 1:
        raise ScoringInvariantError("scored coverage must be in (0, 1]")
    pitch_coverage = pitch_frame_count / expected_frame_count if expected_frame_count else 0.0
    voiced_coverage = voiced_frame_count / expected_frame_count if expected_frame_count else 0.0
    aggregate_confidence = _quantize(min(assessment_confidences))
    metrics: dict[str, NumericMetric] = {
        "timeline_coverage": _metric(timeline_coverage, "ratio", 1.0, timeline_coverage),
        "voiced_coverage": _metric(
            voiced_coverage,
            "ratio",
            aggregate_confidence,
            timeline_coverage,
        ),
    }
    if all_pitch_errors:
        metrics["pitch_center"] = _metric(
            statistics.median(all_pitch_errors),
            "cents",
            aggregate_confidence,
            pitch_coverage,
        )
        metrics["absolute_pitch_error"] = _metric(
            statistics.median(abs(error) for error in all_pitch_errors),
            "cents",
            aggregate_confidence,
            pitch_coverage,
        )
    _add_optional_metric(
        metrics,
        "onset_offset",
        onset_offsets,
        "milliseconds",
        aggregate_confidence,
        resolved_pitch_regions,
    )
    _add_optional_metric(
        metrics,
        "duration_delta",
        duration_deltas,
        "milliseconds",
        aggregate_confidence,
        resolved_pitch_regions,
    )
    _add_optional_metric(
        metrics,
        "long_tone_stability",
        stability_values,
        "cents",
        aggregate_confidence,
        long_tone_regions,
    )
    _add_optional_metric(
        metrics,
        "vibrato_rate",
        vibrato_rates,
        "hertz",
        aggregate_confidence,
        long_tone_regions,
    )
    _add_optional_metric(
        metrics,
        "vibrato_depth",
        vibrato_depths,
        "cents",
        aggregate_confidence,
        long_tone_regions,
    )

    corrections.sort(key=lambda event: (event.start_sample, event.correction_type.value))
    return ScoreV1(
        schema_version="score.v1",
        tenant_id=manifest.tenant_id,
        session_id=features.session_id,
        phrase_id=features.phrase_id,
        song_id=manifest.song_id,
        reference_source=manifest.reference_source,
        user_features_sha256=_model_digest(features),
        transport_evidence_sha256=features.transport_evidence_sha256,
        scored_coverage=scored_coverage,
        metrics=metrics,
        corrections=corrections,
        abstained_reason=None,
        versions=versions,
        produced_at=produced_at,
    )


def _validate_inputs(
    manifest: SongManifestV1,
    features: UserFeaturesV1,
    produced_at: datetime,
    policy: ScoringPolicy,
) -> None:
    if produced_at.tzinfo is None or produced_at.utcoffset() is None:
        raise ScoringInvariantError("produced_at must include a timezone")
    approved_fingerprint = APPROVED_POLICY_FINGERPRINTS.get(policy.score_version)
    if approved_fingerprint is None:
        raise ScoringInvariantError("scoring policy version is not registered")
    if policy.fingerprint() != approved_fingerprint:
        raise ScoringInvariantError("scoring policy fingerprint is not approved for its version")
    if manifest.tenant_id != features.tenant_id:
        raise ScoringInvariantError("manifest and features belong to different tenants")
    if manifest.sample_rate != features.sample_rate:
        raise ScoringInvariantError("manifest and features use different sample rates")
    if manifest.versions.calibration_version != features.versions.calibration_version:
        raise ScoringInvariantError("manifest and features use different calibration versions")
    if manifest.versions.score_version != policy.score_version:
        raise ScoringInvariantError("manifest score_version does not match the scoring policy")
    if features.versions.score_version != policy.score_version:
        raise ScoringInvariantError("feature score_version does not match the scoring policy")
    if produced_at < manifest.produced_at or produced_at < features.produced_at:
        raise ScoringInvariantError("produced_at cannot precede an input artifact")


def _abstain(
    manifest: SongManifestV1,
    features: UserFeaturesV1,
    produced_at: datetime,
    versions: VersionStamp,
    reason: str,
) -> ScoreV1:
    return ScoreV1(
        schema_version="score.v1",
        tenant_id=manifest.tenant_id,
        session_id=features.session_id,
        phrase_id=features.phrase_id,
        song_id=manifest.song_id,
        reference_source=manifest.reference_source,
        user_features_sha256=_model_digest(features),
        transport_evidence_sha256=features.transport_evidence_sha256,
        scored_coverage=0.0,
        metrics={},
        corrections=[],
        abstained_reason=reason,
        versions=versions,
        produced_at=produced_at,
    )


def _model_digest(model: UserFeaturesV1) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _covered_samples(region: ScorableRegion, features: UserFeaturesV1) -> int:
    start = max(region.start_sample, features.frames[0].sample_index)
    end = min(region.end_sample, features.frames[-1].sample_index + features.hop_samples)
    return max(0, end - start)


def _frames_for_regions(
    frames: Sequence[UserFeatureFrame],
    regions: Sequence[ScorableRegion],
) -> list[UserFeatureFrame]:
    return [
        frame
        for frame in frames
        if any(region.start_sample <= frame.sample_index < region.end_sample for region in regions)
    ]


def _timing_frames(
    region: ScorableRegion,
    features: UserFeaturesV1,
    policy: ScoringPolicy,
    reference_regions: Sequence[ScorableRegion],
) -> list[UserFeatureFrame]:
    window = round(policy.timing_search_window_ms * features.sample_rate / 1_000)
    output: list[UserFeatureFrame] = []
    for frame in features.frames:
        if not (region.start_sample - window <= frame.sample_index < region.end_sample + window):
            continue
        if not (region.start_sample <= frame.sample_index < region.end_sample) and any(
            other.region_id != region.region_id
            and other.start_sample <= frame.sample_index < other.end_sample
            for other in reference_regions
        ):
            continue
        if (
            not frame.voiced
            or frame.f0_hz is None
            or frame.f0_confidence < policy.min_user_f0_confidence
            or frame.leakage_confidence > policy.max_leakage_confidence
        ):
            continue
        if abs(_cents(frame.f0_hz, region.target_f0_hz)) <= policy.timing_pitch_window_cents:
            output.append(frame)
    if not output:
        return []
    max_gap_samples = round(policy.timing_max_gap_ms * features.sample_rate / 1_000)
    runs: list[list[UserFeatureFrame]] = [[output[0]]]
    for frame in output[1:]:
        if frame.sample_index - runs[-1][-1].sample_index <= max_gap_samples:
            runs[-1].append(frame)
        else:
            runs.append([frame])
    region_center = (region.start_sample + region.end_sample) / 2

    def rank(run: Sequence[UserFeatureFrame]) -> tuple[int, int, float, int]:
        overlap = sum(
            region.start_sample <= frame.sample_index < region.end_sample for frame in run
        )
        run_center = (run[0].sample_index + run[-1].sample_index + features.hop_samples) / 2
        return overlap, len(run), -abs(run_center - region_center), -run[0].sample_index

    return max(runs, key=rank)


def _pitch_correction_type(
    signed_error: float,
    policy: ScoringPolicy,
) -> CorrectionType | None:
    octave = round(signed_error / 1_200)
    if octave and abs(signed_error - octave * 1_200) <= policy.octave_tolerance_cents:
        return CorrectionType.OCTAVE_ERROR
    if signed_error >= policy.pitch_tolerance_cents:
        return CorrectionType.SHARP
    if signed_error <= -policy.pitch_tolerance_cents:
        return CorrectionType.FLAT
    return None


def _correction(
    manifest: SongManifestV1,
    features: UserFeaturesV1,
    region: ScorableRegion,
    correction_type: CorrectionType,
    produced_at: datetime,
    policy: ScoringPolicy,
    *,
    confidence: float,
    severity: float,
    observed: NumericMetric | None,
    reference: NumericMetric | None,
    evidence_start_sample: int | None = None,
    evidence_end_sample: int | None = None,
) -> CorrectionEventV1:
    reference_artifact = _reference_artifact(manifest)
    identity = "/".join(
        (
            str(manifest.tenant_id),
            str(features.session_id),
            str(features.phrase_id),
            region.region_id,
            correction_type.value,
            policy.score_version,
            policy.fingerprint(),
            manifest.source_sha256,
            manifest.versions.model_release,
            reference_artifact.sha256,
            features.source_audio_sha256,
            features.versions.model_release,
        )
    )
    user_evidence_start = (
        region.start_sample if evidence_start_sample is None else evidence_start_sample
    )
    user_evidence_end = region.end_sample if evidence_end_sample is None else evidence_end_sample
    return CorrectionEventV1(
        schema_version="correction-event.v1",
        tenant_id=manifest.tenant_id,
        session_id=features.session_id,
        phrase_id=features.phrase_id,
        correction_id=uuid5(CORRECTION_NAMESPACE, identity),
        correction_type=correction_type,
        start_sample=region.start_sample,
        end_sample=region.end_sample,
        severity=_quantize(severity),
        confidence=_quantize(confidence),
        reference_confidence=region.reference_confidence,
        observed=observed,
        reference=reference,
        evidence=[
            EvidencePointer(
                artifact_id=reference_artifact.artifact_id,
                start_sample=region.start_sample,
                end_sample=region.end_sample,
            ),
            EvidencePointer(
                artifact_id=f"user-features:{features.source_audio_sha256}",
                start_sample=user_evidence_start,
                end_sample=user_evidence_end,
            ),
        ],
        score_version=policy.score_version,
        produced_at=produced_at,
    )


def _timing_correction(
    manifest: SongManifestV1,
    features: UserFeaturesV1,
    region: ScorableRegion,
    correction_type: CorrectionType,
    offset_ms: float,
    produced_at: datetime,
    policy: ScoringPolicy,
    confidence: float,
    coverage: float,
    observed_start: int,
    observed_end: int,
) -> CorrectionEventV1:
    return _correction(
        manifest,
        features,
        region,
        correction_type,
        produced_at,
        policy,
        confidence=confidence,
        severity=min(abs(offset_ms) / 300.0, 1.0),
        observed=_metric(offset_ms, "milliseconds", confidence, coverage),
        reference=_metric(0.0, "milliseconds", 1.0, 1.0),
        evidence_start_sample=observed_start,
        evidence_end_sample=observed_end,
    )


def _reference_artifact(manifest: SongManifestV1) -> ArtifactPointer:
    authoritative_kind = (
        "notes" if manifest.reference_source == ReferenceSource.CANONICAL_NOTES else "f0"
    )
    artifact = next(
        (candidate for candidate in manifest.artifacts if candidate.kind == authoritative_kind),
        None,
    )
    if artifact is None:
        raise ScoringInvariantError(
            f"manifest is missing its authoritative {authoritative_kind} artifact"
        )
    return artifact


def _metric(
    value: float,
    unit: MetricUnit,
    confidence: float,
    coverage: float,
) -> NumericMetric:
    return NumericMetric(
        value=_quantize(value),
        unit=unit,
        confidence=_quantize(confidence),
        coverage=_quantize(coverage),
    )


def _add_optional_metric(
    metrics: dict[str, NumericMetric],
    name: str,
    values: Sequence[float],
    unit: MetricUnit,
    confidence: float,
    eligible_count: int,
) -> None:
    if values:
        metrics[name] = _metric(
            statistics.median(values),
            unit,
            confidence,
            min(len(values) / max(1, eligible_count), 1.0),
        )


def _cents(observed_hz: float | None, reference_hz: float) -> float:
    if observed_hz is None or observed_hz <= 0 or reference_hz <= 0:
        raise ScoringInvariantError("pitch values must be positive")
    return 1_200 * math.log2(observed_hz / reference_hz)


def _samples_to_ms(samples: int, sample_rate: int) -> float:
    return samples * 1_000 / sample_rate


def _linear_detrend(values: Sequence[float]) -> list[float]:
    if len(values) < 2:
        return [0.0 for _ in values]
    x_mean = (len(values) - 1) / 2
    y_mean = statistics.fmean(values)
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    slope = (
        sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values)) / denominator
        if denominator
        else 0.0
    )
    return [value - (y_mean + slope * (index - x_mean)) for index, value in enumerate(values)]


def _vibrato_descriptor(
    frames: Sequence[UserFeatureFrame],
    residuals: Sequence[float],
    sample_rate: int,
    hop_samples: int,
    policy: ScoringPolicy,
) -> tuple[float, float] | None:
    if len(frames) < 8:
        return None
    duration = (frames[-1].sample_index - frames[0].sample_index + hop_samples) / sample_rate
    if duration * 1_000 < policy.vibrato_min_duration_ms:
        return None
    center = statistics.median(residuals)
    signs = [1 if value >= center else -1 for value in residuals]
    crossings = sum(current != previous for previous, current in pairwise(signs))
    rate = crossings / (2 * duration) if duration else 0.0
    depth = (_percentile(residuals, 0.95) - _percentile(residuals, 0.05)) / 2
    if not (
        policy.vibrato_min_rate_hz <= rate <= policy.vibrato_max_rate_hz
        and policy.vibrato_min_depth_cents <= depth <= policy.vibrato_max_depth_cents
    ):
        return None
    return _quantize(rate), _quantize(depth)


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _quantize(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded

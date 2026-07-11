from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from music_ai_contracts.models import PhraseAudioV1, TransportEvidenceV1, TransportSyncV1

from music_ai_scoring_service.policy import FeaturePolicy
from music_ai_scoring_service.serialization import canonical_model_bytes, sha256_hex


class TransportCalibrationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    reference_start_sample: int
    evidence_payload: bytes
    evidence_sha256: str
    anchor: TransportSyncV1


def calibrate_phrase(
    phrase: PhraseAudioV1,
    evidence: TransportEvidenceV1,
    policy: FeaturePolicy,
) -> CalibrationResult:
    selected_by_seq: dict[int, TransportSyncV1] = {}
    for event in evidence.events:
        current = selected_by_seq.get(event.seq)
        if current is None or event.revision > current.revision:
            selected_by_seq[event.seq] = event
    selected = [selected_by_seq[seq] for seq in sorted(selected_by_seq)]
    if not selected:
        raise TransportCalibrationError("transport evidence has no authoritative events")
    if any(event.sample_rate != phrase.sample_rate for event in selected):
        raise TransportCalibrationError("transport sample rate does not match the phrase")
    if any(current.captured_at <= previous.captured_at for previous, current in pairwise(selected)):
        raise TransportCalibrationError("transport timestamps must be strictly increasing")
    if any(
        current.microphone_sample_index <= previous.microphone_sample_index
        for previous, current in pairwise(selected)
    ):
        raise TransportCalibrationError(
            "transport microphone positions must be strictly increasing"
        )

    segments: list[list[TransportSyncV1]] = [[selected[0]]]
    for previous, current in pairwise(selected):
        microphone_delta = current.microphone_sample_index - previous.microphone_sample_index
        playhead_delta = current.playhead_samples - previous.playhead_samples
        observed_rate_ppm = (
            abs(playhead_delta / microphone_delta - 1.0) * 1_000_000
            if playhead_delta > 0
            else float("inf")
        )
        if observed_rate_ppm <= policy.max_segment_rate_error_ppm:
            segments[-1].append(current)
        else:
            segments.append([current])

    maximum_distance = round(policy.max_anchor_distance_ms * phrase.sample_rate / 1_000)
    left_anchor = max(
        (
            event
            for event in selected
            if event.microphone_sample_index <= phrase.sample_start
        ),
        key=lambda event: event.microphone_sample_index,
        default=None,
    )
    right_anchor = min(
        (
            event
            for event in selected
            if event.microphone_sample_index >= phrase.sample_end
        ),
        key=lambda event: event.microphone_sample_index,
        default=None,
    )
    if left_anchor is None or right_anchor is None:
        raise TransportCalibrationError("transport evidence does not bracket the phrase")
    if (
        phrase.sample_start - left_anchor.microphone_sample_index > maximum_distance
        or right_anchor.microphone_sample_index - phrase.sample_end > maximum_distance
    ):
        raise TransportCalibrationError("transport boundary anchor is too far from the phrase")
    selected_segment = next(
        (
            segment
            for segment in segments
            if left_anchor in segment and right_anchor in segment
        ),
        None,
    )
    if selected_segment is None:
        raise TransportCalibrationError("transport seek or loop crosses the phrase")
    phrase_segment = [
        event
        for event in selected_segment
        if left_anchor.microphone_sample_index
        <= event.microphone_sample_index
        <= right_anchor.microphone_sample_index
    ]
    anchor = min(
        phrase_segment,
        key=lambda event: abs(event.microphone_sample_index - phrase.sample_start),
    )
    if abs(anchor.drift_ppm) > policy.max_compensable_drift_ppm:
        raise TransportCalibrationError("transport drift exceeds the compensable limit")

    maximum_residual = policy.max_anchor_residual_ms * phrase.sample_rate / 1_000
    rate = 1.0 + anchor.drift_ppm / 1_000_000
    for event in phrase_segment:
        predicted = (
            anchor.playhead_samples
            + (event.microphone_sample_index - anchor.microphone_sample_index) / rate
        )
        if abs(predicted - event.playhead_samples) > maximum_residual:
            raise TransportCalibrationError("transport anchors contradict the declared drift")

    phrase_duration = phrase.sample_end - phrase.sample_start
    drift_error_samples = phrase_duration * abs(anchor.drift_ppm) / 1_000_000
    maximum_error_samples = policy.max_uncompensated_error_ms * phrase.sample_rate / 1_000
    if drift_error_samples > maximum_error_samples:
        raise TransportCalibrationError("transport drift would exceed the timeline error budget")

    reference_start = round(
        anchor.playhead_samples + (phrase.sample_start - anchor.microphone_sample_index) / rate
    )
    if reference_start < 0:
        raise TransportCalibrationError("transport maps the phrase before the song timeline")
    payload = canonical_model_bytes(evidence)
    return CalibrationResult(
        reference_start_sample=reference_start,
        evidence_payload=payload,
        evidence_sha256=sha256_hex(payload),
        anchor=anchor,
    )

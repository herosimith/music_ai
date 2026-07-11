from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from music_ai_contracts.models import TransportSyncV1
from music_ai_scoring_service.calibration import TransportCalibrationError, calibrate_phrase
from music_ai_scoring_service.policy import DEFAULT_POLICY
from scoring_service_testkit import (
    CAPTURED_AT,
    PHRASE_END,
    PHRASE_START,
    REFERENCE_END,
    REFERENCE_START,
    SAMPLE_RATE,
    SESSION_ID,
    TENANT_ID,
    make_phrase,
    make_transport,
)


def test_calibration_maps_phrase_start_and_hashes_canonical_evidence() -> None:
    phrase, _ = make_phrase()
    evidence = make_transport(drift_ppm=20.0)

    result = calibrate_phrase(phrase, evidence, DEFAULT_POLICY)

    assert result.reference_start_sample == REFERENCE_START
    assert len(result.evidence_sha256) == 64
    assert result.evidence_payload.startswith(b'{"calibration_version"')


def test_latest_revision_wins_deterministically() -> None:
    phrase, _ = make_phrase()
    events = [
        _event(10, 0, PHRASE_START, REFERENCE_START, CAPTURED_AT - timedelta(seconds=2)),
        _event(10, 1, PHRASE_START, REFERENCE_START + 100, CAPTURED_AT - timedelta(seconds=1)),
        _event(11, 0, PHRASE_END, REFERENCE_END + 100, CAPTURED_AT),
    ]
    evidence = make_transport(events=events)

    result = calibrate_phrase(phrase, evidence, DEFAULT_POLICY)

    assert result.anchor.revision == 1
    assert result.reference_start_sample == REFERENCE_START + 100


def test_seek_inside_phrase_and_distant_anchor_fail_closed() -> None:
    phrase, _ = make_phrase()
    seek_events = [
        _event(10, 0, PHRASE_START, REFERENCE_START, CAPTURED_AT - timedelta(seconds=1)),
        _event(11, 0, PHRASE_START + 24_000, 100_000, CAPTURED_AT),
        _event(12, 0, PHRASE_END, 124_000, CAPTURED_AT + timedelta(seconds=1)),
    ]
    with pytest.raises(TransportCalibrationError, match="seek or loop"):
        calibrate_phrase(phrase, make_transport(events=seek_events), DEFAULT_POLICY)

    far_event = _event(10, 0, 0, 0, CAPTURED_AT)
    with pytest.raises(TransportCalibrationError, match="does not bracket"):
        calibrate_phrase(phrase, make_transport(events=[far_event]), DEFAULT_POLICY)


def test_single_anchor_cannot_prove_continuous_phrase_playback() -> None:
    phrase, _ = make_phrase()
    with pytest.raises(TransportCalibrationError, match="does not bracket"):
        calibrate_phrase(
            phrase,
            make_transport(events=[make_transport().events[0]]),
            DEFAULT_POLICY,
        )


def test_drift_and_anchor_residual_limits_fail_closed_at_boundaries() -> None:
    phrase, _ = make_phrase()
    with pytest.raises(TransportCalibrationError, match="compensable"):
        calibrate_phrase(phrase, make_transport(drift_ppm=1_001.0), DEFAULT_POLICY)

    strict_error = replace(DEFAULT_POLICY, max_uncompensated_error_ms=0.5)
    with pytest.raises(TransportCalibrationError, match="error budget"):
        calibrate_phrase(phrase, make_transport(drift_ppm=1_000.0), strict_error)

    contradictory = [
        _event(10, 0, PHRASE_START, REFERENCE_START, CAPTURED_AT - timedelta(seconds=1)),
        _event(11, 0, PHRASE_END, REFERENCE_END + 100, CAPTURED_AT),
    ]
    strict_residual = replace(DEFAULT_POLICY, max_anchor_residual_ms=1.0)
    with pytest.raises(TransportCalibrationError, match="contradict"):
        calibrate_phrase(phrase, make_transport(events=contradictory), strict_residual)


def test_non_monotonic_transport_time_is_rejected() -> None:
    phrase, _ = make_phrase()
    events = [
        _event(10, 0, PHRASE_START, REFERENCE_START, CAPTURED_AT),
        _event(11, 0, PHRASE_END, REFERENCE_END, CAPTURED_AT - timedelta(seconds=1)),
    ]
    with pytest.raises(TransportCalibrationError, match="timestamps"):
        calibrate_phrase(phrase, make_transport(events=events), DEFAULT_POLICY)


def _event(
    seq: int,
    revision: int,
    microphone_sample_index: int,
    playhead_samples: int,
    captured_at,
) -> TransportSyncV1:
    return TransportSyncV1(
        schema_version="transport.v1",
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        seq=seq,
        revision=revision,
        captured_at=captured_at,
        playhead_samples=playhead_samples,
        microphone_sample_index=microphone_sample_index,
        sample_rate=SAMPLE_RATE,
        drift_ppm=0.0,
    )

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ScoringPolicy:
    score_version: str = "score.v1"
    pipeline_version: str = "scoring-core.v1"
    min_reference_confidence: float = 0.80
    min_monophonic_confidence: float = 0.80
    min_user_f0_confidence: float = 0.80
    max_leakage_confidence: float = 0.20
    min_timeline_coverage: float = 0.80
    min_pitch_coverage: float = 0.50
    missed_voiced_coverage: float = 0.10
    missed_max_energy_dbfs: float = -45.0
    pitch_tolerance_cents: float = 25.0
    octave_tolerance_cents: float = 100.0
    timing_pitch_window_cents: float = 175.0
    timing_search_window_ms: float = 250.0
    timing_max_gap_ms: float = 30.0
    onset_tolerance_ms: float = 80.0
    duration_tolerance_ms: float = 120.0
    stability_min_duration_ms: float = 800.0
    stability_threshold_cents: float = 35.0
    vibrato_min_duration_ms: float = 1_000.0
    vibrato_min_rate_hz: float = 3.0
    vibrato_max_rate_hz: float = 9.0
    vibrato_min_depth_cents: float = 15.0
    vibrato_max_depth_cents: float = 120.0

    def __post_init__(self) -> None:
        if not self.score_version.strip() or not self.pipeline_version.strip():
            raise ValueError("score and pipeline versions must not be empty")
        unit_fields = (
            self.min_reference_confidence,
            self.min_monophonic_confidence,
            self.min_user_f0_confidence,
            self.max_leakage_confidence,
            self.min_timeline_coverage,
            self.min_pitch_coverage,
            self.missed_voiced_coverage,
        )
        if any(not math.isfinite(value) or value < 0 or value > 1 for value in unit_fields):
            raise ValueError("confidence and coverage thresholds must be between zero and one")
        if self.missed_voiced_coverage >= self.min_pitch_coverage:
            raise ValueError("missed threshold must be below the pitch coverage threshold")
        if not -160 <= self.missed_max_energy_dbfs <= 12:
            raise ValueError("missed energy threshold must be a valid dBFS value")
        positive_fields = (
            self.pitch_tolerance_cents,
            self.octave_tolerance_cents,
            self.timing_pitch_window_cents,
            self.timing_search_window_ms,
            self.timing_max_gap_ms,
            self.onset_tolerance_ms,
            self.duration_tolerance_ms,
            self.stability_min_duration_ms,
            self.stability_threshold_cents,
            self.vibrato_min_duration_ms,
            self.vibrato_min_rate_hz,
            self.vibrato_max_rate_hz,
            self.vibrato_min_depth_cents,
            self.vibrato_max_depth_cents,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive_fields):
            raise ValueError("scoring tolerances and bounds must be finite and positive")
        if self.octave_tolerance_cents >= 600:
            raise ValueError("octave tolerance must stay below half an octave")
        if self.vibrato_min_rate_hz >= self.vibrato_max_rate_hz:
            raise ValueError("vibrato rate bounds are inverted")
        if self.vibrato_min_depth_cents >= self.vibrato_max_depth_cents:
            raise ValueError("vibrato depth bounds are inverted")

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("ascii")).hexdigest()


DEFAULT_POLICY = ScoringPolicy()
APPROVED_POLICY_FINGERPRINTS: Mapping[str, str] = MappingProxyType(
    {
        "score.v1": "bf1891a5fe6794d11a17e352fb3b3e22eea1cde04bc2483f92122871d51d0ae3",
    }
)

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType


class FeaturePolicyAuthorizationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FeaturePolicy:
    pipeline_version: str = "audio-features.v1"
    score_version: str = "score.v1"
    hop_samples: int = 480
    max_anchor_distance_ms: float = 2_000.0
    max_compensable_drift_ppm: float = 1_000.0
    max_uncompensated_error_ms: float = 2.0
    max_anchor_residual_ms: float = 5.0
    max_segment_rate_error_ppm: float = 5_000.0

    def __post_init__(self) -> None:
        if not self.pipeline_version.strip() or not self.score_version.strip():
            raise ValueError("pipeline and score versions must not be empty")
        if not 0 < self.hop_samples <= 16_384:
            raise ValueError("hop_samples must be between 1 and 16384")
        numeric = (
            self.max_anchor_distance_ms,
            self.max_compensable_drift_ppm,
            self.max_uncompensated_error_ms,
            self.max_anchor_residual_ms,
            self.max_segment_rate_error_ppm,
        )
        if any(not math.isfinite(value) or value <= 0 for value in numeric):
            raise ValueError("calibration bounds must be finite and positive")

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("ascii")).hexdigest()


DEFAULT_POLICY = FeaturePolicy()
APPROVED_POLICY_FINGERPRINTS: Mapping[str, str] = MappingProxyType(
    {"audio-features.v1": "2bf860eeabf6ef38dce94a7ed80cd865fc06a4d07042a2024bd69896d2b051d8"}
)


def require_approved_policy(policy: FeaturePolicy) -> None:
    expected = APPROVED_POLICY_FINGERPRINTS.get(policy.pipeline_version)
    if expected is None or not hmac.compare_digest(policy.fingerprint(), expected):
        raise FeaturePolicyAuthorizationError(
            f"feature policy fingerprint is not approved for {policy.pipeline_version}"
        )

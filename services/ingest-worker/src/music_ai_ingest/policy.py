from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType


class PolicyAuthorizationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IngestPolicy:
    pipeline_version: str = "ingest.v1"
    score_version: str = "score.v1"
    min_reference_confidence: float = 0.80
    min_monophonic_confidence: float = 0.80
    min_region_voiced_coverage: float = 0.70
    min_scorable_vocal_coverage: float = 0.35
    min_vocal_presence_coverage: float = 0.05
    min_separation_confidence: float = 0.70
    max_accompaniment_leakage: float = 0.25
    min_region_duration_ms: float = 100.0

    def __post_init__(self) -> None:
        if not self.pipeline_version.strip() or not self.score_version.strip():
            raise ValueError("pipeline and score versions must not be empty")
        unit_fields = (
            self.min_reference_confidence,
            self.min_monophonic_confidence,
            self.min_region_voiced_coverage,
            self.min_scorable_vocal_coverage,
            self.min_vocal_presence_coverage,
            self.min_separation_confidence,
            self.max_accompaniment_leakage,
        )
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in unit_fields):
            raise ValueError("quality thresholds must be finite values between zero and one")
        if not math.isfinite(self.min_region_duration_ms) or self.min_region_duration_ms <= 0:
            raise ValueError("minimum region duration must be finite and positive")

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("ascii")).hexdigest()


DEFAULT_POLICY = IngestPolicy()
APPROVED_POLICY_FINGERPRINTS: Mapping[str, str] = MappingProxyType(
    {
        "ingest.v1": "4b8f040c1cbde637e99464db6f80b8187c939fe68aae49cc51057e0626d8c8f8",
    }
)


def require_approved_policy(policy: IngestPolicy) -> None:
    expected = APPROVED_POLICY_FINGERPRINTS.get(policy.pipeline_version)
    if expected is None or not hmac.compare_digest(policy.fingerprint(), expected):
        raise PolicyAuthorizationError(
            f"quality policy fingerprint is not approved for {policy.pipeline_version}"
        )

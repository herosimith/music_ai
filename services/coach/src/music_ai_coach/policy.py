from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType

from music_ai_coach.types import CoachExercise


class CoachPolicyAuthorizationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CoachPolicy:
    coach_version: str = "coach.v1"
    template_version: str = "coach-templates.v1"
    max_actions: int = 2
    slow_speed: float = 0.75
    loop_repetitions: int = 3
    reference_tone_duration_ms: int = 800
    reference_tone_min_hz: float = 55.0
    reference_tone_max_hz: float = 1_100.0
    allowed_actions: tuple[str, ...] = (
        CoachExercise.LOOP.value,
        CoachExercise.REFERENCE_TONE.value,
        CoachExercise.SLOW.value,
        CoachExercise.TEXT.value,
    )
    correction_priority: tuple[str, ...] = (
        "octave_error",
        "missed",
        "sharp",
        "flat",
        "early",
        "late",
        "short",
        "long",
        "unstable",
    )

    def __post_init__(self) -> None:
        if not self.coach_version.strip() or not self.template_version.strip():
            raise ValueError("coach and template versions must not be empty")
        if not 1 <= self.max_actions <= 8:
            raise ValueError("max_actions must be between 1 and 8")
        if not 0.5 <= self.slow_speed <= 1.0:
            raise ValueError("slow_speed must be between 0.5 and 1.0")
        if not 1 <= self.loop_repetitions <= 8:
            raise ValueError("loop_repetitions must be between 1 and 8")
        if not 100 <= self.reference_tone_duration_ms <= 5_000:
            raise ValueError("reference tone duration is outside the contract")
        if (
            not math.isfinite(self.reference_tone_min_hz)
            or not math.isfinite(self.reference_tone_max_hz)
            or self.reference_tone_min_hz < 55.0
            or self.reference_tone_max_hz > 1_100.0
            or self.reference_tone_min_hz >= self.reference_tone_max_hz
        ):
            raise ValueError("reference tone bounds are unsafe")
        known_actions = {exercise.value for exercise in CoachExercise}
        if set(self.allowed_actions) != known_actions:
            raise ValueError("coach v1 must explicitly approve its complete action allowlist")
        if len(self.correction_priority) != len(set(self.correction_priority)):
            raise ValueError("correction priorities must be unique")

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("ascii")).hexdigest()


DEFAULT_POLICY = CoachPolicy()
APPROVED_COACH_POLICY_FINGERPRINTS: Mapping[str, str] = MappingProxyType(
    {"coach.v1": "16c4bdc5b4205234f27142be76127a478e90a952840ad3ae9f67755f7fed02a2"}
)


def require_approved_policy(policy: CoachPolicy) -> None:
    expected = APPROVED_COACH_POLICY_FINGERPRINTS.get(policy.coach_version)
    if expected is None or not hmac.compare_digest(policy.fingerprint(), expected):
        raise CoachPolicyAuthorizationError(
            f"coach policy fingerprint is not approved for {policy.coach_version}"
        )

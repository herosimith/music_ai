from __future__ import annotations

from dataclasses import replace

import pytest
from music_ai_coach.policy import (
    APPROVED_COACH_POLICY_FINGERPRINTS,
    DEFAULT_POLICY,
    CoachPolicy,
    CoachPolicyAuthorizationError,
    require_approved_policy,
)


def test_default_coach_policy_has_committed_fingerprint() -> None:
    assert DEFAULT_POLICY.fingerprint() == APPROVED_COACH_POLICY_FINGERPRINTS["coach.v1"]
    require_approved_policy(DEFAULT_POLICY)


def test_policy_changes_require_new_approval() -> None:
    with pytest.raises(CoachPolicyAuthorizationError, match="not approved"):
        require_approved_policy(replace(DEFAULT_POLICY, max_actions=3))
    with pytest.raises(CoachPolicyAuthorizationError, match="not approved"):
        require_approved_policy(replace(DEFAULT_POLICY, coach_version="coach.v2"))


def test_policy_rejects_unsafe_or_incomplete_controls() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        CoachPolicy(reference_tone_max_hz=2_000.0)
    with pytest.raises(ValueError, match="complete action allowlist"):
        CoachPolicy(allowed_actions=("text",))

from __future__ import annotations

from dataclasses import replace

import pytest
from music_ai_scoring_service.policy import (
    APPROVED_POLICY_FINGERPRINTS,
    DEFAULT_POLICY,
    FeaturePolicy,
    FeaturePolicyAuthorizationError,
    require_approved_policy,
)


def test_default_feature_policy_has_committed_fingerprint() -> None:
    assert DEFAULT_POLICY.fingerprint() == APPROVED_POLICY_FINGERPRINTS["audio-features.v1"]
    require_approved_policy(DEFAULT_POLICY)


def test_feature_policy_changes_require_new_version_approval() -> None:
    with pytest.raises(FeaturePolicyAuthorizationError, match="not approved"):
        require_approved_policy(replace(DEFAULT_POLICY, hop_samples=240))
    with pytest.raises(FeaturePolicyAuthorizationError, match="not approved"):
        require_approved_policy(replace(DEFAULT_POLICY, pipeline_version="audio-features.v2"))


def test_feature_policy_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="hop_samples"):
        FeaturePolicy(hop_samples=0)
    with pytest.raises(ValueError, match="finite and positive"):
        FeaturePolicy(max_anchor_distance_ms=float("inf"))

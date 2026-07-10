from __future__ import annotations

from dataclasses import replace

import pytest
from music_ai_ingest.policy import (
    APPROVED_POLICY_FINGERPRINTS,
    DEFAULT_POLICY,
    IngestPolicy,
    PolicyAuthorizationError,
    require_approved_policy,
)


def test_default_quality_policy_has_committed_fingerprint() -> None:
    assert DEFAULT_POLICY.fingerprint() == APPROVED_POLICY_FINGERPRINTS["ingest.v1"]
    require_approved_policy(DEFAULT_POLICY)


def test_threshold_or_version_changes_require_new_approval() -> None:
    with pytest.raises(PolicyAuthorizationError, match="not approved"):
        require_approved_policy(replace(DEFAULT_POLICY, min_reference_confidence=0.81))
    with pytest.raises(PolicyAuthorizationError, match="not approved"):
        require_approved_policy(replace(DEFAULT_POLICY, pipeline_version="ingest.v2"))


def test_quality_policy_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        IngestPolicy(min_scorable_vocal_coverage=1.1)
    with pytest.raises(ValueError, match="finite and positive"):
        IngestPolicy(min_region_duration_ms=0)

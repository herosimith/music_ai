from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from music_ai_contracts.registry import (
    ModelRecord,
    ModelRegistryV1,
    ModelTask,
    TrainingDataReview,
)
from music_ai_model_runtime import (
    ModelAuthorizationError,
    ModelAuthorizer,
    ModelBinding,
    bound_model_release,
    model_set_release,
)


def test_authorizer_verifies_registry_task_constraints_and_weight_digest(tmp_path: Path) -> None:
    artifact = tmp_path / "model.weights"
    artifact.write_bytes(b"approved-model")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    record = ModelRecord(
        model_id="f0.test.v1",
        task=ModelTask.F0,
        artifact_sha256=digest,
        source_url="https://models.example.test/f0.test.v1",
        code_license_spdx="MIT",
        weight_license_spdx="LicenseRef-Test",
        training_data_review=TrainingDataReview.APPROVED,
        commercial_use_approved=True,
        approved_by="test-reviewer",
        approved_at=datetime(2026, 7, 11, tzinfo=UTC),
        constraints=["region:cn"],
    )
    registry = ModelRegistryV1(schema_version="model-registry.v1", models=[record])
    binding = ModelBinding("f0.test.v1", ModelTask.F0, artifact)

    with pytest.raises(ModelAuthorizationError, match="unsatisfied"):
        ModelAuthorizer(registry).authorize(binding, ModelTask.F0)
    authorized = ModelAuthorizer(
        registry,
        satisfied_constraints=frozenset({"region:cn"}),
    ).authorize(binding, ModelTask.F0)
    assert authorized.artifact_size == len(b"approved-model")

    artifact.write_bytes(b"tampered")
    with pytest.raises(ModelAuthorizationError, match="digest"):
        ModelAuthorizer(
            registry,
            satisfied_constraints=frozenset({"region:cn"}),
        ).authorize(binding, ModelTask.F0)


def test_provenance_binds_full_digest_and_model_set_is_order_independent() -> None:
    first = bound_model_release("first.model.v1", "a" * 64)
    second = bound_model_release("second.model.v1", "b" * 64)
    assert first.endswith("a" * 64)
    assert len(first) <= 128
    assert model_set_release(first, second) == model_set_release(second, first)

    shared_prefix = "long-model." + "x" * 45
    long_first = bound_model_release(f"{shared_prefix}.first", "c" * 64)
    long_second = bound_model_release(f"{shared_prefix}.second", "c" * 64)
    assert long_first != long_second
    assert "~" in long_first
    assert long_first.endswith("c" * 64)
    assert len(long_first) <= 128

    with pytest.raises(ValueError, match="must not be empty"):
        model_set_release()
    with pytest.raises(ValueError, match="must be unique"):
        model_set_release(first, first)

from __future__ import annotations

from pathlib import Path

import pytest
from ingest_testkit import make_authorized_models
from music_ai_contracts.registry import ModelRegistryV1, ModelTask
from music_ai_ingest.model_gate import ModelAuthorizationError, ModelAuthorizer
from music_ai_ingest.providers import ModelBinding


def test_empty_registry_and_changed_weight_fail_closed(tmp_path: Path) -> None:
    _, separation_binding, _, _ = make_authorized_models(tmp_path)
    empty = ModelAuthorizer(ModelRegistryV1(schema_version="model-registry.v1", models=[]))
    with pytest.raises(ModelAuthorizationError, match="absent"):
        empty.authorize(separation_binding, ModelTask.SOURCE_SEPARATION)

    authorizer, separation_binding, _, _ = make_authorized_models(tmp_path)
    separation_binding.artifact_path.write_bytes(b"tampered-after-approval")
    with pytest.raises(ModelAuthorizationError, match="digest"):
        authorizer.authorize(separation_binding, ModelTask.SOURCE_SEPARATION)


def test_model_task_commercial_gate_and_constraints_are_enforced(tmp_path: Path) -> None:
    authorizer, separation_binding, f0_binding, registry = make_authorized_models(
        tmp_path,
        constraints=("region:cn",),
    )
    approved = authorizer.authorize(separation_binding, ModelTask.SOURCE_SEPARATION)
    assert approved.record.model_id == separation_binding.model_id
    assert approved.artifact_size == separation_binding.artifact_path.stat().st_size

    wrong_binding_task = ModelBinding(
        separation_binding.model_id,
        ModelTask.F0,
        separation_binding.artifact_path,
    )
    with pytest.raises(ModelAuthorizationError, match="binding declares"):
        authorizer.authorize(wrong_binding_task, ModelTask.SOURCE_SEPARATION)

    wrong_registered_task = ModelBinding(
        f0_binding.model_id,
        ModelTask.SOURCE_SEPARATION,
        f0_binding.artifact_path,
    )
    with pytest.raises(ModelAuthorizationError, match="registered model task"):
        authorizer.authorize(wrong_registered_task, ModelTask.SOURCE_SEPARATION)

    constrained = ModelAuthorizer(registry)
    with pytest.raises(ModelAuthorizationError, match="unsatisfied"):
        constrained.authorize(separation_binding, ModelTask.SOURCE_SEPARATION)

    unapproved_record = registry.models[0].model_copy(update={"commercial_use_approved": False})
    unapproved = ModelAuthorizer(
        ModelRegistryV1(schema_version="model-registry.v1", models=[unapproved_record]),
        satisfied_constraints=frozenset({"region:cn"}),
    )
    with pytest.raises(ModelAuthorizationError, match="commercial"):
        unapproved.authorize(separation_binding, ModelTask.SOURCE_SEPARATION)


def test_missing_or_non_file_model_artifact_is_rejected(tmp_path: Path) -> None:
    authorizer, separation_binding, _, _ = make_authorized_models(tmp_path)
    missing = ModelBinding(
        separation_binding.model_id,
        ModelTask.SOURCE_SEPARATION,
        tmp_path / "missing.weights",
    )
    with pytest.raises(ModelAuthorizationError, match="unavailable"):
        authorizer.authorize(missing, ModelTask.SOURCE_SEPARATION)

    directory = tmp_path / "weight-directory"
    directory.mkdir()
    not_file = ModelBinding(
        separation_binding.model_id,
        ModelTask.SOURCE_SEPARATION,
        directory,
    )
    with pytest.raises(ModelAuthorizationError, match="regular file"):
        authorizer.authorize(not_file, ModelTask.SOURCE_SEPARATION)

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as JsonSchemaError
from music_ai_contracts.models import (
    CONTRACT_MODELS,
    CoachActionV1,
    PhraseAudioV1,
    ReferenceF0V1,
    ScoreV1,
    SongManifestV1,
    TransportEvidenceV1,
    TransportSyncV1,
    UserFeaturesV1,
)
from music_ai_contracts.registry import ModelRegistryV1, load_registry, schema_text
from music_ai_contracts.schema import schemas
from pydantic import ValidationError

CONTRACTS_ROOT = Path(__file__).parents[2]
REPOSITORY_ROOT = Path(__file__).parents[4]
REGISTRY_ROOT = REPOSITORY_ROOT / "models" / "registry"


@pytest.mark.parametrize("schema_version", sorted(CONTRACT_MODELS))
def test_committed_schema_matches_source_exactly(schema_version: str) -> None:
    committed_text = (CONTRACTS_ROOT / "schemas" / f"{schema_version}.schema.json").read_text(
        encoding="utf-8"
    )
    expected_text = json.dumps(schemas()[schema_version], indent=2, sort_keys=True) + "\n"
    assert committed_text == expected_text
    Draft202012Validator.check_schema(json.loads(committed_text))


def test_contract_file_sets_match_registered_models() -> None:
    expected = set(CONTRACT_MODELS)
    schemas_found = {
        path.name.removesuffix(".schema.json")
        for path in (CONTRACTS_ROOT / "schemas").glob("*.schema.json")
    }
    examples_found = {
        path.name.removesuffix(".json") for path in (CONTRACTS_ROOT / "examples").glob("*.json")
    }
    assert schemas_found == expected
    assert examples_found == expected


@pytest.mark.parametrize("schema_version", sorted(CONTRACT_MODELS))
def test_examples_validate_in_pydantic_and_json_schema(schema_version: str) -> None:
    example = _example(schema_version)
    model = CONTRACT_MODELS[schema_version].model_validate(example)
    assert model.model_dump(mode="json")["schema_version"] == schema_version
    Draft202012Validator(
        schemas()[schema_version],
        format_checker=FormatChecker(),
    ).validate(example)


@pytest.mark.parametrize("schema_version", sorted(CONTRACT_MODELS))
def test_pydantic_rejects_unknown_fields(schema_version: str) -> None:
    example = _example(schema_version)
    example["unexpected"] = "must fail"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CONTRACT_MODELS[schema_version].model_validate(example)


@pytest.mark.parametrize("schema_version", sorted(CONTRACT_MODELS))
def test_pydantic_requires_explicit_schema_version(schema_version: str) -> None:
    example = _example(schema_version)
    del example["schema_version"]
    with pytest.raises(ValidationError, match="Field required"):
        CONTRACT_MODELS[schema_version].model_validate(example)


def test_phrase_rejects_inverted_sample_range() -> None:
    data = _example("phrase-audio.v1")
    data["sample_end"] = data["sample_start"]
    with pytest.raises(ValidationError, match="sample_end must be greater"):
        PhraseAudioV1.model_validate(data)


def test_phrase_rejects_payload_length_mismatch() -> None:
    data = _example("phrase-audio.v1")
    data["byte_length"] = 44
    with pytest.raises(ValidationError, match="WAV byte_length"):
        PhraseAudioV1.model_validate(data)


def test_raw_pcm_requires_exact_payload_length() -> None:
    data = _example("phrase-audio.v1")
    data["codec"] = "pcm_s16le"
    data["byte_length"] = (data["sample_end"] - data["sample_start"]) * 2
    assert PhraseAudioV1.model_validate(data).codec == "pcm_s16le"
    data["byte_length"] += 1
    with pytest.raises(ValidationError, match="raw PCM byte_length"):
        PhraseAudioV1.model_validate(data)


def test_phrase_rejects_naive_timestamp() -> None:
    data = _example("phrase-audio.v1")
    data["captured_at"] = "2026-07-11T04:00:05"
    with pytest.raises(ValidationError, match="timezone"):
        PhraseAudioV1.model_validate(data)


def test_transport_rejects_naive_timestamp() -> None:
    data = _example("transport.v1")
    data["captured_at"] = "2026-07-11T04:00:05"
    with pytest.raises(ValidationError, match="timezone"):
        TransportSyncV1.model_validate(data)


def test_transport_evidence_requires_sorted_matching_events() -> None:
    data = _example("transport-evidence.v1")
    data["events"] = list(reversed(data["events"]))
    with pytest.raises(ValidationError, match="unique and sorted"):
        TransportEvidenceV1.model_validate(data)

    data = _example("transport-evidence.v1")
    data["events"][0]["session_id"] = "99999999-9999-4999-8999-999999999999"
    with pytest.raises(ValidationError, match="identity must match"):
        TransportEvidenceV1.model_validate(data)

    data = _example("transport-evidence.v1")
    data["produced_at"] = "2026-07-11T04:00:03Z"
    with pytest.raises(ValidationError, match="cannot predate"):
        TransportEvidenceV1.model_validate(data)


@pytest.mark.parametrize("status", ["rejected", "practice_only"])
def test_non_scoring_manifest_cannot_claim_scorable_regions(status: str) -> None:
    data = _example("song-manifest.v1")
    data["gate_status"] = status
    with pytest.raises(ValidationError, match="non-scoring songs cannot contain"):
        SongManifestV1.model_validate(data)


def test_accepted_manifest_cannot_have_blocking_issue() -> None:
    data = _example("song-manifest.v1")
    data["quality_issues"][0]["severity"] = "blocking"
    with pytest.raises(ValidationError, match="blocking quality issues"):
        SongManifestV1.model_validate(data)


def test_reference_source_requires_matching_artifacts() -> None:
    data = _example("song-manifest.v1")
    data["artifacts"] = [artifact for artifact in data["artifacts"] if artifact["kind"] != "vocal"]
    with pytest.raises(ValidationError, match="missing required artifacts"):
        SongManifestV1.model_validate(data)


def test_abstained_score_cannot_contain_corrections() -> None:
    data = _example("score.v1")
    data["abstained_reason"] = "input.leakage"
    with pytest.raises(ValidationError, match="abstained scores cannot contain"):
        ScoreV1.model_validate(data)


def test_valid_abstained_score_is_first_class_result() -> None:
    data = _example("score.v1")
    data["abstained_reason"] = "input.leakage"
    data["scored_coverage"] = 0
    data["metrics"] = {}
    data["corrections"] = []
    assert ScoreV1.model_validate(data).abstained_reason == "input.leakage"


def test_score_rejects_correction_from_another_tenant() -> None:
    data = _example("score.v1")
    data["corrections"][0]["tenant_id"] = "77777777-7777-4777-8777-777777777777"
    with pytest.raises(ValidationError, match="identity must match"):
        ScoreV1.model_validate(data)


def test_unvoiced_frame_cannot_carry_f0() -> None:
    data = _example("user-features.v1")
    data["frames"][0]["voiced"] = False
    with pytest.raises(ValidationError, match="unvoiced frames cannot"):
        UserFeaturesV1.model_validate(data)


def test_feature_model_releases_are_unique_and_sorted() -> None:
    data = _example("user-features.v1")
    data["model_releases"] = list(reversed(data["model_releases"]))
    with pytest.raises(ValidationError, match="unique and sorted"):
        UserFeaturesV1.model_validate(data)


def test_score_example_binds_canonical_feature_and_transport_examples() -> None:
    transport = TransportEvidenceV1.model_validate(_example("transport-evidence.v1"))
    features = UserFeaturesV1.model_validate(_example("user-features.v1"))
    score = ScoreV1.model_validate(_example("score.v1"))

    transport_digest = _canonical_digest(transport)
    feature_digest = _canonical_digest(features)
    assert features.transport_evidence_sha256 == transport_digest
    assert score.transport_evidence_sha256 == transport_digest
    assert score.user_features_sha256 == feature_digest
    assert score.versions.model_release == features.versions.model_release


def test_feature_frames_must_be_contiguous() -> None:
    data = _example("user-features.v1")
    data["frames"][1]["sample_index"] += data["hop_samples"]
    with pytest.raises(ValidationError, match="contiguous by hop_samples"):
        UserFeaturesV1.model_validate(data)


def test_reference_f0_frames_must_be_voicing_consistent_and_contiguous() -> None:
    data = _example("reference-f0.v1")
    data["frames"][0]["voiced"] = False
    with pytest.raises(ValidationError, match="unvoiced reference frames"):
        ReferenceF0V1.model_validate(data)

    data = _example("reference-f0.v1")
    data["frames"][1]["sample_index"] += data["hop_samples"]
    with pytest.raises(ValidationError, match="contiguous by hop_samples"):
        ReferenceF0V1.model_validate(data)

    data = _example("reference-f0.v1")
    data["candidates"].append({"start_sample": 900000, "end_sample": 950000, "ornament": False})
    with pytest.raises(ValidationError, match="must not overlap"):
        ReferenceF0V1.model_validate(data)


def test_coach_action_arguments_match_discriminator() -> None:
    data = _example("coach-action.v1")
    data["arguments"] = {"speed": 0.8, "start_sample": 0, "end_sample": 100}
    with pytest.raises(ValidationError):
        CoachActionV1.model_validate(data)


def test_coach_action_rejects_unsafe_reference_tone_and_duplicate_sources() -> None:
    data = _example("coach-action.v1")
    data["action_type"] = "reference_tone"
    data["arguments"] = {"f0_hz": 20_000, "duration_ms": 800}
    with pytest.raises(ValidationError):
        CoachActionV1.model_validate(data)

    data = _example("coach-action.v1")
    data["source_correction_ids"] *= 2
    with pytest.raises(ValidationError, match="unique and sorted"):
        CoachActionV1.model_validate(data)


def test_coach_example_binds_the_exact_score_example() -> None:
    score = ScoreV1.model_validate(_example("score.v1"))
    action = CoachActionV1.model_validate(_example("coach-action.v1")).root
    known_corrections = {correction.correction_id for correction in score.corrections}

    assert action.source_score_sha256 == _canonical_digest(score)
    assert set(action.source_correction_ids) <= known_corrections
    assert action.tenant_id == score.tenant_id
    assert action.session_id == score.session_id
    assert action.phrase_id == score.phrase_id
    assert action.score_version == score.versions.score_version


def test_model_registry_schema_matches_source_and_starts_empty() -> None:
    committed_text = (REGISTRY_ROOT / "registry.schema.json").read_text(encoding="utf-8")
    assert committed_text == schema_text()
    registry = load_registry(REGISTRY_ROOT / "models.json")
    Draft202012Validator(
        json.loads(committed_text),
        format_checker=FormatChecker(),
    ).validate(registry.model_dump(mode="json"))
    assert registry.models == []


@pytest.mark.parametrize("review", ["pending", "rejected"])
def test_registry_rejects_commercial_model_without_training_approval(review: str) -> None:
    data = _model_record()
    data["training_data_review"] = review
    with pytest.raises(ValidationError, match="commercial models require"):
        ModelRegistryV1.model_validate({"schema_version": "model-registry.v1", "models": [data]})
    with pytest.raises(JsonSchemaError):
        Draft202012Validator(
            json.loads(schema_text()),
            format_checker=FormatChecker(),
        ).validate({"schema_version": "model-registry.v1", "models": [data]})


def test_registry_rejects_duplicate_model_ids() -> None:
    record = _model_record()
    with pytest.raises(ValidationError, match="model_id values must be unique"):
        ModelRegistryV1.model_validate(
            {"schema_version": "model-registry.v1", "models": [record, copy.deepcopy(record)]}
        )


def _example(schema_version: str) -> dict[str, object]:
    return json.loads((CONTRACTS_ROOT / "examples" / f"{schema_version}.json").read_text())


def _canonical_digest(model) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _model_record() -> dict[str, object]:
    return {
        "model_id": "f0.test-v1",
        "task": "f0",
        "artifact_sha256": "f" * 64,
        "source_url": "https://models.example.test/f0.test-v1.bin",
        "code_license_spdx": "MIT",
        "weight_license_spdx": "LicenseRef-Internal-Test",
        "training_data_review": "approved",
        "commercial_use_approved": True,
        "approved_by": "test-reviewer",
        "approved_at": "2026-07-11T04:00:00Z",
        "constraints": [],
    }

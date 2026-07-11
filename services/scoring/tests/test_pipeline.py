from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest
from music_ai_contracts.models import GateStatus
from music_ai_contracts.registry import ModelRegistryV1
from music_ai_model_runtime import ModelAuthorizer
from music_ai_scoring_service.pipeline import ScoringPipeline, ScoringTaskError
from music_ai_scoring_service.policy import DEFAULT_POLICY
from music_ai_scoring_service.serialization import canonical_model_bytes, sha256_hex
from music_ai_scoring_service.types import LeakageAnalysis
from scoring_service_testkit import (
    FixtureLeakageProvider,
    FixturePitchProvider,
    make_authorized_models,
    make_job,
    make_manifest,
    make_pipeline,
    make_transport,
)


def test_pipeline_builds_deterministic_evidence_bound_score(tmp_path: Path) -> None:
    job = make_job()
    pipeline, pitch, leakage = make_pipeline(tmp_path)

    first = pipeline.run(job)
    second = pipeline.run(job)

    assert first == second
    assert first.score.abstained_reason is None
    assert first.score.scored_coverage == 1.0
    assert first.score.user_features_sha256 == sha256_hex(canonical_model_bytes(first.features))
    assert (
        first.score.transport_evidence_sha256
        == first.features.transport_evidence_sha256
        == first.evidence[0].sha256
    )
    assert first.evidence[1].sha256 == first.score.user_features_sha256
    assert len(first.idempotency_key) == 64
    assert pitch.calls == 2
    assert leakage.calls == 2
    indices = [frame.sample_index for frame in first.features.frames]
    assert indices[0] == job.manifest.scorable_regions[0].start_sample
    assert all(current - previous == 480 for previous, current in pairwise(indices))
    assert first.evidence[1].model_release.startswith("model-set.")
    assert len(first.features.model_releases) == 2
    assert all("@sha256-" in release for release in first.features.model_releases)


def test_trusted_low_pitch_evidence_produces_abstention_not_task_failure(tmp_path: Path) -> None:
    authorizer, pitch_binding, leakage_binding = make_authorized_models(tmp_path)
    pitch = FixturePitchProvider(pitch_binding, voiced=False, confidence=0.0)
    leakage = FixtureLeakageProvider(leakage_binding, confidence=0.02)
    pipeline = ScoringPipeline(
        pitch_provider=pitch,
        leakage_provider=leakage,
        authorizer=authorizer,
    )

    result = pipeline.run(make_job())

    assert result.score.abstained_reason == "input.insufficient_pitch_confidence"
    assert result.score.scored_coverage == 0.0
    assert result.score.metrics == {}
    assert result.score.user_features_sha256 == result.evidence[1].sha256


def test_model_audio_and_transport_failures_publish_no_fake_score(tmp_path: Path) -> None:
    job = make_job()
    _, pitch_binding, leakage_binding = make_authorized_models(tmp_path / "empty")
    pitch = FixturePitchProvider(pitch_binding)
    leakage = FixtureLeakageProvider(leakage_binding)
    empty_pipeline = ScoringPipeline(
        pitch_provider=pitch,
        leakage_provider=leakage,
        authorizer=ModelAuthorizer(ModelRegistryV1(schema_version="model-registry.v1", models=[])),
    )
    with pytest.raises(ScoringTaskError) as unauthorized:
        empty_pipeline.run(job)
    assert unauthorized.value.code == "model.unauthorized"
    assert pitch.calls == 0
    assert leakage.calls == 0

    pipeline, pitch, leakage = make_pipeline(tmp_path / "integrity")
    corrupted = bytes([job.audio_payload[0] ^ 1]) + job.audio_payload[1:]
    corrupt_job = job.model_copy(update={"audio_payload": corrupted})
    with pytest.raises(ScoringTaskError) as integrity:
        pipeline.run(corrupt_job)
    assert integrity.value.code == "input.audio_integrity"
    assert pitch.calls == 0
    assert leakage.calls == 0

    pipeline, pitch, leakage = make_pipeline(tmp_path / "transport")
    drift_job = job.model_copy(update={"transport": make_transport(drift_ppm=1_001.0)})
    with pytest.raises(ScoringTaskError) as transport:
        pipeline.run(drift_job)
    assert transport.value.code == "input.transport"
    assert pitch.calls == 0
    assert leakage.calls == 0


def test_provider_timeline_mismatch_is_a_task_failure(tmp_path: Path) -> None:
    authorizer, pitch_binding, leakage_binding = make_authorized_models(tmp_path)
    pitch = FixturePitchProvider(pitch_binding)

    class ShortLeakageProvider(FixtureLeakageProvider):
        def analyze(self, audio, hop_samples, model):
            result = super().analyze(audio, hop_samples, model)
            return LeakageAnalysis(
                hop_samples=result.hop_samples,
                frames=result.frames[:-1],
            )

    pipeline = ScoringPipeline(
        pitch_provider=pitch,
        leakage_provider=ShortLeakageProvider(leakage_binding),
        authorizer=authorizer,
    )
    with pytest.raises(ScoringTaskError) as error:
        pipeline.run(make_job())
    assert error.value.code == "provider.invalid_output"


def test_non_scoring_manifest_returns_reference_abstention(tmp_path: Path) -> None:
    manifest = make_manifest(gate_status=GateStatus.PRACTICE_ONLY)
    job = make_job(manifest=manifest)
    pipeline, _, _ = make_pipeline(tmp_path)

    result = pipeline.run(job)

    assert result.score.abstained_reason == "reference.practice_only"
    assert result.score.user_features_sha256 == result.evidence[1].sha256


def test_unapproved_feature_policy_fails_before_provider_calls(tmp_path: Path) -> None:
    authorizer, pitch_binding, leakage_binding = make_authorized_models(tmp_path)
    pitch = FixturePitchProvider(pitch_binding)
    leakage = FixtureLeakageProvider(leakage_binding)
    pipeline = ScoringPipeline(
        pitch_provider=pitch,
        leakage_provider=leakage,
        authorizer=authorizer,
        policy=replace(DEFAULT_POLICY, hop_samples=240),
    )

    with pytest.raises(ScoringTaskError) as error:
        pipeline.run(make_job())
    assert error.value.code == "policy.unapproved"
    assert pitch.calls == 0
    assert leakage.calls == 0

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from ingest_testkit import (
    FixtureF0Provider,
    FixtureSeparationProvider,
    MemoryPublisher,
    make_analysis,
    make_authorized_models,
    make_job,
    make_pipeline,
    make_stems,
)
from music_ai_contracts.models import GateStatus, ReferenceF0V1, ReferenceSource
from music_ai_contracts.registry import ModelRegistryV1
from music_ai_ingest.model_gate import ModelAuthorizationError, ModelAuthorizer
from music_ai_ingest.pipeline import IngestPipeline, IngestPipelineError
from music_ai_ingest.policy import DEFAULT_POLICY, PolicyAuthorizationError
from music_ai_ingest.types import PublishedArtifact, RegionCandidate
from pydantic import ValidationError


def test_accepted_pipeline_is_byte_deterministic_and_idempotent(tmp_path: Path) -> None:
    job = make_job()
    pipeline, publisher, separation, f0 = make_pipeline(tmp_path, job=job)

    first = pipeline.run(job)
    second = pipeline.run(job)

    assert first == second
    assert first.manifest.gate_status == GateStatus.ACCEPTED
    assert first.manifest.reference_source == ReferenceSource.EXTRACTED_RECORDING
    assert first.manifest.scorable_vocal_coverage == 1.0
    assert len(first.manifest.scorable_regions) == 2
    assert len({region.region_id for region in first.manifest.scorable_regions}) == 2
    assert all(region.target_f0_hz == 440.0 for region in first.manifest.scorable_regions)
    assert all(artifact.kind != "notes" for artifact in first.manifest.artifacts)
    assert separation.calls == 2
    assert f0.calls == 2
    assert len(publisher.artifacts) == 3
    assert len(publisher.manifests) == 1

    f0_payload = next(
        payload for (_, kind, _), (_, payload) in publisher.artifacts.items() if kind == "f0"
    )
    track = ReferenceF0V1.model_validate_json(f0_payload)
    assert track.tenant_id == job.tenant_id
    assert track.song_id == job.song_id
    assert track.source_vocal_sha256 == first.artifacts[0].sha256
    assert track.vocal_presence_coverage == 0.6
    assert track.separation_confidence == 0.95
    assert track.accompaniment_leakage == 0.05
    assert len(track.candidates) == 2
    assert "@sha256-" in track.model_release
    assert all("@sha256-" in artifact.model_release for artifact in first.artifacts)
    assert track.model_release.endswith(hashlib.sha256(b"approved-f0-weights").hexdigest())
    assert first.artifacts[0].model_release.endswith(
        hashlib.sha256(b"approved-separation-weights").hexdigest()
    )
    assert f0_payload == json.dumps(
        track.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


@pytest.mark.parametrize(
    ("stem_overrides", "analysis_overrides", "expected_status", "expected_code"),
    [
        (
            {"vocal_presence_coverage": 0.0},
            {},
            GateStatus.REJECTED,
            "separation.no_vocal",
        ),
        (
            {"separation_confidence": 0.69},
            {},
            GateStatus.PRACTICE_ONLY,
            "separation.low_confidence",
        ),
        (
            {"accompaniment_leakage": 0.26},
            {},
            GateStatus.PRACTICE_ONLY,
            "separation.high_leakage",
        ),
        (
            {},
            {"reference_confidence": 0.79},
            GateStatus.PRACTICE_ONLY,
            "reference.insufficient_coverage",
        ),
        (
            {},
            {"monophonic_confidence": 0.79},
            GateStatus.PRACTICE_ONLY,
            "reference.insufficient_coverage",
        ),
        (
            {},
            {"ornament": True},
            GateStatus.PRACTICE_ONLY,
            "reference.insufficient_coverage",
        ),
        (
            {},
            {"candidates": []},
            GateStatus.PRACTICE_ONLY,
            "reference.no_regions",
        ),
    ],
)
def test_quality_gate_never_scores_unreliable_references(
    tmp_path: Path,
    stem_overrides: dict[str, float],
    analysis_overrides: dict[str, object],
    expected_status: GateStatus,
    expected_code: str,
) -> None:
    job = make_job()
    stems = make_stems(job, **stem_overrides)
    analysis = make_analysis(job, **analysis_overrides)
    pipeline, _, _, _ = make_pipeline(
        tmp_path,
        job=job,
        stems=stems,
        analysis=analysis,
    )

    result = pipeline.run(job)

    assert result.manifest.gate_status == expected_status
    assert result.manifest.scorable_vocal_coverage == 0.0
    assert result.manifest.scorable_regions == []
    assert expected_code in {issue.code for issue in result.manifest.quality_issues}
    assert all(issue.severity == "blocking" for issue in result.manifest.quality_issues)


def test_partial_but_sufficient_reference_is_accepted_with_warning(tmp_path: Path) -> None:
    job = make_job()
    analysis = make_analysis(
        job,
        candidates=[
            RegionCandidate(start_sample=4_800, end_sample=28_800),
            RegionCandidate(start_sample=28_800, end_sample=52_800, ornament=True),
        ],
    )
    pipeline, _, _, _ = make_pipeline(tmp_path, job=job, analysis=analysis)

    result = pipeline.run(job)

    assert result.manifest.gate_status == GateStatus.ACCEPTED
    assert result.manifest.scorable_vocal_coverage == 0.5
    assert len(result.manifest.scorable_regions) == 2
    assert {issue.code for issue in result.manifest.quality_issues} == {
        "reference.partial_coverage"
    }


def test_region_requires_sufficient_voiced_frame_coverage(tmp_path: Path) -> None:
    job = make_job()
    base = make_analysis(job)
    frames = []
    for frame in base.frames:
        in_candidate = 4_800 <= frame.sample_index < 52_800
        remove_voice = in_candidate and (frame.sample_index // base.hop_samples) % 2 == 0
        frames.append(
            frame.model_copy(update={"voiced": False, "f0_hz": None}) if remove_voice else frame
        )
    analysis = base.model_copy(update={"frames": frames})
    pipeline, _, _, _ = make_pipeline(tmp_path, job=job, analysis=analysis)

    result = pipeline.run(job)

    assert result.manifest.gate_status == GateStatus.PRACTICE_ONLY
    assert {issue.code for issue in result.manifest.quality_issues} == {
        "reference.insufficient_coverage"
    }


def test_quality_gate_includes_exact_threshold_boundaries(tmp_path: Path) -> None:
    job = make_job()
    candidate = RegionCandidate(start_sample=4_800, end_sample=9_600)
    base = make_analysis(
        job,
        candidates=[candidate],
        reference_confidence=0.80,
        monophonic_confidence=0.80,
    )
    candidate_indices = [
        index
        for index, frame in enumerate(base.frames)
        if candidate.start_sample <= frame.sample_index < candidate.end_sample
    ]
    frames = list(base.frames)
    for index in candidate_indices[:3]:
        frames[index] = frames[index].model_copy(update={"voiced": False, "f0_hz": None})
    analysis = base.model_copy(update={"frames": frames})
    stems = make_stems(
        job,
        vocal_presence_coverage=0.05,
        separation_confidence=0.70,
        accompaniment_leakage=0.25,
    )
    pipeline, _, _, _ = make_pipeline(
        tmp_path,
        job=job,
        stems=stems,
        analysis=analysis,
    )

    result = pipeline.run(job)

    assert len(candidate_indices) == 10
    assert result.manifest.gate_status == GateStatus.ACCEPTED
    assert result.manifest.scorable_vocal_coverage == 1.0
    assert len(result.manifest.scorable_regions) == 1


def test_exact_minimum_scorable_coverage_is_accepted(tmp_path: Path) -> None:
    job = make_job()
    analysis = make_analysis(
        job,
        candidates=[
            RegionCandidate(start_sample=4_800, end_sample=21_600),
            RegionCandidate(start_sample=21_600, end_sample=52_800, ornament=True),
        ],
    )
    pipeline, _, _, _ = make_pipeline(tmp_path, job=job, analysis=analysis)

    result = pipeline.run(job)

    assert result.manifest.gate_status == GateStatus.ACCEPTED
    assert result.manifest.scorable_vocal_coverage == 0.35


def test_pipeline_authorization_failure_calls_no_provider_or_publisher(tmp_path: Path) -> None:
    job = make_job()
    _, separation_binding, f0_binding, _ = make_authorized_models(tmp_path)
    separation = FixtureSeparationProvider(separation_binding, make_stems(job))
    f0 = FixtureF0Provider(f0_binding, make_analysis(job))
    publisher = MemoryPublisher()
    pipeline = IngestPipeline(
        separation_provider=separation,
        f0_provider=f0,
        authorizer=ModelAuthorizer(ModelRegistryV1(schema_version="model-registry.v1", models=[])),
        publisher=publisher,
    )

    with pytest.raises(ModelAuthorizationError, match="absent"):
        pipeline.run(job)
    assert separation.calls == 0
    assert f0.calls == 0
    assert publisher.artifacts == {}
    assert publisher.manifests == {}


def test_float_quantization_stabilizes_artifacts_and_regions(tmp_path: Path) -> None:
    job = make_job()
    first_pipeline, _, _, _ = make_pipeline(
        tmp_path / "first",
        job=job,
        analysis=make_analysis(job, f0_hz=440.0000001, reference_confidence=0.95000001),
    )
    second_pipeline, _, _, _ = make_pipeline(
        tmp_path / "second",
        job=job,
        analysis=make_analysis(job, f0_hz=440.0000002, reference_confidence=0.95000002),
    )

    first = first_pipeline.run(job)
    second = second_pipeline.run(job)

    assert first.manifest == second.manifest
    assert first.manifest_record_id == second.manifest_record_id
    assert first.artifacts == second.artifacts


def test_policy_changes_fail_closed_before_inference(tmp_path: Path) -> None:
    job = make_job()
    authorizer, separation_binding, f0_binding, _ = make_authorized_models(tmp_path)
    separation = FixtureSeparationProvider(separation_binding, make_stems(job))
    f0 = FixtureF0Provider(f0_binding, make_analysis(job))
    pipeline = IngestPipeline(
        separation_provider=separation,
        f0_provider=f0,
        authorizer=authorizer,
        publisher=MemoryPublisher(),
        policy=replace(DEFAULT_POLICY, min_separation_confidence=0.71),
    )

    with pytest.raises(PolicyAuthorizationError, match="fingerprint"):
        pipeline.run(job)
    assert separation.calls == 0
    assert f0.calls == 0


def test_provider_timeline_and_publisher_metadata_are_verified(tmp_path: Path) -> None:
    job = make_job()
    changed_timeline = make_stems(job).model_copy(
        update={"duration_samples": job.duration_samples + 1}
    )
    pipeline, _, _, _ = make_pipeline(tmp_path / "timeline", job=job, stems=changed_timeline)
    with pytest.raises(IngestPipelineError, match="separation changed"):
        pipeline.run(job)

    class MismatchedPublisher(MemoryPublisher):
        def publish_artifact(self, song_id, artifact):
            published = super().publish_artifact(song_id, artifact)
            return published.model_copy(update={"model_release": "wrong-model.v1"})

    pipeline, _, _, _ = make_pipeline(
        tmp_path / "publisher",
        job=job,
        publisher=MismatchedPublisher(),
    )
    with pytest.raises(IngestPipelineError, match="mismatched metadata"):
        pipeline.run(job)


def test_reference_analysis_rejects_gaps_overlaps_and_out_of_bounds() -> None:
    job = make_job()
    valid = make_analysis(job)

    frames = [frame.model_dump() for frame in valid.frames]
    frames.pop(1)
    with pytest.raises(ValidationError, match="contiguous"):
        valid.model_validate({**valid.model_dump(), "frames": frames})

    candidates = [
        RegionCandidate(start_sample=4_800, end_sample=28_800).model_dump(),
        RegionCandidate(start_sample=20_000, end_sample=40_000).model_dump(),
    ]
    with pytest.raises(ValidationError, match="must not overlap"):
        valid.model_validate({**valid.model_dump(), "candidates": candidates})

    candidates[-1] = {"start_sample": 90_000, "end_sample": 100_000, "ornament": False}
    with pytest.raises(ValidationError, match="within"):
        valid.model_validate({**valid.model_dump(), "candidates": candidates[-1:]})


def test_ingest_job_rejects_tampered_source_payload() -> None:
    job = make_job()
    with pytest.raises(ValidationError, match="source payload SHA-256"):
        job.model_copy(update={"source_payload": b"tampered"}).model_validate(
            {**job.model_dump(), "source_payload": b"tampered"}
        )


def test_publisher_result_model_cannot_hide_invalid_hash() -> None:
    with pytest.raises(ValidationError):
        PublishedArtifact(
            artifact_id="55555555-5555-4555-8555-555555555555",
            kind="f0",
            sha256="not-a-sha",
            model_release="f0.v1",
        )

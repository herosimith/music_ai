from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from music_ai_contracts.models import ReferenceF0Frame, SongManifestV1
from music_ai_contracts.registry import (
    ModelRecord,
    ModelRegistryV1,
    ModelTask,
    TrainingDataReview,
)
from music_ai_ingest.artifacts import canonical_model_bytes, sha256_hex
from music_ai_ingest.model_gate import AuthorizedModel, ModelAuthorizer
from music_ai_ingest.pipeline import IngestPipeline
from music_ai_ingest.providers import ModelBinding
from music_ai_ingest.types import (
    ArtifactBlob,
    IngestJob,
    PublishedArtifact,
    ReferenceAnalysis,
    RegionCandidate,
    StemResult,
)

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
SONG_ID = UUID("44444444-4444-4444-8444-444444444444")
PRODUCED_AT = datetime(2026, 7, 11, 7, 0, tzinfo=UTC)
SAMPLE_RATE = 48_000
DURATION_SAMPLES = 96_000
HOP_SAMPLES = 480
SOURCE_PAYLOAD = b"synthetic authorized song source"


def make_job(
    *,
    tenant_id: UUID = TENANT_ID,
    song_id: UUID = SONG_ID,
    produced_at: datetime = PRODUCED_AT,
) -> IngestJob:
    return IngestJob(
        tenant_id=tenant_id,
        song_id=song_id,
        rights_basis="Synthetic test fixture",
        source_sha256=sha256_hex(SOURCE_PAYLOAD),
        source_media_type="audio/wav",
        source_payload=SOURCE_PAYLOAD,
        sample_rate=SAMPLE_RATE,
        duration_samples=DURATION_SAMPLES,
        calibration_version="calibration.test.v1",
        produced_at=produced_at,
    )


def make_stems(
    job: IngestJob,
    *,
    vocal_presence_coverage: float = 0.60,
    separation_confidence: float = 0.95,
    accompaniment_leakage: float = 0.05,
) -> StemResult:
    return StemResult(
        vocal_wav=b"RIFF-test-vocal-stem",
        accompaniment_wav=b"RIFF-test-accompaniment-stem",
        sample_rate=job.sample_rate,
        duration_samples=job.duration_samples,
        vocal_presence_coverage=vocal_presence_coverage,
        separation_confidence=separation_confidence,
        accompaniment_leakage=accompaniment_leakage,
    )


def make_analysis(
    job: IngestJob,
    *,
    reference_confidence: float = 0.96,
    monophonic_confidence: float = 0.95,
    ornament: bool = False,
    candidates: list[RegionCandidate] | None = None,
    f0_hz: float = 440.0,
) -> ReferenceAnalysis:
    selected = candidates
    if selected is None:
        selected = [
            RegionCandidate(start_sample=4_800, end_sample=28_800, ornament=ornament),
            RegionCandidate(start_sample=28_800, end_sample=52_800, ornament=ornament),
        ]
    frames: list[ReferenceF0Frame] = []
    for sample_index in range(0, job.duration_samples, HOP_SAMPLES):
        voiced = any(
            candidate.start_sample <= sample_index < candidate.end_sample for candidate in selected
        )
        frames.append(
            ReferenceF0Frame(
                sample_index=sample_index,
                voiced=voiced,
                f0_hz=f0_hz if voiced else None,
                f0_confidence=reference_confidence if voiced else 0.0,
                monophonic_confidence=monophonic_confidence,
            )
        )
    return ReferenceAnalysis(
        sample_rate=job.sample_rate,
        duration_samples=job.duration_samples,
        hop_samples=HOP_SAMPLES,
        frames=frames,
        candidates=selected,
    )


class FixtureSeparationProvider:
    def __init__(self, binding: ModelBinding, result: StemResult | None = None) -> None:
        self.binding = binding
        self.result = result
        self.calls = 0

    def separate(self, job: IngestJob, model: AuthorizedModel) -> StemResult:
        assert model.record.model_id == self.binding.model_id
        self.calls += 1
        return self.result or make_stems(job)


class FixtureF0Provider:
    def __init__(self, binding: ModelBinding, result: ReferenceAnalysis | None = None) -> None:
        self.binding = binding
        self.result = result
        self.calls = 0

    def analyze(
        self,
        vocal_wav: bytes,
        sample_rate: int,
        duration_samples: int,
        model: AuthorizedModel,
    ) -> ReferenceAnalysis:
        assert vocal_wav
        assert model.record.model_id == self.binding.model_id
        self.calls += 1
        if self.result is not None:
            return self.result
        job = make_job()
        return make_analysis(
            job.model_copy(
                update={"sample_rate": sample_rate, "duration_samples": duration_samples}
            )
        )


class MemoryPublisher:
    def __init__(self) -> None:
        self.artifacts: dict[tuple[UUID, str, str], tuple[PublishedArtifact, bytes]] = {}
        self.manifests: dict[str, tuple[UUID, SongManifestV1]] = {}

    def publish_artifact(self, song_id: UUID, artifact: ArtifactBlob) -> PublishedArtifact:
        key = (song_id, artifact.kind, artifact.sha256)
        existing = self.artifacts.get(key)
        if existing is not None:
            return existing[0]
        identity = f"music-ai-test-asset:{song_id}:{artifact.kind}:{artifact.sha256}"
        artifact_id = uuid5(NAMESPACE_URL, identity)
        published = PublishedArtifact(
            artifact_id=artifact_id,
            kind=artifact.kind,
            sha256=artifact.sha256,
            model_release=artifact.model_release,
        )
        self.artifacts[key] = (published, artifact.payload)
        return published

    def publish_manifest(self, song_id: UUID, manifest: SongManifestV1) -> UUID:
        payload = canonical_model_bytes(manifest)
        digest = sha256_hex(payload)
        existing = self.manifests.get(digest)
        if existing is not None:
            return existing[0]
        record_id = uuid5(NAMESPACE_URL, f"music-ai-test-manifest:{song_id}:{digest}")
        self.manifests[digest] = (record_id, manifest)
        return record_id


def make_authorized_models(
    tmp_path: Path,
    *,
    constraints: tuple[str, ...] = (),
) -> tuple[ModelAuthorizer, ModelBinding, ModelBinding, ModelRegistryV1]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    separation_path = tmp_path / "separation.weights"
    f0_path = tmp_path / "f0.weights"
    separation_path.write_bytes(b"approved-separation-weights")
    f0_path.write_bytes(b"approved-f0-weights")
    records = [
        _record(
            "separator.test.v1",
            ModelTask.SOURCE_SEPARATION,
            separation_path,
            constraints,
        ),
        _record("reference-f0.test.v1", ModelTask.F0, f0_path, constraints),
    ]
    registry = ModelRegistryV1(schema_version="model-registry.v1", models=records)
    authorizer = ModelAuthorizer(registry, satisfied_constraints=frozenset(constraints))
    return (
        authorizer,
        ModelBinding("separator.test.v1", ModelTask.SOURCE_SEPARATION, separation_path),
        ModelBinding("reference-f0.test.v1", ModelTask.F0, f0_path),
        registry,
    )


def make_pipeline(
    tmp_path: Path,
    *,
    job: IngestJob | None = None,
    stems: StemResult | None = None,
    analysis: ReferenceAnalysis | None = None,
    publisher: MemoryPublisher | None = None,
) -> tuple[IngestPipeline, MemoryPublisher, FixtureSeparationProvider, FixtureF0Provider]:
    selected_job = job or make_job()
    authorizer, separation_binding, f0_binding, _ = make_authorized_models(tmp_path)
    separation = FixtureSeparationProvider(
        separation_binding,
        stems or make_stems(selected_job),
    )
    f0 = FixtureF0Provider(f0_binding, analysis or make_analysis(selected_job))
    selected_publisher = publisher or MemoryPublisher()
    return (
        IngestPipeline(
            separation_provider=separation,
            f0_provider=f0,
            authorizer=authorizer,
            publisher=selected_publisher,
        ),
        selected_publisher,
        separation,
        f0,
    )


def _record(
    model_id: str,
    task: ModelTask,
    path: Path,
    constraints: tuple[str, ...],
) -> ModelRecord:
    return ModelRecord(
        model_id=model_id,
        task=task,
        artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_url=f"https://models.example.test/{path.name}",
        code_license_spdx="MIT",
        weight_license_spdx="LicenseRef-Internal-Test",
        training_data_review=TrainingDataReview.APPROVED,
        commercial_use_approved=True,
        approved_by="test-reviewer",
        approved_at=PRODUCED_AT,
        constraints=list(constraints),
    )

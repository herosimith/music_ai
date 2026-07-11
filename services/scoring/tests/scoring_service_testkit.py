from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from music_ai_contracts.models import (
    ArtifactPointer,
    GateStatus,
    PhraseAudioV1,
    ReferenceSource,
    ScorableRegion,
    SongManifestV1,
    TransportEvidenceV1,
    TransportSyncV1,
    VersionStamp,
)
from music_ai_contracts.registry import (
    ModelRecord,
    ModelRegistryV1,
    ModelTask,
    TrainingDataReview,
)
from music_ai_model_runtime import AuthorizedModel, ModelAuthorizer, ModelBinding
from music_ai_scoring_service.pipeline import ScoringPipeline
from music_ai_scoring_service.providers import LeakageProvider, PitchProvider
from music_ai_scoring_service.types import (
    DecodedPhrase,
    LeakageAnalysis,
    LeakageFrame,
    PitchAnalysis,
    PitchFrame,
    ScoringJob,
)

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
SESSION_ID = UUID("22222222-2222-4222-8222-222222222222")
PHRASE_ID = UUID("33333333-3333-4333-8333-333333333333")
SONG_ID = UUID("44444444-4444-4444-8444-444444444444")
MANIFEST_ID = UUID("55555555-5555-4555-8555-555555555555")
SAMPLE_RATE = 48_000
HOP_SAMPLES = 480
PHRASE_START = 240_000
PHRASE_END = 288_000
REFERENCE_START = 864_000
REFERENCE_END = 912_000
CAPTURED_AT = datetime(2026, 7, 11, 4, 0, 5, tzinfo=UTC)
PRODUCED_AT = datetime(2026, 7, 11, 4, 0, 7, tzinfo=UTC)


def pcm_payload(*, amplitude: int = 8_000) -> bytes:
    samples = [
        round(amplitude * math.sin(2 * math.pi * 440 * index / SAMPLE_RATE))
        for index in range(PHRASE_END - PHRASE_START)
    ]
    return struct.pack(f"<{len(samples)}h", *samples)


def wav_payload(
    pcm: bytes | None = None,
    *,
    channels: int = 1,
    sample_rate: int = SAMPLE_RATE,
) -> bytes:
    selected = pcm or pcm_payload()
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as target:
            target.setnchannels(channels)
            target.setsampwidth(2)
            target.setframerate(sample_rate)
            target.writeframes(selected)
        return buffer.getvalue()


def make_phrase(
    payload: bytes | None = None,
    *,
    codec: str = "pcm_s16le",
    tenant_id: UUID = TENANT_ID,
    session_id: UUID = SESSION_ID,
    phrase_id: UUID = PHRASE_ID,
) -> tuple[PhraseAudioV1, bytes]:
    selected = payload or (pcm_payload() if codec == "pcm_s16le" else wav_payload())
    return (
        PhraseAudioV1(
            schema_version="phrase-audio.v1",
            tenant_id=tenant_id,
            session_id=session_id,
            phrase_id=phrase_id,
            sequence=0,
            sample_start=PHRASE_START,
            sample_end=PHRASE_END,
            sample_rate=SAMPLE_RATE,
            channels=1,
            codec=codec,
            sha256=hashlib.sha256(selected).hexdigest(),
            byte_length=len(selected),
            calibration_version="calibration.test.v1",
            captured_at=CAPTURED_AT,
            idempotency_key="phrase-idempotency-0123456789",
        ),
        selected,
    )


def make_manifest(
    *,
    tenant_id: UUID = TENANT_ID,
    song_id: UUID = SONG_ID,
    gate_status: GateStatus = GateStatus.ACCEPTED,
    artifacts: list[ArtifactPointer] | None = None,
) -> SongManifestV1:
    regions = (
        [
            ScorableRegion(
                region_id="phrase-region-01",
                start_sample=REFERENCE_START,
                end_sample=REFERENCE_END,
                target_f0_hz=440.0,
                reference_confidence=0.98,
                monophonic_confidence=0.97,
                ornament=False,
            )
        ]
        if gate_status == GateStatus.ACCEPTED
        else []
    )
    selected_artifacts = artifacts or [
        ArtifactPointer(
            artifact_id=f"song-source:{song_id}",
            kind="source",
            sha256="a" * 64,
        ),
        ArtifactPointer(
            artifact_id="66666666-6666-4666-8666-666666666666",
            kind="vocal",
            sha256="b" * 64,
            model_release="separator.test.v1",
        ),
        ArtifactPointer(
            artifact_id="77777777-7777-4777-8777-777777777777",
            kind="f0",
            sha256="c" * 64,
            model_release="reference-f0.test.v1",
        ),
    ]
    return SongManifestV1(
        schema_version="song-manifest.v1",
        tenant_id=tenant_id,
        song_id=song_id,
        reference_source=ReferenceSource.EXTRACTED_RECORDING,
        rights_basis="Synthetic test fixture",
        source_sha256=selected_artifacts[0].sha256,
        sample_rate=SAMPLE_RATE,
        duration_samples=1_440_000,
        gate_status=gate_status,
        scorable_vocal_coverage=1.0 if regions else 0.0,
        quality_issues=[],
        artifacts=selected_artifacts,
        scorable_regions=regions,
        versions=VersionStamp(
            pipeline_version="ingest.test.v1",
            model_release="reference-model-set.test.v1",
            score_version="score.v1",
            calibration_version="calibration.test.v1",
        ),
        produced_at=CAPTURED_AT - timedelta(seconds=1),
    )


def make_transport(
    *,
    tenant_id: UUID = TENANT_ID,
    session_id: UUID = SESSION_ID,
    phrase_id: UUID = PHRASE_ID,
    drift_ppm: float = 0.0,
    events: list[TransportSyncV1] | None = None,
) -> TransportEvidenceV1:
    selected = events or [
        TransportSyncV1(
            schema_version="transport.v1",
            tenant_id=tenant_id,
            session_id=session_id,
            seq=10,
            revision=0,
            captured_at=CAPTURED_AT - timedelta(seconds=1),
            playhead_samples=REFERENCE_START,
            microphone_sample_index=PHRASE_START,
            sample_rate=SAMPLE_RATE,
            drift_ppm=drift_ppm,
        ),
        TransportSyncV1(
            schema_version="transport.v1",
            tenant_id=tenant_id,
            session_id=session_id,
            seq=11,
            revision=0,
            captured_at=CAPTURED_AT,
            playhead_samples=REFERENCE_END,
            microphone_sample_index=PHRASE_END,
            sample_rate=SAMPLE_RATE,
            drift_ppm=drift_ppm,
        ),
    ]
    return TransportEvidenceV1(
        schema_version="transport-evidence.v1",
        tenant_id=tenant_id,
        session_id=session_id,
        phrase_id=phrase_id,
        calibration_version="calibration.test.v1",
        events=selected,
        produced_at=CAPTURED_AT + timedelta(seconds=1),
    )


def make_job(
    *,
    phrase: PhraseAudioV1 | None = None,
    payload: bytes | None = None,
    manifest: SongManifestV1 | None = None,
    transport: TransportEvidenceV1 | None = None,
    manifest_record_id: UUID = MANIFEST_ID,
) -> ScoringJob:
    if phrase is None:
        selected_phrase, generated_payload = make_phrase()
        selected_payload = generated_payload if payload is None else payload
    else:
        if payload is None:
            raise ValueError("custom phrase fixtures require their exact audio payload")
        selected_phrase = phrase
        selected_payload = payload
    selected_manifest = manifest or make_manifest(tenant_id=selected_phrase.tenant_id)
    return ScoringJob(
        phrase=selected_phrase,
        audio_payload=selected_payload,
        transport=transport
        or make_transport(
            tenant_id=selected_phrase.tenant_id,
            session_id=selected_phrase.session_id,
            phrase_id=selected_phrase.phrase_id,
        ),
        manifest=selected_manifest,
        manifest_record_id=manifest_record_id,
        region_ids=(
            [selected_manifest.scorable_regions[0].region_id]
            if selected_manifest.gate_status == GateStatus.ACCEPTED
            else None
        ),
        produced_at=PRODUCED_AT,
    )


class FixturePitchProvider(PitchProvider):
    def __init__(
        self,
        binding: ModelBinding,
        *,
        voiced: bool = True,
        f0_hz: float = 440.0,
        confidence: float = 0.99,
    ) -> None:
        self.binding = binding
        self.voiced = voiced
        self.f0_hz = f0_hz
        self.confidence = confidence
        self.calls = 0

    def analyze(
        self,
        audio: DecodedPhrase,
        hop_samples: int,
        model: AuthorizedModel,
    ) -> PitchAnalysis:
        assert model.record.model_id == self.binding.model_id
        self.calls += 1
        return PitchAnalysis(
            hop_samples=hop_samples,
            frames=[
                PitchFrame(
                    offset_samples=offset,
                    voiced=self.voiced,
                    f0_hz=self.f0_hz if self.voiced else None,
                    f0_confidence=self.confidence,
                )
                for offset in range(0, audio.frame_count - hop_samples + 1, hop_samples)
            ],
        )


class FixtureLeakageProvider(LeakageProvider):
    def __init__(self, binding: ModelBinding, *, confidence: float = 0.02) -> None:
        self.binding = binding
        self.confidence = confidence
        self.calls = 0

    def analyze(
        self,
        audio: DecodedPhrase,
        hop_samples: int,
        model: AuthorizedModel,
    ) -> LeakageAnalysis:
        assert model.record.model_id == self.binding.model_id
        self.calls += 1
        return LeakageAnalysis(
            hop_samples=hop_samples,
            frames=[
                LeakageFrame(offset_samples=offset, leakage_confidence=self.confidence)
                for offset in range(0, audio.frame_count - hop_samples + 1, hop_samples)
            ],
        )


def make_authorized_models(
    tmp_path: Path,
) -> tuple[ModelAuthorizer, ModelBinding, ModelBinding]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    pitch_path = tmp_path / "pitch.weights"
    leakage_path = tmp_path / "leakage.weights"
    pitch_path.write_bytes(b"approved-pitch-weights")
    leakage_path.write_bytes(b"approved-leakage-weights")
    records = [
        _record("user-f0.test.v1", ModelTask.F0, pitch_path),
        _record("leakage.test.v1", ModelTask.QUALITY_GATE, leakage_path),
    ]
    registry = ModelRegistryV1(schema_version="model-registry.v1", models=records)
    return (
        ModelAuthorizer(registry),
        ModelBinding(records[0].model_id, ModelTask.F0, pitch_path),
        ModelBinding(records[1].model_id, ModelTask.QUALITY_GATE, leakage_path),
    )


def make_pipeline(
    tmp_path: Path,
    *,
    pitch_provider: FixturePitchProvider | None = None,
    leakage_provider: FixtureLeakageProvider | None = None,
) -> tuple[ScoringPipeline, FixturePitchProvider, FixtureLeakageProvider]:
    authorizer, pitch_binding, leakage_binding = make_authorized_models(tmp_path)
    pitch = pitch_provider or FixturePitchProvider(pitch_binding)
    leakage = leakage_provider or FixtureLeakageProvider(leakage_binding)
    return (
        ScoringPipeline(
            pitch_provider=pitch,
            leakage_provider=leakage,
            authorizer=authorizer,
        ),
        pitch,
        leakage,
    )


def _record(model_id: str, task: ModelTask, path: Path) -> ModelRecord:
    return ModelRecord(
        model_id=model_id,
        task=task,
        artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_url=f"https://models.example.test/{path.name}",
        code_license_spdx="MIT",
        weight_license_spdx="LicenseRef-Test",
        training_data_review=TrainingDataReview.APPROVED,
        commercial_use_approved=True,
        approved_by="test-reviewer",
        approved_at=CAPTURED_AT,
        constraints=[],
    )

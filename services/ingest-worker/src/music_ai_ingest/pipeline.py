from __future__ import annotations

import math
import statistics
from uuid import UUID

from music_ai_contracts.models import (
    ArtifactPointer,
    GateStatus,
    QualityIssue,
    ReferenceF0Frame,
    ReferenceF0V1,
    ReferenceSource,
    ScorableRegion,
    SongManifestV1,
    VersionStamp,
)
from music_ai_contracts.registry import ModelTask

from music_ai_ingest.artifacts import (
    bound_model_release,
    canonical_model_bytes,
    model_set_release,
    quantize,
    region_id,
    sha256_hex,
)
from music_ai_ingest.model_gate import ModelAuthorizer
from music_ai_ingest.policy import DEFAULT_POLICY, IngestPolicy, require_approved_policy
from music_ai_ingest.providers import ReferenceF0Provider, SeparationProvider
from music_ai_ingest.publisher import ArtifactPublisher
from music_ai_ingest.types import (
    ArtifactBlob,
    GateOutcome,
    IngestJob,
    IngestResult,
    PublishedArtifact,
    ReferenceAnalysis,
    StemResult,
)


class IngestPipelineError(RuntimeError):
    pass


class IngestPipeline:
    def __init__(
        self,
        *,
        separation_provider: SeparationProvider,
        f0_provider: ReferenceF0Provider,
        authorizer: ModelAuthorizer,
        publisher: ArtifactPublisher,
        policy: IngestPolicy = DEFAULT_POLICY,
    ) -> None:
        self.separation_provider = separation_provider
        self.f0_provider = f0_provider
        self.authorizer = authorizer
        self.publisher = publisher
        self.policy = policy

    def run(self, job: IngestJob) -> IngestResult:
        require_approved_policy(self.policy)
        separation_model = self.authorizer.authorize(
            self.separation_provider.binding,
            ModelTask.SOURCE_SEPARATION,
        )
        f0_model = self.authorizer.authorize(
            self.f0_provider.binding,
            ModelTask.F0,
        )
        stem_result = StemResult.model_validate(
            self.separation_provider.separate(job, separation_model)
        )
        self._require_matching_timeline(
            job.sample_rate,
            job.duration_samples,
            stem_result.sample_rate,
            stem_result.duration_samples,
            "separation",
        )
        analysis = ReferenceAnalysis.model_validate(
            self.f0_provider.analyze(
                stem_result.vocal_wav,
                stem_result.sample_rate,
                stem_result.duration_samples,
                f0_model,
            )
        )
        self._require_matching_timeline(
            job.sample_rate,
            job.duration_samples,
            analysis.sample_rate,
            analysis.duration_samples,
            "reference F0",
        )

        separation_release = bound_model_release(
            separation_model.record.model_id,
            separation_model.record.artifact_sha256,
        )
        f0_release = bound_model_release(
            f0_model.record.model_id,
            f0_model.record.artifact_sha256,
        )
        model_release = model_set_release(separation_release, f0_release)
        normalized_frames = [
            ReferenceF0Frame(
                sample_index=frame.sample_index,
                voiced=frame.voiced,
                f0_hz=quantize(frame.f0_hz) if frame.f0_hz is not None else None,
                f0_confidence=quantize(frame.f0_confidence),
                monophonic_confidence=quantize(frame.monophonic_confidence),
            )
            for frame in analysis.frames
        ]
        vocal_sha256 = sha256_hex(stem_result.vocal_wav)
        reference_track = ReferenceF0V1(
            schema_version="reference-f0.v1",
            tenant_id=job.tenant_id,
            song_id=job.song_id,
            sample_rate=job.sample_rate,
            duration_samples=job.duration_samples,
            hop_samples=analysis.hop_samples,
            source_vocal_sha256=vocal_sha256,
            pipeline_version=self.policy.pipeline_version,
            model_release=f0_release,
            vocal_presence_coverage=quantize(stem_result.vocal_presence_coverage),
            separation_confidence=quantize(stem_result.separation_confidence),
            accompaniment_leakage=quantize(stem_result.accompaniment_leakage),
            frames=normalized_frames,
            candidates=analysis.candidates,
            produced_at=job.produced_at,
        )
        f0_payload = canonical_model_bytes(reference_track)
        f0_sha256 = sha256_hex(f0_payload)
        gate = self._gate(
            job,
            stem_result,
            analysis,
            normalized_frames,
            f0_sha256,
            model_release,
        )

        blobs = [
            ArtifactBlob(
                kind="vocal",
                media_type="audio/wav",
                payload=stem_result.vocal_wav,
                model_release=separation_release,
                sha256=vocal_sha256,
            ),
            ArtifactBlob(
                kind="accompaniment",
                media_type="audio/wav",
                payload=stem_result.accompaniment_wav,
                model_release=separation_release,
                sha256=sha256_hex(stem_result.accompaniment_wav),
            ),
            ArtifactBlob(
                kind="f0",
                media_type="application/json",
                payload=f0_payload,
                model_release=f0_release,
                sha256=f0_sha256,
            ),
        ]
        published = [self._publish_verified(job.song_id, blob) for blob in blobs]
        artifacts = [
            ArtifactPointer(
                artifact_id=f"song-source:{job.song_id}",
                kind="source",
                sha256=job.source_sha256,
            ),
            *(artifact.pointer() for artifact in published),
        ]
        manifest = SongManifestV1(
            schema_version="song-manifest.v1",
            tenant_id=job.tenant_id,
            song_id=job.song_id,
            reference_source=ReferenceSource.EXTRACTED_RECORDING,
            rights_basis=job.rights_basis,
            source_sha256=job.source_sha256,
            sample_rate=job.sample_rate,
            duration_samples=job.duration_samples,
            gate_status=gate.status,
            scorable_vocal_coverage=gate.coverage,
            quality_issues=gate.issues,
            artifacts=artifacts,
            scorable_regions=gate.regions,
            versions=VersionStamp(
                pipeline_version=self.policy.pipeline_version,
                model_release=model_release,
                score_version=self.policy.score_version,
                calibration_version=job.calibration_version,
            ),
            produced_at=job.produced_at,
        )
        if manifest.reference_source == ReferenceSource.CANONICAL_NOTES or any(
            artifact.kind == "notes" for artifact in manifest.artifacts
        ):
            raise IngestPipelineError("extracted recordings cannot claim canonical notation")
        manifest_record_id = self.publisher.publish_manifest(job.song_id, manifest)
        return IngestResult(
            manifest_record_id=manifest_record_id,
            manifest=manifest,
            artifacts=published,
        )

    def _gate(
        self,
        job: IngestJob,
        stems: StemResult,
        analysis: ReferenceAnalysis,
        frames: list[ReferenceF0Frame],
        reference_sha256: str,
        model_release: str,
    ) -> GateOutcome:
        if stems.vocal_presence_coverage < self.policy.min_vocal_presence_coverage:
            return GateOutcome(
                status=GateStatus.REJECTED,
                coverage=0.0,
                issues=[_issue("separation.no_vocal", "blocking")],
                regions=[],
            )

        policy_fingerprint = self.policy.fingerprint()
        minimum_samples = math.ceil(self.policy.min_region_duration_ms * job.sample_rate / 1_000)
        total_candidate_samples = sum(
            candidate.end_sample - candidate.start_sample for candidate in analysis.candidates
        )
        regions: list[ScorableRegion] = []
        eligible_samples = 0
        excluded_regions = 0
        for candidate in analysis.candidates:
            candidate_frames = [
                frame
                for frame in frames
                if candidate.start_sample <= frame.sample_index < candidate.end_sample
            ]
            voiced_frames = [
                frame for frame in candidate_frames if frame.voiced and frame.f0_hz is not None
            ]
            voiced_coverage = (
                len(voiced_frames) / len(candidate_frames) if candidate_frames else 0.0
            )
            duration = candidate.end_sample - candidate.start_sample
            if duration < minimum_samples or not candidate_frames or not voiced_frames:
                excluded_regions += 1
                continue
            reference_confidence = quantize(
                statistics.median(frame.f0_confidence for frame in candidate_frames)
            )
            monophonic_confidence = quantize(
                statistics.median(frame.monophonic_confidence for frame in candidate_frames)
            )
            target_f0_hz = quantize(
                statistics.median(frame.f0_hz for frame in voiced_frames if frame.f0_hz is not None)
            )
            region = ScorableRegion(
                region_id=region_id(
                    song_id=job.song_id,
                    source_sha256=job.source_sha256,
                    reference_sha256=reference_sha256,
                    model_release=model_release,
                    policy_fingerprint=policy_fingerprint,
                    start_sample=candidate.start_sample,
                    end_sample=candidate.end_sample,
                    ornament=candidate.ornament,
                ),
                start_sample=candidate.start_sample,
                end_sample=candidate.end_sample,
                target_f0_hz=target_f0_hz,
                reference_confidence=reference_confidence,
                monophonic_confidence=monophonic_confidence,
                ornament=candidate.ornament,
            )
            regions.append(region)
            if (
                reference_confidence >= self.policy.min_reference_confidence
                and monophonic_confidence >= self.policy.min_monophonic_confidence
                and voiced_coverage >= self.policy.min_region_voiced_coverage
                and not candidate.ornament
            ):
                eligible_samples += duration

        coverage = (
            quantize(eligible_samples / total_candidate_samples)
            if total_candidate_samples > 0
            else 0.0
        )
        blocking: list[QualityIssue] = []
        if stems.separation_confidence < self.policy.min_separation_confidence:
            blocking.append(_issue("separation.low_confidence", "blocking"))
        if stems.accompaniment_leakage > self.policy.max_accompaniment_leakage:
            blocking.append(_issue("separation.high_leakage", "blocking"))
        if not regions:
            blocking.append(_issue("reference.no_regions", "blocking"))
        elif coverage < self.policy.min_scorable_vocal_coverage:
            blocking.append(_issue("reference.insufficient_coverage", "blocking"))
        if blocking:
            return GateOutcome(
                status=GateStatus.PRACTICE_ONLY,
                coverage=0.0,
                issues=blocking,
                regions=[],
            )

        warnings: list[QualityIssue] = []
        if excluded_regions or coverage < 1.0:
            warnings.append(_issue("reference.partial_coverage", "warning"))
        return GateOutcome(
            status=GateStatus.ACCEPTED,
            coverage=coverage,
            issues=warnings,
            regions=regions,
        )

    def _publish_verified(self, song_id: UUID, blob: ArtifactBlob) -> PublishedArtifact:
        published = self.publisher.publish_artifact(song_id, blob)
        if (
            published.kind != blob.kind
            or published.sha256 != blob.sha256
            or published.model_release != blob.model_release
        ):
            raise IngestPipelineError("artifact publisher returned mismatched metadata")
        return published

    @staticmethod
    def _require_matching_timeline(
        expected_sample_rate: int,
        expected_duration: int,
        actual_sample_rate: int,
        actual_duration: int,
        stage: str,
    ) -> None:
        if actual_sample_rate != expected_sample_rate or actual_duration != expected_duration:
            raise IngestPipelineError(f"{stage} changed the reference timeline")


def _issue(code: str, severity: str) -> QualityIssue:
    return QualityIssue(
        code=code,
        severity=severity,
        message_key=f"ingest.{code}",
        evidence=[],
    )

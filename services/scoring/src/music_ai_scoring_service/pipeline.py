from __future__ import annotations

import hashlib
import json

from music_ai_contracts.models import UserFeatureFrame, UserFeaturesV1, VersionStamp
from music_ai_contracts.registry import ModelTask
from music_ai_model_runtime import (
    ModelAuthorizationError,
    ModelAuthorizer,
    bound_model_release,
    model_set_release,
)
from music_ai_scoring import ScoringInvariantError, score_phrase

from music_ai_scoring_service.audio import AudioIntegrityError, decode_phrase_audio, energy_dbfs
from music_ai_scoring_service.calibration import TransportCalibrationError, calibrate_phrase
from music_ai_scoring_service.policy import (
    DEFAULT_POLICY,
    FeaturePolicy,
    FeaturePolicyAuthorizationError,
    require_approved_policy,
)
from music_ai_scoring_service.providers import LeakageProvider, PitchProvider
from music_ai_scoring_service.serialization import canonical_model_bytes, quantize, sha256_hex
from music_ai_scoring_service.types import (
    EvidenceBlob,
    LeakageAnalysis,
    PitchAnalysis,
    ScoringComputation,
    ScoringJob,
)


class ScoringTaskError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ScoringPipeline:
    def __init__(
        self,
        *,
        pitch_provider: PitchProvider,
        leakage_provider: LeakageProvider,
        authorizer: ModelAuthorizer,
        policy: FeaturePolicy = DEFAULT_POLICY,
    ) -> None:
        self.pitch_provider = pitch_provider
        self.leakage_provider = leakage_provider
        self.authorizer = authorizer
        self.policy = policy

    def run(self, job: ScoringJob) -> ScoringComputation:
        try:
            require_approved_policy(self.policy)
        except FeaturePolicyAuthorizationError as error:
            raise ScoringTaskError("policy.unapproved", str(error)) from error
        try:
            pitch_model = self.authorizer.authorize(
                self.pitch_provider.binding,
                ModelTask.F0,
            )
            leakage_model = self.authorizer.authorize(
                self.leakage_provider.binding,
                ModelTask.QUALITY_GATE,
            )
        except ModelAuthorizationError as error:
            raise ScoringTaskError("model.unauthorized", str(error)) from error

        try:
            audio = decode_phrase_audio(job.phrase, job.audio_payload)
        except AudioIntegrityError as error:
            raise ScoringTaskError("input.audio_integrity", str(error)) from error
        try:
            calibration = calibrate_phrase(job.phrase, job.transport, self.policy)
        except TransportCalibrationError as error:
            raise ScoringTaskError("input.transport", str(error)) from error

        try:
            pitch = PitchAnalysis.model_validate(
                self.pitch_provider.analyze(audio, self.policy.hop_samples, pitch_model)
            )
            leakage = LeakageAnalysis.model_validate(
                self.leakage_provider.analyze(audio, self.policy.hop_samples, leakage_model)
            )
        except (TypeError, ValueError) as error:
            raise ScoringTaskError("provider.invalid_output", str(error)) from error
        self._validate_provider_timelines(audio.frame_count, pitch, leakage)

        pitch_release = bound_model_release(
            pitch_model.record.model_id,
            pitch_model.record.artifact_sha256,
        )
        leakage_release = bound_model_release(
            leakage_model.record.model_id,
            leakage_model.record.artifact_sha256,
        )
        model_release = model_set_release(pitch_release, leakage_release)
        frames: list[UserFeatureFrame] = []
        for pitch_frame, leakage_frame in zip(pitch.frames, leakage.frames, strict=True):
            sample_index = calibration.reference_start_sample + pitch_frame.offset_samples
            if sample_index < 0:
                continue
            if sample_index >= job.manifest.duration_samples:
                break
            start = pitch_frame.offset_samples
            end = start + self.policy.hop_samples
            frames.append(
                UserFeatureFrame(
                    sample_index=sample_index,
                    voiced=pitch_frame.voiced,
                    f0_hz=quantize(pitch_frame.f0_hz) if pitch_frame.f0_hz is not None else None,
                    f0_confidence=quantize(pitch_frame.f0_confidence),
                    energy_dbfs=energy_dbfs(audio.samples[start:end]),
                    leakage_confidence=quantize(leakage_frame.leakage_confidence),
                )
            )
        if not frames:
            raise ScoringTaskError(
                "input.outside_reference_timeline",
                "phrase frames do not overlap the reference song timeline",
            )

        features = UserFeaturesV1(
            schema_version="user-features.v1",
            tenant_id=job.phrase.tenant_id,
            session_id=job.phrase.session_id,
            phrase_id=job.phrase.phrase_id,
            sample_rate=job.phrase.sample_rate,
            hop_samples=self.policy.hop_samples,
            source_audio_sha256=job.phrase.sha256,
            transport_evidence_sha256=calibration.evidence_sha256,
            model_releases=sorted([pitch_release, leakage_release]),
            frames=frames,
            versions=VersionStamp(
                pipeline_version=self.policy.pipeline_version,
                model_release=model_release,
                score_version=self.policy.score_version,
                calibration_version=job.phrase.calibration_version,
            ),
            produced_at=job.produced_at,
        )
        features_payload = canonical_model_bytes(features)
        features_sha256 = sha256_hex(features_payload)
        try:
            score = score_phrase(
                job.manifest,
                features,
                produced_at=job.produced_at,
                region_ids=job.region_ids,
            )
        except ScoringInvariantError as error:
            raise ScoringTaskError("score.invalid_inputs", str(error)) from error
        if (
            score.user_features_sha256 != features_sha256
            or score.transport_evidence_sha256 != calibration.evidence_sha256
        ):
            raise ScoringTaskError(
                "score.evidence_mismatch",
                "score did not bind its input evidence",
            )

        transport_release = (
            f"{self.policy.pipeline_version}@policy-{self.policy.fingerprint()[:24]}"
        )
        evidence = [
            EvidenceBlob(
                kind="transport",
                payload=calibration.evidence_payload,
                sha256=calibration.evidence_sha256,
                model_release=transport_release,
            ),
            EvidenceBlob(
                kind="user_features",
                payload=features_payload,
                sha256=features_sha256,
                model_release=model_release,
            ),
        ]
        idempotency_key = _idempotency_key(job, score, features_sha256)
        return ScoringComputation(
            features=features,
            score=score,
            evidence=evidence,
            idempotency_key=idempotency_key,
        )

    def _validate_provider_timelines(
        self,
        audio_frame_count: int,
        pitch: PitchAnalysis,
        leakage: LeakageAnalysis,
    ) -> None:
        if pitch.hop_samples != self.policy.hop_samples:
            raise ScoringTaskError("provider.invalid_output", "pitch hop does not match policy")
        if leakage.hop_samples != self.policy.hop_samples:
            raise ScoringTaskError("provider.invalid_output", "leakage hop does not match policy")
        pitch_offsets = [frame.offset_samples for frame in pitch.frames]
        leakage_offsets = [frame.offset_samples for frame in leakage.frames]
        if pitch_offsets != leakage_offsets:
            raise ScoringTaskError("provider.invalid_output", "provider frame offsets do not match")
        if any(offset + self.policy.hop_samples > audio_frame_count for offset in pitch_offsets):
            raise ScoringTaskError("provider.invalid_output", "provider frame exceeds phrase audio")


def _idempotency_key(job: ScoringJob, score, features_sha256: str) -> str:
    payload = json.dumps(
        {
            "tenant_id": str(job.phrase.tenant_id),
            "session_id": str(job.phrase.session_id),
            "phrase_id": str(job.phrase.phrase_id),
            "manifest_record_id": str(job.manifest_record_id),
            "features_sha256": features_sha256,
            "score_sha256": sha256_hex(canonical_model_bytes(score)),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()

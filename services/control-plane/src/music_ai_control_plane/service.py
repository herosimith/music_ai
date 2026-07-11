from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from music_ai_contracts.models import GateStatus, PhraseAudioV1, ScoreV1, SongManifestV1
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from music_ai_control_plane.config import Settings
from music_ai_control_plane.database import utc_now
from music_ai_control_plane.media_intake import (
    EncryptedAudioKind,
    detect_unsupported_encrypted_audio,
)
from music_ai_control_plane.models import (
    AudioState,
    DeletionRequest,
    DeletionResource,
    DeletionStatus,
    DeletionTask,
    PhraseArtifact,
    PracticeSession,
    ScoreRecord,
    Song,
    SongManifestRecord,
    SongState,
    StoredAsset,
)
from music_ai_control_plane.schemas import AssetCreate, SessionCreate, SongCreate
from music_ai_control_plane.storage import ObjectStore


class DomainError(RuntimeError):
    code = "domain_error"


class NotFoundError(DomainError):
    code = "not_found"


class ConflictError(DomainError):
    code = "conflict"


class InvalidRequestError(DomainError):
    code = "invalid_request"


class MggKeyUnavailableError(InvalidRequestError):
    code = "mgg.key_unavailable"


class MggEncryptedUnsupportedError(InvalidRequestError):
    code = "mgg.encrypted_unsupported"


class ControlPlaneService:
    def __init__(
        self,
        session: Session,
        object_store: ObjectStore,
        settings: Settings,
    ) -> None:
        self.session = session
        self.object_store = object_store
        self.settings = settings

    def create_song(
        self,
        tenant_id: UUID,
        request: SongCreate,
        *,
        now: datetime | None = None,
    ) -> Song:
        timestamp = _aware_now(now)
        existing = self.session.scalar(
            select(Song).where(
                Song.tenant_id == tenant_id,
                Song.source_sha256 == request.source_sha256,
                Song.deleted_at.is_(None),
            )
        )
        if existing is not None:
            if (
                existing.source_byte_length != request.source_byte_length
                or existing.source_media_type != request.source_media_type
            ):
                raise ConflictError("song source hash was reused with different metadata")
            return existing

        song = Song(
            tenant_id=tenant_id,
            display_name=request.display_name,
            rights_basis=request.rights_basis,
            source_sha256=request.source_sha256,
            source_byte_length=request.source_byte_length,
            source_media_type=request.source_media_type,
            state=SongState.PENDING_UPLOAD,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.session.add(song)
        self.session.flush()
        extension = {
            "audio/flac": "flac",
            "audio/mpeg": "mp3",
            "audio/ogg": "ogg",
            "audio/wav": "wav",
        }[request.source_media_type]
        song.source_object_key = (
            f"tenants/{tenant_id}/songs/{song.id}/source-{request.source_sha256}.{extension}"
        )
        self._commit("song with this source already exists")
        return song

    def upload_song_source(
        self,
        tenant_id: UUID,
        song_id: UUID,
        payload: bytes,
        *,
        now: datetime | None = None,
    ) -> Song:
        timestamp = _aware_now(now)
        song = self._song(tenant_id, song_id, for_update=True)
        if song.state not in {SongState.PENDING_UPLOAD, SongState.UPLOADED}:
            raise ConflictError("song source can no longer be replaced")
        self._verify_payload(
            payload,
            expected_length=song.source_byte_length,
            expected_sha256=song.source_sha256,
        )
        encrypted_kind = detect_unsupported_encrypted_audio(payload)
        if encrypted_kind == EncryptedAudioKind.MUSICEX:
            raise MggKeyUnavailableError(
                "MusicEx encrypted audio requires an authorized client export"
            )
        if encrypted_kind == EncryptedAudioKind.QMC_LEGACY:
            raise MggEncryptedUnsupportedError(
                "legacy encrypted MGG audio requires an authorized client export"
            )
        if song.source_object_key is None:
            raise InvalidRequestError("song source storage key is missing")
        if song.state == SongState.UPLOADED and self.object_store.exists(song.source_object_key):
            return song
        self.object_store.put(song.source_object_key, payload)
        song.state = SongState.UPLOADED
        song.source_uploaded_at = timestamp
        song.updated_at = timestamp
        self._commit("song source upload could not be recorded")
        return song

    def get_song(self, tenant_id: UUID, song_id: UUID) -> Song:
        return self._song(tenant_id, song_id)

    def reserve_asset(
        self,
        tenant_id: UUID,
        song_id: UUID,
        request: AssetCreate,
        *,
        now: datetime | None = None,
    ) -> StoredAsset:
        timestamp = _aware_now(now)
        self._song(tenant_id, song_id, for_update=True)
        existing = self.session.scalar(
            select(StoredAsset).where(
                StoredAsset.tenant_id == tenant_id,
                StoredAsset.song_id == song_id,
                StoredAsset.kind == request.kind,
                StoredAsset.sha256 == request.sha256,
                StoredAsset.byte_length == request.byte_length,
                StoredAsset.media_type == request.media_type,
                StoredAsset.model_release == request.model_release,
                StoredAsset.deleted_at.is_(None),
            )
        )
        if existing is not None:
            return existing
        asset = StoredAsset(
            tenant_id=tenant_id,
            song_id=song_id,
            kind=request.kind,
            sha256=request.sha256,
            byte_length=request.byte_length,
            media_type=request.media_type,
            model_release=request.model_release,
            state=AudioState.PENDING,
            created_at=timestamp,
        )
        self.session.add(asset)
        self.session.flush()
        asset.object_key = f"tenants/{tenant_id}/songs/{song_id}/assets/{asset.id}/{request.sha256}"
        self._commit("asset reservation conflicts with an existing asset")
        return asset

    def upload_asset(
        self,
        tenant_id: UUID,
        asset_id: UUID,
        payload: bytes,
        *,
        now: datetime | None = None,
    ) -> StoredAsset:
        timestamp = _aware_now(now)
        asset = self.session.scalar(
            select(StoredAsset)
            .where(
                StoredAsset.id == asset_id,
                StoredAsset.tenant_id == tenant_id,
                StoredAsset.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if asset is None:
            raise NotFoundError("asset not found")
        self._verify_payload(
            payload,
            expected_length=asset.byte_length,
            expected_sha256=asset.sha256,
        )
        if asset.object_key is None:
            raise InvalidRequestError("asset storage key is missing")
        if asset.state == AudioState.STORED and self.object_store.exists(asset.object_key):
            return asset
        if asset.state == AudioState.DELETED:
            raise ConflictError("asset has been deleted")
        self.object_store.put(asset.object_key, payload)
        asset.state = AudioState.STORED
        asset.uploaded_at = timestamp
        self._commit("asset upload could not be recorded")
        return asset

    def get_asset(self, tenant_id: UUID, asset_id: UUID) -> StoredAsset:
        asset = self.session.scalar(
            select(StoredAsset).where(
                StoredAsset.id == asset_id,
                StoredAsset.tenant_id == tenant_id,
                StoredAsset.deleted_at.is_(None),
            )
        )
        if asset is None:
            raise NotFoundError("asset not found")
        return asset

    def publish_manifest(
        self,
        tenant_id: UUID,
        song_id: UUID,
        manifest: SongManifestV1,
        *,
        now: datetime | None = None,
    ) -> SongManifestRecord:
        timestamp = _aware_now(now)
        song = self._song(tenant_id, song_id, for_update=True)
        if song.state == SongState.PENDING_UPLOAD:
            raise ConflictError("song source must be uploaded before publishing a manifest")
        if manifest.tenant_id != tenant_id or manifest.song_id != song_id:
            raise InvalidRequestError("manifest identity does not match the song")
        if song.source_sha256 is None or not hmac.compare_digest(
            manifest.source_sha256, song.source_sha256
        ):
            raise InvalidRequestError("manifest source hash does not match the song")
        if song.source_uploaded_at is not None and manifest.produced_at < song.source_uploaded_at:
            raise InvalidRequestError("manifest cannot predate the uploaded song source")
        if manifest.produced_at > timestamp + timedelta(minutes=5):
            raise InvalidRequestError("manifest production time is too far in the future")
        self._validate_manifest_artifacts(tenant_id, song, manifest)

        payload, digest = _canonical_model(manifest)
        existing = self.session.scalar(
            select(SongManifestRecord).where(
                SongManifestRecord.tenant_id == tenant_id,
                SongManifestRecord.song_id == song_id,
                SongManifestRecord.payload_sha256 == digest,
                SongManifestRecord.deleted_at.is_(None),
            )
        )
        if existing is not None:
            return existing
        record = SongManifestRecord(
            tenant_id=tenant_id,
            song_id=song_id,
            payload=payload,
            payload_sha256=digest,
            pipeline_version=manifest.versions.pipeline_version,
            model_release=manifest.versions.model_release,
            score_version=manifest.versions.score_version,
            calibration_version=manifest.versions.calibration_version,
            produced_at=manifest.produced_at,
            created_at=timestamp,
        )
        self.session.add(record)
        song.manifest_payload = payload
        song.manifest_sha256 = digest
        song.state = {
            GateStatus.ACCEPTED: SongState.ACCEPTED,
            GateStatus.PRACTICE_ONLY: SongState.PRACTICE_ONLY,
            GateStatus.REJECTED: SongState.REJECTED,
        }[manifest.gate_status]
        song.updated_at = timestamp
        self._commit("manifest version already exists")
        return record

    def create_practice_session(
        self,
        tenant_id: UUID,
        request: SessionCreate,
        *,
        now: datetime | None = None,
    ) -> PracticeSession:
        timestamp = _aware_now(now)
        song = self._song(tenant_id, request.song_id, for_update=True)
        manifest = self.session.scalar(
            select(SongManifestRecord).where(
                SongManifestRecord.id == request.manifest_record_id,
                SongManifestRecord.tenant_id == tenant_id,
                SongManifestRecord.song_id == song.id,
                SongManifestRecord.deleted_at.is_(None),
            )
        )
        if manifest is None or manifest.payload is None:
            raise NotFoundError("song manifest version not found")
        manifest_payload = SongManifestV1.model_validate(manifest.payload)
        if manifest_payload.gate_status not in {GateStatus.ACCEPTED, GateStatus.PRACTICE_ONLY}:
            raise ConflictError("song manifest is not available for practice")
        if manifest.calibration_version != request.calibration_version:
            raise ConflictError("session calibration must match the selected song manifest")
        session = PracticeSession(
            tenant_id=tenant_id,
            song_id=song.id,
            manifest_record_id=manifest.id,
            calibration_version=request.calibration_version,
            created_at=timestamp,
        )
        self.session.add(session)
        self._commit("practice session could not be created")
        return session

    def get_practice_session(self, tenant_id: UUID, session_id: UUID) -> PracticeSession:
        return self._practice_session(tenant_id, session_id)

    def reserve_phrase(
        self,
        tenant_id: UUID,
        phrase: PhraseAudioV1,
        *,
        now: datetime | None = None,
    ) -> PhraseArtifact:
        timestamp = _aware_now(now)
        if phrase.tenant_id != tenant_id:
            raise InvalidRequestError("phrase tenant does not match the credential")
        practice = self._practice_session(tenant_id, phrase.session_id, for_update=True)
        if phrase.calibration_version != practice.calibration_version:
            raise InvalidRequestError("phrase calibration does not match the session")
        if phrase.captured_at > timestamp + timedelta(minutes=5):
            raise InvalidRequestError("phrase capture time is too far in the future")

        existing = self.session.scalar(
            select(PhraseArtifact).where(
                PhraseArtifact.tenant_id == tenant_id,
                PhraseArtifact.idempotency_key == phrase.idempotency_key,
            )
        )
        if existing is not None:
            if not _same_phrase(existing, phrase):
                raise ConflictError("phrase idempotency key was reused with different metadata")
            if existing.audio_state == AudioState.DELETED or existing.deleted_at is not None:
                raise ConflictError("phrase reservation has already been deleted")
            return existing
        conflicting_id = self.session.scalar(
            select(PhraseArtifact).where(PhraseArtifact.id == phrase.phrase_id)
        )
        if conflicting_id is not None:
            raise ConflictError("phrase ID already exists")

        extension = "pcm" if phrase.codec == "pcm_s16le" else "wav"
        artifact = PhraseArtifact(
            id=phrase.phrase_id,
            tenant_id=tenant_id,
            session_id=practice.id,
            song_id=practice.song_id,
            sequence=phrase.sequence,
            sample_start=phrase.sample_start,
            sample_end=phrase.sample_end,
            sample_rate=phrase.sample_rate,
            codec=phrase.codec,
            byte_length=phrase.byte_length,
            sha256=phrase.sha256,
            calibration_version=phrase.calibration_version,
            captured_at=phrase.captured_at,
            idempotency_key=phrase.idempotency_key,
            audio_state=AudioState.PENDING,
            object_key=(
                f"tenants/{tenant_id}/phrases/{phrase.phrase_id}/{phrase.sha256}.{extension}"
            ),
            expires_at=timestamp + timedelta(seconds=self.settings.raw_audio_ttl_seconds),
            created_at=timestamp,
        )
        self.session.add(artifact)
        self._commit("phrase sequence or idempotency key already exists")
        return artifact

    def upload_phrase(
        self,
        tenant_id: UUID,
        phrase_id: UUID,
        payload: bytes,
        *,
        now: datetime | None = None,
    ) -> PhraseArtifact:
        timestamp = _aware_now(now)
        phrase = self._phrase(tenant_id, phrase_id, for_update=True)
        if phrase.audio_state == AudioState.DELETED:
            raise ConflictError("phrase audio has been deleted")
        if timestamp >= phrase.expires_at:
            raise ConflictError("phrase upload reservation has expired")
        self._verify_payload(
            payload,
            expected_length=phrase.byte_length,
            expected_sha256=phrase.sha256,
        )
        if phrase.object_key is None:
            raise InvalidRequestError("phrase storage key is missing")
        if phrase.audio_state == AudioState.STORED and self.object_store.exists(phrase.object_key):
            return phrase
        self.object_store.put(phrase.object_key, payload)
        phrase.audio_state = AudioState.STORED
        phrase.uploaded_at = timestamp
        self._commit("phrase upload could not be recorded")
        return phrase

    def get_phrase(self, tenant_id: UUID, phrase_id: UUID) -> PhraseArtifact:
        return self._phrase(tenant_id, phrase_id)

    def write_score(
        self,
        tenant_id: UUID,
        score: ScoreV1,
        idempotency_key: str,
        manifest_record_id: UUID,
        *,
        now: datetime | None = None,
    ) -> ScoreRecord:
        timestamp = _aware_now(now)
        if len(idempotency_key) < 16 or len(idempotency_key) > 128:
            raise InvalidRequestError("score idempotency key must contain 16 to 128 characters")
        if score.tenant_id != tenant_id:
            raise InvalidRequestError("score tenant does not match the credential")
        payload, digest = _canonical_model(score)
        existing = self.session.scalar(
            select(ScoreRecord).where(
                ScoreRecord.tenant_id == tenant_id,
                ScoreRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.payload_sha256 != digest:
                raise ConflictError("score idempotency key was reused with different content")
            if existing.manifest_record_id != manifest_record_id:
                raise InvalidRequestError("score idempotency retry changed its manifest version")
            if existing.deleted_at is not None:
                raise ConflictError("score was deleted and cannot be recreated with the same key")
            self._song(tenant_id, score.song_id, for_update=True)
            self._require_score_evidence(tenant_id, score)
            return existing
        song = self._song(tenant_id, score.song_id, for_update=True)
        practice = self._practice_session(tenant_id, score.session_id, for_update=True)
        phrase = self._phrase(tenant_id, score.phrase_id, for_update=True)
        if (
            practice.song_id != song.id
            or phrase.song_id != song.id
            or phrase.session_id != practice.id
        ):
            raise InvalidRequestError("score resource identities do not belong together")
        if phrase.audio_state != AudioState.STORED:
            raise ConflictError("phrase audio must be stored before accepting a score")
        if (
            score.versions.calibration_version != practice.calibration_version
            or score.versions.calibration_version != phrase.calibration_version
        ):
            raise InvalidRequestError("score calibration does not match the phrase session")
        if phrase.uploaded_at is not None and score.produced_at < phrase.uploaded_at:
            raise InvalidRequestError("score cannot predate its phrase upload")
        if score.produced_at > timestamp + timedelta(minutes=5):
            raise InvalidRequestError("score production time is too far in the future")
        if practice.manifest_record_id != manifest_record_id:
            raise InvalidRequestError("score manifest does not match the practice session")
        manifest_record = self._manifest_for_score(
            tenant_id,
            song.id,
            manifest_record_id,
            score,
        )
        if manifest_record.payload is None:
            raise ConflictError("score manifest payload has been deleted")
        manifest = SongManifestV1.model_validate(manifest_record.payload)
        if manifest.gate_status != GateStatus.ACCEPTED:
            raise ConflictError("only accepted references can receive authoritative scores")
        if manifest.reference_source != score.reference_source:
            raise InvalidRequestError("score reference source does not match its manifest")
        if score.produced_at < manifest_record.produced_at:
            raise InvalidRequestError("score cannot predate its reference manifest")
        self._require_score_evidence(tenant_id, score)

        record = ScoreRecord(
            tenant_id=tenant_id,
            song_id=song.id,
            manifest_record_id=manifest_record.id,
            session_id=practice.id,
            phrase_id=phrase.id,
            idempotency_key=idempotency_key,
            schema_version=score.schema_version,
            score_version=score.versions.score_version,
            pipeline_version=score.versions.pipeline_version,
            model_release=score.versions.model_release,
            calibration_version=score.versions.calibration_version,
            payload=payload,
            payload_sha256=digest,
            produced_at=score.produced_at,
            created_at=timestamp,
        )
        self.session.add(record)
        self._commit("score idempotency key already exists")
        return record

    def _require_score_evidence(self, tenant_id: UUID, score: ScoreV1) -> None:
        expected = {
            "transport": score.transport_evidence_sha256,
            "user_features": score.user_features_sha256,
        }
        if any(digest is None for digest in expected.values()):
            raise InvalidRequestError(
                "authoritative scores must bind transport and user feature evidence"
            )
        digests = {digest for digest in expected.values() if digest is not None}
        assets = list(
            self.session.scalars(
                select(StoredAsset).where(
                    StoredAsset.tenant_id == tenant_id,
                    StoredAsset.song_id == score.song_id,
                    StoredAsset.kind.in_(expected),
                    StoredAsset.sha256.in_(digests),
                    StoredAsset.deleted_at.is_(None),
                )
            )
        )
        for kind, digest in expected.items():
            matches = [
                asset
                for asset in assets
                if asset.kind == kind
                and asset.sha256 == digest
                and asset.media_type == "application/json"
                and asset.model_release is not None
                and (
                    kind != "user_features"
                    or asset.model_release == score.versions.model_release
                )
            ]
            if not matches:
                raise InvalidRequestError(
                    "score references unregistered or mismatched evidence"
                )
            if not any(
                asset.state == AudioState.STORED
                and asset.object_key is not None
                and self.object_store.exists(asset.object_key)
                for asset in matches
            ):
                raise ConflictError("score evidence is unavailable")

    def list_scores(self, tenant_id: UUID, session_id: UUID) -> list[ScoreRecord]:
        self._practice_session(tenant_id, session_id)
        return list(
            self.session.scalars(
                select(ScoreRecord)
                .where(
                    ScoreRecord.tenant_id == tenant_id,
                    ScoreRecord.session_id == session_id,
                    ScoreRecord.deleted_at.is_(None),
                )
                .order_by(ScoreRecord.created_at, ScoreRecord.id)
            )
        )

    def get_score(self, tenant_id: UUID, score_id: UUID) -> ScoreRecord:
        score = self.session.scalar(
            select(ScoreRecord).where(
                ScoreRecord.id == score_id,
                ScoreRecord.tenant_id == tenant_id,
                ScoreRecord.deleted_at.is_(None),
            )
        )
        if score is None:
            raise NotFoundError("score not found")
        return score

    def request_song_deletion(
        self,
        tenant_id: UUID,
        song_id: UUID,
        *,
        now: datetime | None = None,
    ) -> DeletionRequest:
        timestamp = _aware_now(now)
        existing = self._deletion_for_resource(
            tenant_id,
            DeletionResource.SONG,
            song_id,
        )
        if existing is not None:
            return existing
        song = self.session.scalar(
            select(Song).where(Song.id == song_id, Song.tenant_id == tenant_id).with_for_update()
        )
        existing = self._deletion_for_resource(
            tenant_id,
            DeletionResource.SONG,
            song_id,
        )
        if existing is not None:
            return existing
        if song is None:
            raise NotFoundError("song not found")

        deletion = DeletionRequest(
            tenant_id=tenant_id,
            resource_type=DeletionResource.SONG,
            resource_id=song_id,
            reason="user_requested",
            status=DeletionStatus.PENDING,
            requested_at=timestamp,
        )
        self.session.add(deletion)
        self.session.flush()
        object_keys: list[str] = []
        if song.source_object_key is not None:
            object_keys.append(song.source_object_key)

        manifests = list(
            self.session.scalars(
                select(SongManifestRecord)
                .where(
                    SongManifestRecord.tenant_id == tenant_id,
                    SongManifestRecord.song_id == song_id,
                )
                .with_for_update()
            )
        )
        for manifest in manifests:
            manifest.payload = None
            manifest.payload_sha256 = None
            manifest.deleted_at = timestamp

        sessions = list(
            self.session.scalars(
                select(PracticeSession)
                .where(
                    PracticeSession.tenant_id == tenant_id,
                    PracticeSession.song_id == song_id,
                )
                .with_for_update()
            )
        )
        for practice in sessions:
            practice.deleted_at = timestamp

        phrases = list(
            self.session.scalars(
                select(PhraseArtifact)
                .where(
                    PhraseArtifact.tenant_id == tenant_id,
                    PhraseArtifact.song_id == song_id,
                )
                .with_for_update()
            )
        )
        for phrase in phrases:
            if phrase.object_key is not None:
                object_keys.append(phrase.object_key)
            phrase.object_key = None
            phrase.audio_state = AudioState.DELETED
            phrase.audio_deleted_at = timestamp
            phrase.deleted_at = timestamp
            phrase.sha256 = None
            phrase.idempotency_key = None

        assets = list(
            self.session.scalars(
                select(StoredAsset)
                .where(
                    StoredAsset.tenant_id == tenant_id,
                    StoredAsset.song_id == song_id,
                )
                .with_for_update()
            )
        )
        for asset in assets:
            if asset.object_key is not None:
                object_keys.append(asset.object_key)
            asset.object_key = None
            asset.sha256 = None
            asset.state = AudioState.DELETED
            asset.deleted_at = timestamp

        scores = list(
            self.session.scalars(
                select(ScoreRecord)
                .where(
                    ScoreRecord.tenant_id == tenant_id,
                    ScoreRecord.song_id == song_id,
                )
                .with_for_update()
            )
        )
        for score in scores:
            score.payload = None
            score.payload_sha256 = None
            score.idempotency_key = None
            score.deleted_at = timestamp

        song.display_name = None
        song.rights_basis = None
        song.source_sha256 = None
        song.source_byte_length = None
        song.source_media_type = None
        song.source_object_key = None
        song.source_uploaded_at = None
        song.manifest_payload = None
        song.manifest_sha256 = None
        song.state = SongState.DELETED
        song.deleted_at = timestamp
        song.updated_at = timestamp
        self._add_deletion_tasks(deletion, tenant_id, object_keys, timestamp)
        if not object_keys:
            self.session.add(
                DeletionTask(
                    request_id=deletion.id,
                    tenant_id=tenant_id,
                    object_key=None,
                    status=DeletionStatus.PENDING,
                    next_attempt_at=timestamp,
                    created_at=timestamp,
                )
            )
        self._commit("song deletion could not be recorded")
        return deletion

    def expire_raw_audio(
        self,
        tenant_id: UUID,
        *,
        now: datetime | None = None,
    ) -> int:
        timestamp = _aware_now(now)
        expired = list(
            self.session.scalars(
                select(PhraseArtifact)
                .where(
                    PhraseArtifact.tenant_id == tenant_id,
                    PhraseArtifact.deleted_at.is_(None),
                    PhraseArtifact.audio_state != AudioState.DELETED,
                    PhraseArtifact.expires_at <= timestamp,
                )
                .with_for_update(skip_locked=True)
            )
        )
        created = 0
        for phrase in expired:
            existing = self._deletion_for_resource(
                tenant_id,
                DeletionResource.PHRASE_AUDIO,
                phrase.id,
            )
            if existing is not None:
                continue
            deletion = DeletionRequest(
                tenant_id=tenant_id,
                resource_type=DeletionResource.PHRASE_AUDIO,
                resource_id=phrase.id,
                reason="raw_audio_ttl",
                status=DeletionStatus.PENDING,
                requested_at=timestamp,
            )
            self.session.add(deletion)
            self.session.flush()
            object_keys = [phrase.object_key] if phrase.object_key is not None else []
            phrase.object_key = None
            phrase.audio_state = AudioState.DELETED
            phrase.audio_deleted_at = timestamp
            self._add_deletion_tasks(deletion, tenant_id, object_keys, timestamp)
            if not object_keys:
                deletion.status = DeletionStatus.COMPLETED
                deletion.completed_at = timestamp
            created += 1
        self._commit("raw audio expiry could not be recorded")
        return created

    def process_deletions(
        self,
        tenant_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[int, int]:
        timestamp = _aware_now(now)
        tasks = list(
            self.session.scalars(
                select(DeletionTask)
                .where(
                    DeletionTask.tenant_id == tenant_id,
                    DeletionTask.status == DeletionStatus.PENDING,
                    DeletionTask.next_attempt_at <= timestamp,
                )
                .with_for_update(skip_locked=True)
            )
        )
        completed = 0
        failed = 0
        for task in tasks:
            try:
                if task.object_key is not None:
                    self.object_store.delete(task.object_key)
                task.object_key = None
                task.status = DeletionStatus.COMPLETED
                task.completed_at = timestamp
                task.last_error = None
                completed += 1
            except Exception as error:
                task.attempts += 1
                task.last_error = _safe_error(error)
                if task.attempts >= self.settings.deletion_retry_limit:
                    task.status = DeletionStatus.FAILED
                    failed += 1
                else:
                    task.next_attempt_at = timestamp + timedelta(seconds=min(300, 2**task.attempts))

        self.session.flush()
        pending_deletions = list(
            self.session.scalars(
                select(DeletionRequest)
                .where(
                    DeletionRequest.tenant_id == tenant_id,
                    DeletionRequest.status == DeletionStatus.PENDING,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for deletion in pending_deletions:
            statuses = list(
                self.session.scalars(
                    select(DeletionTask.status).where(
                        DeletionTask.request_id == deletion.id,
                        DeletionTask.tenant_id == tenant_id,
                    )
                )
            )
            if statuses and all(status == DeletionStatus.COMPLETED for status in statuses):
                if deletion.resource_type == DeletionResource.SONG:
                    self._purge_song_records(deletion.tenant_id, deletion.resource_id)
                deletion.status = DeletionStatus.COMPLETED
                deletion.completed_at = timestamp
                deletion.last_error = None
            elif any(status == DeletionStatus.FAILED for status in statuses):
                deletion.status = DeletionStatus.FAILED
                deletion.last_error = "one or more object deletions exhausted retries"
        self._commit("deletion task results could not be recorded")
        return completed, failed

    def get_deletion(self, tenant_id: UUID, deletion_id: UUID) -> DeletionRequest:
        deletion = self.session.scalar(
            select(DeletionRequest).where(
                DeletionRequest.id == deletion_id,
                DeletionRequest.tenant_id == tenant_id,
            )
        )
        if deletion is None:
            raise NotFoundError("deletion request not found")
        return deletion

    def _song(self, tenant_id: UUID, song_id: UUID, *, for_update: bool = False) -> Song:
        statement = select(Song).where(
            Song.id == song_id,
            Song.tenant_id == tenant_id,
            Song.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        song = self.session.scalar(statement)
        if song is None:
            raise NotFoundError("song not found")
        return song

    def _practice_session(
        self,
        tenant_id: UUID,
        session_id: UUID,
        *,
        for_update: bool = False,
    ) -> PracticeSession:
        statement = select(PracticeSession).where(
            PracticeSession.id == session_id,
            PracticeSession.tenant_id == tenant_id,
            PracticeSession.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        practice = self.session.scalar(statement)
        if practice is None:
            raise NotFoundError("practice session not found")
        return practice

    def _phrase(
        self,
        tenant_id: UUID,
        phrase_id: UUID,
        *,
        for_update: bool = False,
    ) -> PhraseArtifact:
        statement = select(PhraseArtifact).where(
            PhraseArtifact.id == phrase_id,
            PhraseArtifact.tenant_id == tenant_id,
            PhraseArtifact.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        phrase = self.session.scalar(statement)
        if phrase is None:
            raise NotFoundError("phrase not found")
        return phrase

    def _manifest_for_score(
        self,
        tenant_id: UUID,
        song_id: UUID,
        manifest_record_id: UUID,
        score: ScoreV1,
    ) -> SongManifestRecord:
        manifest = self.session.scalar(
            select(SongManifestRecord).where(
                SongManifestRecord.id == manifest_record_id,
                SongManifestRecord.tenant_id == tenant_id,
                SongManifestRecord.song_id == song_id,
                SongManifestRecord.score_version == score.versions.score_version,
                SongManifestRecord.calibration_version == score.versions.calibration_version,
                SongManifestRecord.deleted_at.is_(None),
            )
        )
        if manifest is None:
            raise ConflictError("no compatible immutable manifest exists for this score")
        return manifest

    def _validate_manifest_artifacts(
        self,
        tenant_id: UUID,
        song: Song,
        manifest: SongManifestV1,
    ) -> None:
        assets = list(
            self.session.scalars(
                select(StoredAsset).where(
                    StoredAsset.tenant_id == tenant_id,
                    StoredAsset.song_id == song.id,
                    StoredAsset.state == AudioState.STORED,
                    StoredAsset.deleted_at.is_(None),
                )
            )
        )
        by_id = {str(asset.id): asset for asset in assets}
        for pointer in manifest.artifacts:
            if pointer.kind == "source":
                if pointer.artifact_id != f"song-source:{song.id}":
                    raise InvalidRequestError("source artifact ID does not match the song")
                if song.source_sha256 is None or pointer.sha256 != song.source_sha256:
                    raise InvalidRequestError("source artifact hash does not match the song")
                if song.source_object_key is None or not self.object_store.exists(
                    song.source_object_key
                ):
                    raise InvalidRequestError("song source object is unavailable")
                continue
            asset = by_id.get(pointer.artifact_id)
            if (
                asset is None
                or asset.kind != pointer.kind
                or asset.sha256 != pointer.sha256
                or asset.model_release != pointer.model_release
                or asset.object_key is None
                or not self.object_store.exists(asset.object_key)
            ):
                raise InvalidRequestError("manifest references an unregistered or mismatched asset")

    def _verify_payload(
        self,
        payload: bytes,
        *,
        expected_length: int | None,
        expected_sha256: str | None,
    ) -> None:
        if expected_length is None or expected_sha256 is None:
            raise InvalidRequestError("upload metadata has been removed")
        if len(payload) > self.settings.max_upload_bytes:
            raise InvalidRequestError("upload exceeds the configured size limit")
        if len(payload) != expected_length:
            raise InvalidRequestError("upload byte length does not match its reservation")
        digest = hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(digest, expected_sha256):
            raise InvalidRequestError("upload hash does not match its reservation")

    def _deletion_for_resource(
        self,
        tenant_id: UUID,
        resource_type: DeletionResource,
        resource_id: UUID,
    ) -> DeletionRequest | None:
        return self.session.scalar(
            select(DeletionRequest).where(
                DeletionRequest.tenant_id == tenant_id,
                DeletionRequest.resource_type == resource_type,
                DeletionRequest.resource_id == resource_id,
            )
        )

    def _add_deletion_tasks(
        self,
        deletion: DeletionRequest,
        tenant_id: UUID,
        object_keys: list[str],
        timestamp: datetime,
    ) -> None:
        for object_key in sorted(set(object_keys)):
            self.session.add(
                DeletionTask(
                    request_id=deletion.id,
                    tenant_id=tenant_id,
                    object_key=object_key,
                    status=DeletionStatus.PENDING,
                    next_attempt_at=timestamp,
                    created_at=timestamp,
                )
            )

    def _purge_song_records(self, tenant_id: UUID, song_id: UUID) -> None:
        for model in (
            ScoreRecord,
            PhraseArtifact,
            PracticeSession,
            SongManifestRecord,
            StoredAsset,
        ):
            self.session.execute(
                delete(model)
                .where(model.tenant_id == tenant_id, model.song_id == song_id)
                .execution_options(synchronize_session=False)
            )
        self.session.execute(
            delete(Song)
            .where(Song.tenant_id == tenant_id, Song.id == song_id)
            .execution_options(synchronize_session=False)
        )

    def _commit(self, conflict_message: str) -> None:
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise ConflictError(conflict_message) from None


def _canonical_model(model: SongManifestV1 | ScoreV1) -> tuple[dict[str, object], str]:
    payload = model.model_dump(mode="json")
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return payload, hashlib.sha256(encoded).hexdigest()


def _same_phrase(record: PhraseArtifact, phrase: PhraseAudioV1) -> bool:
    return (
        record.id == phrase.phrase_id
        and record.session_id == phrase.session_id
        and record.sequence == phrase.sequence
        and record.sample_start == phrase.sample_start
        and record.sample_end == phrase.sample_end
        and record.sample_rate == phrase.sample_rate
        and record.codec == phrase.codec
        and record.byte_length == phrase.byte_length
        and record.sha256 == phrase.sha256
        and record.calibration_version == phrase.calibration_version
        and record.captured_at == phrase.captured_at
    )


def _aware_now(value: datetime | None) -> datetime:
    timestamp = value or utc_now()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise InvalidRequestError("operation time must include a timezone")
    return timestamp.astimezone(UTC)


def _safe_error(error: Exception) -> str:
    return f"{type(error).__name__}: object deletion failed"[:1000]

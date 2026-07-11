from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from music_ai_contracts.models import PhraseAudioV1, ScoreV1, SongManifestV1
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from music_ai_control_plane.config import Settings
from music_ai_control_plane.database import Database
from music_ai_control_plane.models import AudioState, PhraseArtifact, ScoreRecord, Song, StoredAsset
from music_ai_control_plane.schemas import (
    AssetCreate,
    AssetView,
    DeletionView,
    ErrorView,
    HealthView,
    MaintenanceResult,
    ManifestRecordView,
    PhraseView,
    ScoreRecordView,
    SessionCreate,
    SessionView,
    SongCreate,
    SongView,
)
from music_ai_control_plane.security import (
    Actor,
    AuthenticationError,
    ScopeDeniedError,
    authenticate,
    ensure_bootstrap_credential,
)
from music_ai_control_plane.service import (
    ControlPlaneService,
    DomainError,
    NotFoundError,
)
from music_ai_control_plane.storage import LocalObjectStore, ObjectStore

bearer = HTTPBearer(auto_error=False)


def create_app(
    settings: Settings | None = None,
    object_store: ObjectStore | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(resolved_settings.database_url)
        if resolved_settings.auto_create_schema:
            database.create_schema()
        store = object_store or LocalObjectStore(resolved_settings.object_store_root)
        app.state.database = database
        app.state.object_store = store
        app.state.settings = resolved_settings
        if resolved_settings.bootstrap_api_token is not None:
            with database.session() as session:
                ensure_bootstrap_credential(
                    session,
                    tenant_slug=resolved_settings.bootstrap_tenant_slug or "",
                    tenant_name=resolved_settings.bootstrap_tenant_name or "",
                    token=resolved_settings.bootstrap_api_token.get_secret_value(),
                    pepper=resolved_settings.token_pepper.get_secret_value(),
                )
        try:
            yield
        finally:
            database.dispose()

    app = FastAPI(
        title="music_ai control plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    _install_error_handlers(app)

    @app.get("/health", response_model=HealthView)
    def health() -> HealthView:
        return HealthView(status="ok")

    @app.get("/ready", response_model=HealthView)
    def ready(session: Annotated[Session, Depends(get_session)]) -> HealthView:
        try:
            session.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="database is unavailable") from error
        return HealthView(status="ok")

    @app.post("/v1/songs", response_model=SongView)
    def create_song(
        request: SongCreate,
        actor: Annotated[Actor, Depends(require_scope("songs:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> SongView:
        return _song_view(service.create_song(actor.tenant_id, request))

    @app.get("/v1/songs/{song_id}", response_model=SongView)
    def get_song(
        song_id: UUID,
        actor: Annotated[Actor, Depends(get_actor)],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> SongView:
        return _song_view(service.get_song(actor.tenant_id, song_id))

    @app.put("/v1/songs/{song_id}/content", response_model=SongView)
    async def upload_song(
        song_id: UUID,
        request: Request,
        actor: Annotated[Actor, Depends(require_scope("songs:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> SongView:
        song = await run_in_threadpool(service.get_song, actor.tenant_id, song_id)
        _require_content_type(request, {song.source_media_type or ""})
        payload = await _read_upload(request, service.settings.max_upload_bytes)
        uploaded = await run_in_threadpool(
            service.upload_song_source,
            actor.tenant_id,
            song_id,
            payload,
        )
        return _song_view(uploaded)

    @app.post("/internal/v1/songs/{song_id}/assets", response_model=AssetView)
    def reserve_asset(
        song_id: UUID,
        request: AssetCreate,
        actor: Annotated[Actor, Depends(require_scope("assets:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> AssetView:
        return _asset_view(service.reserve_asset(actor.tenant_id, song_id, request))

    @app.put("/internal/v1/assets/{asset_id}/content", response_model=AssetView)
    async def upload_asset(
        asset_id: UUID,
        request: Request,
        actor: Annotated[Actor, Depends(require_scope("assets:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> AssetView:
        asset = await run_in_threadpool(service.get_asset, actor.tenant_id, asset_id)
        _require_content_type(request, {asset.media_type or ""})
        payload = await _read_upload(request, service.settings.max_upload_bytes)
        uploaded = await run_in_threadpool(
            service.upload_asset,
            actor.tenant_id,
            asset_id,
            payload,
        )
        return _asset_view(uploaded)

    @app.post(
        "/internal/v1/songs/{song_id}/manifests",
        response_model=ManifestRecordView,
    )
    def publish_manifest(
        song_id: UUID,
        manifest: SongManifestV1,
        actor: Annotated[Actor, Depends(require_scope("assets:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> ManifestRecordView:
        record = service.publish_manifest(actor.tenant_id, song_id, manifest)
        return ManifestRecordView(
            id=record.id,
            song_id=record.song_id,
            payload_sha256=_required(record.payload_sha256),
            manifest=SongManifestV1.model_validate(record.payload),
            created_at=record.created_at,
        )

    @app.post("/v1/sessions", response_model=SessionView)
    def create_session(
        request: SessionCreate,
        actor: Annotated[Actor, Depends(require_scope("sessions:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> SessionView:
        return SessionView.model_validate(service.create_practice_session(actor.tenant_id, request))

    @app.get("/v1/sessions/{session_id}", response_model=SessionView)
    def get_session(
        session_id: UUID,
        actor: Annotated[Actor, Depends(get_actor)],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> SessionView:
        return SessionView.model_validate(service.get_practice_session(actor.tenant_id, session_id))

    @app.post("/v1/phrases", response_model=PhraseView)
    def reserve_phrase(
        phrase: PhraseAudioV1,
        actor: Annotated[Actor, Depends(require_scope("phrases:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> PhraseView:
        return _phrase_view(service.reserve_phrase(actor.tenant_id, phrase))

    @app.put("/v1/phrases/{phrase_id}/content", response_model=PhraseView)
    async def upload_phrase(
        phrase_id: UUID,
        request: Request,
        actor: Annotated[Actor, Depends(require_scope("phrases:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> PhraseView:
        phrase = await run_in_threadpool(service.get_phrase, actor.tenant_id, phrase_id)
        expected_types = (
            {"application/octet-stream"}
            if phrase.codec == "pcm_s16le"
            else {"audio/wav", "audio/x-wav"}
        )
        _require_content_type(request, expected_types)
        payload = await _read_upload(request, service.settings.max_upload_bytes)
        uploaded = await run_in_threadpool(
            service.upload_phrase,
            actor.tenant_id,
            phrase_id,
            payload,
        )
        return _phrase_view(uploaded)

    @app.post("/internal/v1/scores", response_model=ScoreRecordView)
    def write_score(
        score: ScoreV1,
        actor: Annotated[Actor, Depends(require_scope("scores:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        manifest_record_id: Annotated[UUID, Header(alias="Reference-Manifest-Id")],
    ) -> ScoreRecordView:
        record = service.write_score(
            actor.tenant_id,
            score,
            idempotency_key,
            manifest_record_id,
        )
        return _score_view(record)

    @app.get("/v1/sessions/{session_id}/scores", response_model=list[ScoreRecordView])
    def list_scores(
        session_id: UUID,
        actor: Annotated[Actor, Depends(get_actor)],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> list[ScoreRecordView]:
        return [_score_view(record) for record in service.list_scores(actor.tenant_id, session_id)]

    @app.delete(
        "/v1/songs/{song_id}",
        response_model=DeletionView,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def delete_song(
        song_id: UUID,
        actor: Annotated[Actor, Depends(require_scope("songs:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> DeletionView:
        return DeletionView.model_validate(service.request_song_deletion(actor.tenant_id, song_id))

    @app.get("/v1/deletions/{deletion_id}", response_model=DeletionView)
    def get_deletion(
        deletion_id: UUID,
        actor: Annotated[Actor, Depends(get_actor)],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> DeletionView:
        return DeletionView.model_validate(service.get_deletion(actor.tenant_id, deletion_id))

    @app.post("/internal/v1/maintenance/expire", response_model=MaintenanceResult)
    def run_maintenance(
        actor: Annotated[Actor, Depends(require_scope("maintenance:write"))],
        service: Annotated[ControlPlaneService, Depends(get_service)],
    ) -> MaintenanceResult:
        expired = service.expire_raw_audio(actor.tenant_id)
        completed, failed = service.process_deletions(actor.tenant_id)
        return MaintenanceResult(
            expired_audio=expired,
            completed_tasks=completed,
            failed_tasks=failed,
        )

    return app


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> Iterator[Session]:
    with database.session() as session:
        yield session


def get_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> Actor:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("bearer token is required")
    settings: Settings = request.app.state.settings
    try:
        return authenticate(
            session,
            token=credentials.credentials,
            pepper=settings.token_pepper.get_secret_value(),
        )
    except ValueError as error:
        raise AuthenticationError("invalid or revoked bearer token") from error


def require_scope(scope: str):
    def dependency(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
        actor.require(scope)
        return actor

    return dependency


def get_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> ControlPlaneService:
    return ControlPlaneService(
        session,
        request.app.state.object_store,
        request.app.state.settings,
    )


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, error: DomainError) -> JSONResponse:
        status_code = 404 if isinstance(error, NotFoundError) else 409
        if error.code == "invalid_request":
            status_code = 422
        return _error_response(status_code, error.code, str(error))

    @app.exception_handler(AuthenticationError)
    async def handle_authentication_error(
        request: Request,
        error: AuthenticationError,
    ) -> JSONResponse:
        return _error_response(401, "unauthorized", str(error), authenticate_header=True)

    @app.exception_handler(ScopeDeniedError)
    async def handle_scope_error(request: Request, error: ScopeDeniedError) -> JSONResponse:
        return _error_response(403, "forbidden", str(error))


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    authenticate_header: bool = False,
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if authenticate_header else None
    return JSONResponse(
        status_code=status_code,
        content=ErrorView(code=code, message=message).model_dump(mode="json"),
        headers=headers,
    )


def _song_view(song: Song) -> SongView:
    upload_path = f"/v1/songs/{song.id}/content" if song.state.value == "pending_upload" else None
    return SongView(
        id=song.id,
        display_name=_required(song.display_name),
        state=song.state,
        created_at=song.created_at,
        updated_at=song.updated_at,
        upload_path=upload_path,
    )


def _asset_view(asset: StoredAsset) -> AssetView:
    return AssetView(
        id=asset.id,
        song_id=asset.song_id,
        kind=asset.kind,
        state=asset.state,
        upload_path=(
            f"/internal/v1/assets/{asset.id}/content" if asset.state == AudioState.PENDING else None
        ),
    )


def _phrase_view(phrase: PhraseArtifact) -> PhraseView:
    return PhraseView(
        id=phrase.id,
        session_id=phrase.session_id,
        sequence=phrase.sequence,
        audio_state=phrase.audio_state,
        expires_at=phrase.expires_at,
        upload_path=(
            f"/v1/phrases/{phrase.id}/content" if phrase.audio_state == AudioState.PENDING else None
        ),
    )


def _score_view(record: ScoreRecord) -> ScoreRecordView:
    return ScoreRecordView(
        id=record.id,
        session_id=record.session_id,
        phrase_id=record.phrase_id,
        song_id=record.song_id,
        manifest_record_id=record.manifest_record_id,
        payload_sha256=_required(record.payload_sha256),
        score=ScoreV1.model_validate(record.payload),
        created_at=record.created_at,
    )


async def _read_upload(request: Request, maximum: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid Content-Length") from error
        if declared < 0 or declared > maximum:
            raise HTTPException(status_code=413, detail="upload is too large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > maximum:
            raise HTTPException(status_code=413, detail="upload is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _require_content_type(request: Request, expected: set[str]) -> None:
    actual = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if actual not in expected:
        raise HTTPException(status_code=415, detail="unsupported media type")


def _required(value: Any | None):
    if value is None:
        raise RuntimeError("active record is missing required data")
    return value

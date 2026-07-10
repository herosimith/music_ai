from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

import httpx2
from music_ai_contracts.models import SongManifestV1
from pydantic import ValidationError

from music_ai_ingest.types import ArtifactBlob, PublishedArtifact


class ControlPlanePublishError(RuntimeError):
    pass


class ArtifactPublisher(Protocol):
    def publish_artifact(self, song_id: UUID, artifact: ArtifactBlob) -> PublishedArtifact: ...

    def publish_manifest(self, song_id: UUID, manifest: SongManifestV1) -> UUID: ...


class ControlPlanePublisher:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 60.0,
        client: Any | None = None,
    ) -> None:
        if len(token) < 32:
            raise ValueError("control-plane token must contain at least 32 characters")
        self._token = token
        self._owns_client = client is None
        self._client = client or httpx2.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )

    def publish_artifact(self, song_id: UUID, artifact: ArtifactBlob) -> PublishedArtifact:
        reservation = self._request_json(
            "post",
            f"/internal/v1/songs/{song_id}/assets",
            json={
                "kind": artifact.kind,
                "sha256": artifact.sha256,
                "byte_length": len(artifact.payload),
                "media_type": artifact.media_type,
                "model_release": artifact.model_release,
            },
        )
        artifact_id = _response_uuid(reservation, "id", "artifact reservation")
        if reservation.get("song_id") != str(song_id) or reservation.get("kind") != artifact.kind:
            raise ControlPlanePublishError(
                "control plane returned a mismatched artifact reservation"
            )
        state = reservation.get("state")
        if state == "pending":
            expected_path = f"/internal/v1/assets/{artifact_id}/content"
            if reservation.get("upload_path") != expected_path:
                raise ControlPlanePublishError("control plane returned an unexpected artifact path")
            uploaded = self._request_json(
                "put",
                expected_path,
                content=artifact.payload,
                headers={"Content-Type": artifact.media_type},
            )
            if uploaded.get("state") != "stored" or uploaded.get("id") != str(artifact_id):
                raise ControlPlanePublishError("control plane did not confirm the artifact upload")
        elif state != "stored":
            raise ControlPlanePublishError("control plane returned an invalid artifact state")
        return PublishedArtifact(
            artifact_id=artifact_id,
            kind=artifact.kind,
            sha256=artifact.sha256,
            model_release=artifact.model_release,
        )

    def publish_manifest(self, song_id: UUID, manifest: SongManifestV1) -> UUID:
        response = self._request_json(
            "post",
            f"/internal/v1/songs/{song_id}/manifests",
            json=manifest.model_dump(mode="json"),
        )
        try:
            returned = SongManifestV1.model_validate(response.get("manifest"))
        except ValidationError as error:
            raise ControlPlanePublishError("control plane returned an invalid manifest") from error
        if returned != manifest or response.get("song_id") != str(song_id):
            raise ControlPlanePublishError("control plane returned a mismatched manifest")
        return _response_uuid(response, "id", "manifest")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ControlPlanePublisher:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}", **kwargs.pop("headers", {})}
        response = getattr(self._client, method)(path, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            try:
                code = response.json().get("code", "http_error")
            except (TypeError, ValueError):
                code = "http_error"
            raise ControlPlanePublishError(
                f"control plane returned HTTP {response.status_code} ({code})"
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise ControlPlanePublishError("control plane returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise ControlPlanePublishError("control plane returned a non-object response")
        return payload


def _response_uuid(payload: dict[str, Any], field: str, context: str) -> UUID:
    try:
        return UUID(str(payload[field]))
    except (KeyError, TypeError, ValueError) as error:
        raise ControlPlanePublishError(
            f"control plane returned an invalid {context} identifier"
        ) from error

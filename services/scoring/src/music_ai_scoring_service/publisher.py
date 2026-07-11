from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import httpx2
from music_ai_contracts.models import ScoreV1
from pydantic import ValidationError

from music_ai_scoring_service.types import ArchivedEvidence, EvidenceBlob, ScoringComputation


class ScoringPublishError(RuntimeError):
    pass


class ControlPlaneScoringPublisher:
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

    def publish(
        self,
        song_id: UUID,
        manifest_record_id: UUID,
        computation: ScoringComputation,
    ) -> tuple[UUID, list[ArchivedEvidence]]:
        archived = [self._archive(song_id, blob) for blob in computation.evidence]
        response = self._request_json(
            "post",
            "/internal/v1/scores",
            headers={
                "Idempotency-Key": computation.idempotency_key,
                "Reference-Manifest-Id": str(manifest_record_id),
            },
            json=computation.score.model_dump(mode="json"),
        )
        try:
            returned = ScoreV1.model_validate(response.get("score"))
        except ValidationError as error:
            raise ScoringPublishError("control plane returned an invalid score") from error
        if (
            returned != computation.score
            or response.get("song_id") != str(song_id)
            or response.get("manifest_record_id") != str(manifest_record_id)
        ):
            raise ScoringPublishError("control plane returned a mismatched score")
        return _response_uuid(response, "id", "score"), archived

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ControlPlaneScoringPublisher:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _archive(self, song_id: UUID, evidence: EvidenceBlob) -> ArchivedEvidence:
        reservation = self._request_json(
            "post",
            f"/internal/v1/songs/{song_id}/assets",
            json={
                "kind": evidence.kind,
                "sha256": evidence.sha256,
                "byte_length": len(evidence.payload),
                "media_type": "application/json",
                "model_release": evidence.model_release,
            },
        )
        artifact_id = _response_uuid(reservation, "id", "evidence reservation")
        if reservation.get("song_id") != str(song_id) or reservation.get("kind") != evidence.kind:
            raise ScoringPublishError("control plane returned mismatched evidence metadata")
        state = reservation.get("state")
        if state == "pending":
            expected_path = f"/internal/v1/assets/{artifact_id}/content"
            if reservation.get("upload_path") != expected_path:
                raise ScoringPublishError("control plane returned an unexpected evidence path")
            uploaded = self._request_json(
                "put",
                expected_path,
                headers={"Content-Type": "application/json"},
                content=evidence.payload,
            )
            if uploaded.get("id") != str(artifact_id) or uploaded.get("state") != "stored":
                raise ScoringPublishError("control plane did not confirm the evidence upload")
        elif state != "stored":
            raise ScoringPublishError("control plane returned an invalid evidence state")
        return ArchivedEvidence(
            artifact_id=artifact_id,
            kind=evidence.kind,
            sha256=evidence.sha256,
        )

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}", **kwargs.pop("headers", {})}
        try:
            response = getattr(self._client, method)(path, headers=headers, **kwargs)
        except httpx2.RequestError as error:
            raise ScoringPublishError("control plane request failed") from error
        if not 200 <= response.status_code < 300:
            try:
                error_payload = response.json()
            except (TypeError, ValueError):
                error_payload = None
            code = error_payload.get("code") if isinstance(error_payload, dict) else None
            if not isinstance(code, str) or re.fullmatch(r"[a-z0-9_.-]{1,80}", code) is None:
                code = "http_error"
            raise ScoringPublishError(
                f"control plane returned HTTP {response.status_code} ({code})"
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise ScoringPublishError("control plane returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise ScoringPublishError("control plane returned a non-object response")
        return payload


def _response_uuid(payload: dict[str, Any], field: str, context: str) -> UUID:
    try:
        return UUID(str(payload[field]))
    except (KeyError, TypeError, ValueError) as error:
        raise ScoringPublishError(
            f"control plane returned an invalid {context} identifier"
        ) from error

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from ingest_testkit import make_job, make_pipeline
from music_ai_ingest.artifacts import sha256_hex
from music_ai_ingest.publisher import ControlPlanePublisher, ControlPlanePublishError
from music_ai_ingest.types import ArtifactBlob

TOKEN = "publisher-test-token-0123456789abcdef"
SONG_ID = UUID("44444444-4444-4444-8444-444444444444")
ASSET_ID = UUID("55555555-5555-4555-8555-555555555555")


class StubResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class StubClient:
    def __init__(
        self,
        *,
        posts: list[StubResponse] | None = None,
        puts: list[StubResponse] | None = None,
    ) -> None:
        self.posts = deque(posts or [])
        self.puts = deque(puts or [])
        self.calls: list[tuple[str, str]] = []

    def post(self, path: str, **kwargs):
        self.calls.append(("post", path))
        return self.posts.popleft()

    def put(self, path: str, **kwargs):
        self.calls.append(("put", path))
        return self.puts.popleft()


def test_publisher_rejects_short_tokens_and_sanitizes_http_errors() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        ControlPlanePublisher("http://testserver", "short", client=StubClient())

    client = StubClient(
        posts=[StubResponse(409, {"code": "conflict", "message": "provider-secret"})]
    )
    publisher = ControlPlanePublisher("http://testserver", TOKEN, client=client)
    with pytest.raises(ControlPlanePublishError, match=r"HTTP 409 \(conflict\)") as error:
        publisher.publish_artifact(SONG_ID, _artifact())
    assert "provider-secret" not in str(error.value)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (StubResponse(200, ValueError("invalid json")), "invalid JSON"),
        (StubResponse(200, []), "non-object"),
        (
            StubResponse(
                200,
                {"song_id": str(SONG_ID), "kind": "f0", "state": "pending"},
            ),
            "invalid artifact reservation identifier",
        ),
        (
            StubResponse(
                200,
                {
                    "id": str(ASSET_ID),
                    "song_id": str(SONG_ID),
                    "kind": "f0",
                    "state": "pending",
                    "upload_path": "/unexpected",
                },
            ),
            "unexpected artifact path",
        ),
    ],
)
def test_publisher_rejects_malformed_reservations(
    response: StubResponse,
    expected: str,
) -> None:
    publisher = ControlPlanePublisher(
        "http://testserver",
        TOKEN,
        client=StubClient(posts=[response]),
    )
    with pytest.raises(ControlPlanePublishError, match=expected):
        publisher.publish_artifact(SONG_ID, _artifact())


def test_publisher_retry_converges_after_lost_upload_response() -> None:
    pending = StubResponse(
        200,
        {
            "id": str(ASSET_ID),
            "song_id": str(SONG_ID),
            "kind": "f0",
            "state": "pending",
            "upload_path": f"/internal/v1/assets/{ASSET_ID}/content",
        },
    )
    stored = StubResponse(
        200,
        {
            "id": str(ASSET_ID),
            "song_id": str(SONG_ID),
            "kind": "f0",
            "state": "stored",
            "upload_path": None,
        },
    )
    client = StubClient(
        posts=[pending, stored],
        puts=[StubResponse(503, {"code": "unavailable"})],
    )
    publisher = ControlPlanePublisher("http://testserver", TOKEN, client=client)

    with pytest.raises(ControlPlanePublishError, match="HTTP 503"):
        publisher.publish_artifact(SONG_ID, _artifact())
    published = publisher.publish_artifact(SONG_ID, _artifact())

    assert published.artifact_id == ASSET_ID
    assert client.calls == [
        ("post", f"/internal/v1/songs/{SONG_ID}/assets"),
        ("put", f"/internal/v1/assets/{ASSET_ID}/content"),
        ("post", f"/internal/v1/songs/{SONG_ID}/assets"),
    ]


def test_publisher_rejects_invalid_manifest_response(tmp_path: Path) -> None:
    job = make_job()
    pipeline, _, _, _ = make_pipeline(tmp_path, job=job)
    manifest = pipeline.run(job).manifest
    client = StubClient(
        posts=[
            StubResponse(
                200,
                {
                    "id": "not-a-uuid",
                    "song_id": str(job.song_id),
                    "manifest": {"schema_version": "song-manifest.v1"},
                },
            )
        ]
    )
    publisher = ControlPlanePublisher("http://testserver", TOKEN, client=client)

    with pytest.raises(ControlPlanePublishError, match="invalid manifest"):
        publisher.publish_manifest(job.song_id, manifest)


def _artifact() -> ArtifactBlob:
    payload = b"canonical-f0-json"
    return ArtifactBlob(
        kind="f0",
        media_type="application/json",
        payload=payload,
        model_release="f0.test.v1",
        sha256=sha256_hex(payload),
    )

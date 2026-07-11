from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2
import pytest
from music_ai_scoring_service.publisher import (
    ControlPlaneScoringPublisher,
    ScoringPublishError,
)
from scoring_service_testkit import MANIFEST_ID, SONG_ID, make_job, make_pipeline

TOKEN = "scoring-publisher-token-0123456789abcdef"
TRANSPORT_ID = UUID("66666666-6666-4666-8666-666666666666")
FEATURES_ID = UUID("77777777-7777-4777-8777-777777777777")
SCORE_ID = UUID("88888888-8888-4888-8888-888888888888")


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


def test_publisher_rejects_short_tokens_and_sanitizes_http_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 32"):
        ControlPlaneScoringPublisher("http://testserver", "short", client=StubClient())

    computation = _computation(tmp_path)
    client = StubClient(
        posts=[StubResponse(409, {"code": "conflict", "message": "provider-secret"})]
    )
    publisher = ControlPlaneScoringPublisher("http://testserver", TOKEN, client=client)
    with pytest.raises(ScoringPublishError, match=r"HTTP 409 \(conflict\)") as error:
        publisher.publish(SONG_ID, MANIFEST_ID, computation)
    assert "provider-secret" not in str(error.value)

    publisher = ControlPlaneScoringPublisher(
        "http://testserver",
        TOKEN,
        client=StubClient(posts=[StubResponse(503, ["provider-secret"])]),
    )
    with pytest.raises(ScoringPublishError, match=r"HTTP 503 \(http_error\)") as error:
        publisher.publish(SONG_ID, MANIFEST_ID, computation)
    assert "provider-secret" not in str(error.value)

    class FailingClient:
        def post(self, path: str, **kwargs):
            raise httpx2.ConnectError("provider-secret")

    publisher = ControlPlaneScoringPublisher(
        "http://testserver",
        TOKEN,
        client=FailingClient(),
    )
    with pytest.raises(ScoringPublishError, match="request failed") as error:
        publisher.publish(SONG_ID, MANIFEST_ID, computation)
    assert "provider-secret" not in str(error.value)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (StubResponse(200, ValueError("invalid json")), "invalid JSON"),
        (StubResponse(200, []), "non-object"),
        (
            StubResponse(
                200,
                {"song_id": str(SONG_ID), "kind": "transport", "state": "pending"},
            ),
            "invalid evidence reservation identifier",
        ),
        (
            StubResponse(
                200,
                {
                    "id": str(TRANSPORT_ID),
                    "song_id": str(SONG_ID),
                    "kind": "transport",
                    "state": "pending",
                    "upload_path": "/unexpected",
                },
            ),
            "unexpected evidence path",
        ),
    ],
)
def test_publisher_rejects_malformed_evidence_reservations(
    tmp_path: Path,
    response: StubResponse,
    expected: str,
) -> None:
    publisher = ControlPlaneScoringPublisher(
        "http://testserver",
        TOKEN,
        client=StubClient(posts=[response]),
    )
    with pytest.raises(ScoringPublishError, match=expected):
        publisher.publish(SONG_ID, MANIFEST_ID, _computation(tmp_path))


def test_publisher_retry_converges_after_lost_evidence_upload_response(
    tmp_path: Path,
) -> None:
    computation = _computation(tmp_path)
    client = StubClient(
        posts=[
            _pending(TRANSPORT_ID, "transport"),
            _stored(TRANSPORT_ID, "transport"),
            _pending(FEATURES_ID, "user_features"),
            _score_response(computation),
        ],
        puts=[
            StubResponse(503, {"code": "unavailable"}),
            StubResponse(200, {"id": str(FEATURES_ID), "state": "stored"}),
        ],
    )
    publisher = ControlPlaneScoringPublisher("http://testserver", TOKEN, client=client)

    with pytest.raises(ScoringPublishError, match="HTTP 503"):
        publisher.publish(SONG_ID, MANIFEST_ID, computation)
    score_id, evidence = publisher.publish(SONG_ID, MANIFEST_ID, computation)

    assert score_id == SCORE_ID
    assert [item.artifact_id for item in evidence] == [TRANSPORT_ID, FEATURES_ID]
    assert client.calls == [
        ("post", f"/internal/v1/songs/{SONG_ID}/assets"),
        ("put", f"/internal/v1/assets/{TRANSPORT_ID}/content"),
        ("post", f"/internal/v1/songs/{SONG_ID}/assets"),
        ("post", f"/internal/v1/songs/{SONG_ID}/assets"),
        ("put", f"/internal/v1/assets/{FEATURES_ID}/content"),
        ("post", "/internal/v1/scores"),
    ]


def test_publisher_rejects_invalid_or_mismatched_score_response(tmp_path: Path) -> None:
    computation = _computation(tmp_path)
    malformed = StubClient(
        posts=[
            _stored(TRANSPORT_ID, "transport"),
            _stored(FEATURES_ID, "user_features"),
            StubResponse(200, {"id": str(SCORE_ID), "score": {"schema_version": "score.v1"}}),
        ]
    )
    publisher = ControlPlaneScoringPublisher("http://testserver", TOKEN, client=malformed)
    with pytest.raises(ScoringPublishError, match="invalid score"):
        publisher.publish(SONG_ID, MANIFEST_ID, computation)

    mismatch = StubClient(
        posts=[
            _stored(TRANSPORT_ID, "transport"),
            _stored(FEATURES_ID, "user_features"),
            StubResponse(
                200,
                {
                    "id": str(SCORE_ID),
                    "song_id": str(SONG_ID),
                    "manifest_record_id": str(UUID(int=0)),
                    "score": computation.score.model_dump(mode="json"),
                },
            ),
        ]
    )
    publisher = ControlPlaneScoringPublisher("http://testserver", TOKEN, client=mismatch)
    with pytest.raises(ScoringPublishError, match="mismatched score"):
        publisher.publish(SONG_ID, MANIFEST_ID, computation)


def _computation(tmp_path: Path):
    pipeline, _, _ = make_pipeline(tmp_path / "models")
    return pipeline.run(make_job())


def _pending(artifact_id: UUID, kind: str) -> StubResponse:
    return StubResponse(
        200,
        {
            "id": str(artifact_id),
            "song_id": str(SONG_ID),
            "kind": kind,
            "state": "pending",
            "upload_path": f"/internal/v1/assets/{artifact_id}/content",
        },
    )


def _stored(artifact_id: UUID, kind: str) -> StubResponse:
    return StubResponse(
        200,
        {
            "id": str(artifact_id),
            "song_id": str(SONG_ID),
            "kind": kind,
            "state": "stored",
            "upload_path": None,
        },
    )


def _score_response(computation) -> StubResponse:
    return StubResponse(
        200,
        {
            "id": str(SCORE_ID),
            "song_id": str(SONG_ID),
            "manifest_record_id": str(MANIFEST_ID),
            "score": computation.score.model_dump(mode="json"),
        },
    )

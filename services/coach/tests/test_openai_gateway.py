from __future__ import annotations

import os

import pytest
from music_ai_coach.gateways import CoachGatewayError, OpenAIResponsesGateway
from music_ai_coach.types import CoachPlanDraft


class FakeResponse:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.content = b"{}"

    def json(self) -> object:
        return self.payload


class FakeClient:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def completed_response(text: str) -> dict[str, object]:
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }


def request_payload() -> dict[str, object]:
    return {
        "instruction": "Select only an allowed action and correction alias.",
        "request": {
            "state": "corrections",
            "corrections": [{"alias": "c1", "correction_type": "flat"}],
        },
    }


def test_responses_gateway_sends_strict_schema_and_parses_one_output() -> None:
    client = FakeClient(
        FakeResponse(
            completed_response('{"actions":[{"action_type":"slow","correction_alias":"c1"}]}')
        )
    )
    gateway = OpenAIResponsesGateway(
        base_url="https://gateway.example/v1",
        api_key="test-secret-api-key-0123456789",
        model="gpt-test.v1",
        client=client,
        max_output_tokens=128,
    )

    result = gateway.complete(
        request_payload(),
        CoachPlanDraft.model_json_schema(),
        timeout_seconds=3.0,
    )

    assert result == {"actions": [{"action_type": "slow", "correction_alias": "c1"}]}
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://gateway.example/v1/responses"
    assert call["timeout"] == 3.0
    body = call["json"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-test.v1"
    assert body["store"] is False
    assert body["max_output_tokens"] == 128
    schema = body["text"]["format"]["schema"]
    action_schema = schema["$defs"]["CoachDraftAction"]
    assert action_schema["additionalProperties"] is False
    assert action_schema["required"] == ["action_type", "correction_alias"]
    assert "default" not in action_schema["properties"]["correction_alias"]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse({"status": "incomplete", "output": []}), "did not complete"),
        (FakeResponse(completed_response("not-json")), "not valid JSON"),
        (
            FakeResponse(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "refusal", "refusal": "no"}],
                        }
                    ],
                }
            ),
            "refused",
        ),
        (FakeResponse({"error": "provider-secret"}, status_code=503), "HTTP 503"),
        (RuntimeError("provider-secret"), "request failed"),
    ],
)
def test_responses_gateway_fails_closed_without_leaking_provider_details(
    response: FakeResponse | Exception,
    message: str,
) -> None:
    gateway = OpenAIResponsesGateway(
        base_url="https://gateway.example",
        api_key="test-secret-api-key-0123456789",
        model="gpt-test.v1",
        client=FakeClient(response),
    )

    with pytest.raises(CoachGatewayError, match=message) as error:
        gateway.complete(
            request_payload(),
            CoachPlanDraft.model_json_schema(),
            timeout_seconds=2.0,
        )
    assert "provider-secret" not in str(error.value)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://gateway.example/v1",
        "ftp://gateway.example/v1",
        "https://user:secret@gateway.example/v1",
        "https://gateway.example/v1?token=secret",
    ],
)
def test_responses_gateway_rejects_unsafe_base_urls(base_url: str) -> None:
    with pytest.raises(ValueError, match="base URL"):
        OpenAIResponsesGateway(
            base_url=base_url,
            api_key="test-secret-api-key-0123456789",
            model="gpt-test.v1",
            client=FakeClient(FakeResponse({})),
        )


LIVE_BASE_URL = os.getenv("MUSIC_AI_LIVE_COACH_BASE_URL")
LIVE_API_KEY = os.getenv("MUSIC_AI_LIVE_COACH_API_KEY")
LIVE_MODEL = os.getenv("MUSIC_AI_LIVE_COACH_MODEL")


@pytest.mark.skipif(
    not all((LIVE_BASE_URL, LIVE_API_KEY, LIVE_MODEL)),
    reason="live coach gateway credentials are not configured",
)
def test_responses_gateway_live_structured_output() -> None:
    assert LIVE_BASE_URL is not None
    assert LIVE_API_KEY is not None
    assert LIVE_MODEL is not None
    with OpenAIResponsesGateway(
        base_url=LIVE_BASE_URL,
        api_key=LIVE_API_KEY,
        model=LIVE_MODEL,
        max_output_tokens=128,
    ) as gateway:
        result = gateway.complete(
            request_payload(),
            CoachPlanDraft.model_json_schema(),
            timeout_seconds=30.0,
        )
    assert CoachPlanDraft.model_validate(result).actions

from __future__ import annotations

import json

import pytest
from coach_testkit import make_job
from music_ai_coach.providers import CoachProviderError, GatewayCoachProvider
from music_ai_coach.service import CoachService


class CaptureGateway:
    def __init__(self, response) -> None:
        self.response = response
        self.payload = None
        self.schema = None
        self.timeout_seconds = None

    def complete(self, payload, output_schema, *, timeout_seconds):
        self.payload = payload
        self.schema = output_schema
        self.timeout_seconds = timeout_seconds
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_gateway_receives_only_pseudonymous_structured_score_facts() -> None:
    gateway = CaptureGateway(
        {"actions": [{"action_type": "slow", "correction_alias": "c1"}]}
    )
    provider = GatewayCoachProvider("llm.gateway.v1", gateway)
    job = make_job()

    result = CoachService(primary_provider=provider).coach(job)

    assert result.provider == provider.name
    encoded = json.dumps(gateway.payload, sort_keys=True)
    assert str(job.score.tenant_id) not in encoded
    assert str(job.score.session_id) not in encoded
    assert str(job.score.phrase_id) not in encoded
    assert str(job.score.song_id) not in encoded
    assert str(job.score.corrections[0].correction_id) not in encoded
    assert "source_audio" not in encoded
    assert "transport" not in encoded
    assert "start_sample" not in encoded
    assert "end_sample" not in encoded
    assert "c1" in encoded
    assert gateway.schema["additionalProperties"] is False
    assert gateway.timeout_seconds == 10.0


@pytest.mark.parametrize(
    "response",
    [
        {"actions": []},
        {"actions": [{"action_type": "slow", "correction_alias": "c1", "extra": True}]},
        TimeoutError("provider-secret"),
        RuntimeError("network-provider-secret"),
    ],
)
def test_gateway_wraps_malformed_or_timed_out_responses(response) -> None:
    gateway = CaptureGateway(response)
    provider = GatewayCoachProvider("llm.gateway.v1", gateway)

    with pytest.raises(CoachProviderError, match="structured coach provider failed") as error:
        provider.propose(CoachService()._request(make_job(), make_job().score.corrections)[0])
    assert "provider-secret" not in str(error.value)

from __future__ import annotations

import copy
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx2


class CoachGatewayError(RuntimeError):
    pass


class OpenAIResponsesGateway:
    """Strict JSON-schema gateway for OpenAI-compatible Responses APIs."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        client: Any | None = None,
        max_output_tokens: int = 512,
    ) -> None:
        self.endpoint_url = _responses_endpoint(base_url)
        if not 20 <= len(api_key) <= 2_048 or any(character.isspace() for character in api_key):
            raise ValueError("coach API key must contain 20 to 2048 non-whitespace characters")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model) is None:
            raise ValueError("coach model identifier is invalid")
        if not 64 <= max_output_tokens <= 2_048:
            raise ValueError("coach max output tokens must be between 64 and 2048")
        self._api_key = api_key
        self._model = model
        self._client = client or httpx2.Client()
        self._owns_client = client is None
        self._max_output_tokens = max_output_tokens

    def complete(
        self,
        payload: dict[str, Any],
        output_schema: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> object:
        instruction = payload.get("instruction")
        request = payload.get("request")
        if not isinstance(instruction, str) or not instruction.strip():
            raise CoachGatewayError("coach gateway instruction is missing")
        if not isinstance(request, dict):
            raise CoachGatewayError("coach gateway request is invalid")

        request_payload = {
            "model": self._model,
            "input": [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": instruction}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                request,
                                ensure_ascii=True,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "music_ai_coach_plan",
                    "strict": True,
                    "schema": _strict_json_schema(output_schema),
                }
            },
            "max_output_tokens": self._max_output_tokens,
            "store": False,
        }
        try:
            response = self._client.post(
                self.endpoint_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=timeout_seconds,
            )
        except Exception as error:
            raise CoachGatewayError("coach gateway request failed") from error

        if not 200 <= response.status_code < 300:
            raise CoachGatewayError(f"coach gateway returned HTTP {response.status_code}")
        response_body = response.content
        if len(response_body) > 1_000_000:
            raise CoachGatewayError("coach gateway response exceeded the size limit")
        try:
            response_payload = response.json()
        except (TypeError, ValueError) as error:
            raise CoachGatewayError("coach gateway returned invalid JSON") from error
        return _parse_output(response_payload)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenAIResponsesGateway:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def _responses_endpoint(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("coach base URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("coach base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("coach base URL must not contain a query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("coach base URL must use HTTPS outside localhost")
    return f"{base_url.rstrip('/')}/responses"


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(schema)

    def visit(value: object) -> None:
        if isinstance(value, dict):
            value.pop("default", None)
            properties = value.get("properties")
            if value.get("type") == "object" and isinstance(properties, dict):
                value["additionalProperties"] = False
                value["required"] = list(properties)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(normalized)
    return normalized


def _parse_output(response: object) -> object:
    if not isinstance(response, dict) or response.get("status") != "completed":
        raise CoachGatewayError("coach gateway did not complete")
    output = response.get("output")
    if not isinstance(output, list):
        raise CoachGatewayError("coach gateway response has no output")

    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "refusal" or part.get("refusal"):
                raise CoachGatewayError("coach gateway refused the request")
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
    if len(texts) != 1:
        raise CoachGatewayError("coach gateway returned an ambiguous output")
    try:
        return json.loads(texts[0])
    except (TypeError, ValueError) as error:
        raise CoachGatewayError("coach gateway output was not valid JSON") from error

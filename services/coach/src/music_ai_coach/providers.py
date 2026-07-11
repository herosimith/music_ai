from __future__ import annotations

from typing import Any, Protocol

from music_ai_coach.types import (
    CoachDraftAction,
    CoachExercise,
    CoachingState,
    CoachPlanDraft,
    CoachProviderRequest,
)


class CoachProviderError(RuntimeError):
    pass


class CoachProvider(Protocol):
    name: str

    def propose(self, request: CoachProviderRequest) -> CoachPlanDraft: ...


class StructuredCoachGateway(Protocol):
    def complete(
        self,
        payload: dict[str, Any],
        output_schema: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> object: ...


class RuleCoachProvider:
    name = "rules.v1"

    def propose(self, request: CoachProviderRequest) -> CoachPlanDraft:
        if request.state != CoachingState.CORRECTIONS:
            return CoachPlanDraft(
                actions=[CoachDraftAction(action_type=CoachExercise.TEXT)]
            )
        actions: list[CoachDraftAction] = []
        for correction in request.corrections[: request.max_actions]:
            if (
                correction.correction_type.value == "missed"
                and correction.reference is not None
                and correction.reference.unit == "hertz"
                and request.reference_tone_min_hz
                <= correction.reference.value
                <= request.reference_tone_max_hz
            ):
                exercise = CoachExercise.REFERENCE_TONE
            elif correction.correction_type.value in {"short", "long"}:
                exercise = CoachExercise.LOOP
            else:
                exercise = CoachExercise.SLOW
            actions.append(
                CoachDraftAction(
                    action_type=exercise,
                    correction_alias=correction.alias,
                )
            )
        return CoachPlanDraft(actions=actions)


class GatewayCoachProvider:
    def __init__(
        self,
        name: str,
        gateway: StructuredCoachGateway,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not name or len(name) > 80:
            raise ValueError("coach provider name must contain 1 to 80 characters")
        if not 0.1 <= timeout_seconds <= 30.0:
            raise ValueError("coach provider timeout must be between 0.1 and 30 seconds")
        self.name = name
        self.gateway = gateway
        self.timeout_seconds = timeout_seconds

    def propose(self, request: CoachProviderRequest) -> CoachPlanDraft:
        payload = {
            "instruction": (
                "Select only correction aliases and action types from this JSON. "
                "Do not add prose, parameters, identities, scores, health claims, or fields."
            ),
            "request": request.model_dump(mode="json"),
        }
        try:
            response = self.gateway.complete(
                payload,
                CoachPlanDraft.model_json_schema(),
                timeout_seconds=self.timeout_seconds,
            )
            return CoachPlanDraft.model_validate(response)
        except Exception as error:
            raise CoachProviderError("structured coach provider failed") from error

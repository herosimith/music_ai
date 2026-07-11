from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID, uuid5

from music_ai_contracts.models import CoachActionV1, CorrectionEventV1, ScoreV1

from music_ai_coach.policy import (
    DEFAULT_POLICY,
    CoachPolicy,
    CoachPolicyAuthorizationError,
    require_approved_policy,
)
from music_ai_coach.providers import CoachProvider, RuleCoachProvider
from music_ai_coach.rendering import abstained_message, clear_message, correction_message
from music_ai_coach.types import (
    CoachDraftAction,
    CoachEvidenceItem,
    CoachExercise,
    CoachingState,
    CoachJob,
    CoachPlanDraft,
    CoachProviderRequest,
    CoachResult,
    PromptMetric,
)

COACH_NAMESPACE = UUID("755294d1-60ea-58b6-a3ab-48e444e1af0d")


class CoachServiceError(RuntimeError):
    pass


class CoachService:
    def __init__(
        self,
        *,
        primary_provider: CoachProvider | None = None,
        fallback_provider: CoachProvider | None = None,
        policy: CoachPolicy = DEFAULT_POLICY,
    ) -> None:
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider or RuleCoachProvider()
        self.policy = policy

    def coach(self, job: CoachJob) -> CoachResult:
        try:
            require_approved_policy(self.policy)
        except CoachPolicyAuthorizationError as error:
            raise CoachServiceError(str(error)) from error

        score_sha256 = canonical_score_sha256(job.score)
        selected = self._prioritize(job.score)
        request, corrections_by_alias = self._request(job, selected)
        provider = self.fallback_provider
        used_fallback = False

        if self.primary_provider is not None and request.state == CoachingState.CORRECTIONS:
            try:
                actions = self._run_provider(
                    self.primary_provider,
                    request,
                    corrections_by_alias,
                    job,
                    score_sha256,
                )
                provider = self.primary_provider
            except Exception:
                used_fallback = True
                actions = self._run_fallback(
                    request,
                    corrections_by_alias,
                    job,
                    score_sha256,
                )
        else:
            actions = self._run_fallback(
                request,
                corrections_by_alias,
                job,
                score_sha256,
            )

        return CoachResult(
            actions=actions,
            provider=_provider_name(provider),
            used_fallback=used_fallback,
            source_score_sha256=score_sha256,
        )

    def _run_fallback(
        self,
        request: CoachProviderRequest,
        corrections_by_alias: dict[str, CorrectionEventV1],
        job: CoachJob,
        score_sha256: str,
    ) -> list[CoachActionV1]:
        try:
            return self._run_provider(
                self.fallback_provider,
                request,
                corrections_by_alias,
                job,
                score_sha256,
            )
        except Exception as error:
            raise CoachServiceError("deterministic coach fallback failed") from error

    def _run_provider(
        self,
        provider: CoachProvider,
        request: CoachProviderRequest,
        corrections_by_alias: dict[str, CorrectionEventV1],
        job: CoachJob,
        score_sha256: str,
    ) -> list[CoachActionV1]:
        provider_name = _provider_name(provider)
        plan = CoachPlanDraft.model_validate(provider.propose(request))
        self._validate_plan(plan, request, corrections_by_alias)
        return self._build_actions(
            plan,
            request,
            corrections_by_alias,
            job,
            score_sha256,
            provider_name,
        )

    def _prioritize(self, score: ScoreV1) -> list[CorrectionEventV1]:
        priority = {
            correction_type: len(self.policy.correction_priority) - index
            for index, correction_type in enumerate(self.policy.correction_priority)
        }
        ordered = sorted(
            score.corrections,
            key=lambda correction: (
                -correction.severity,
                -(correction.confidence * correction.reference_confidence),
                -priority[correction.correction_type.value],
                correction.start_sample,
                str(correction.correction_id),
            ),
        )
        return ordered[: self.policy.max_actions]

    def _request(
        self,
        job: CoachJob,
        selected: list[CorrectionEventV1],
    ) -> tuple[CoachProviderRequest, dict[str, CorrectionEventV1]]:
        if job.score.abstained_reason is not None:
            state = CoachingState.ABSTAINED
        elif selected:
            state = CoachingState.CORRECTIONS
        else:
            state = CoachingState.CLEAR
        corrections_by_alias = {
            f"c{index}": correction for index, correction in enumerate(selected, start=1)
        }
        evidence = [
            CoachEvidenceItem(
                alias=alias,
                correction_type=correction.correction_type,
                severity=correction.severity,
                confidence=correction.confidence,
                reference_confidence=correction.reference_confidence,
                observed=_prompt_metric(correction.observed),
                reference=_prompt_metric(correction.reference),
            )
            for alias, correction in corrections_by_alias.items()
        ]
        if state != CoachingState.CORRECTIONS:
            corrections_by_alias = {}
            evidence = []
        request = CoachProviderRequest(
            state=state,
            locale=job.locale,
            abstained_reason=(
                job.score.abstained_reason if state == CoachingState.ABSTAINED else None
            ),
            allowed_actions=tuple(
                CoachExercise(action) for action in self.policy.allowed_actions
            ),
            max_actions=self.policy.max_actions,
            reference_tone_min_hz=self.policy.reference_tone_min_hz,
            reference_tone_max_hz=self.policy.reference_tone_max_hz,
            corrections=evidence,
        )
        return request, corrections_by_alias

    def _validate_plan(
        self,
        plan: CoachPlanDraft,
        request: CoachProviderRequest,
        corrections_by_alias: dict[str, CorrectionEventV1],
    ) -> None:
        if len(plan.actions) > request.max_actions:
            raise ValueError("coach provider exceeded the action limit")
        allowed = set(request.allowed_actions)
        if any(action.action_type not in allowed for action in plan.actions):
            raise ValueError("coach provider selected an unapproved action")
        if request.state != CoachingState.CORRECTIONS:
            if len(plan.actions) != 1 or plan.actions[0] != CoachDraftAction(
                action_type=CoachExercise.TEXT
            ):
                raise ValueError("non-correction coaching permits one text action")
            return
        for action in plan.actions:
            if action.correction_alias not in corrections_by_alias:
                raise ValueError("coach provider fabricated a correction alias")
            correction = corrections_by_alias[action.correction_alias]
            if action.action_type == CoachExercise.REFERENCE_TONE:
                reference = correction.reference
                if (
                    reference is None
                    or reference.unit != "hertz"
                    or not self.policy.reference_tone_min_hz
                    <= reference.value
                    <= self.policy.reference_tone_max_hz
                ):
                    raise ValueError("reference tone lacks an approved hertz fact")

    def _build_actions(
        self,
        plan: CoachPlanDraft,
        request: CoachProviderRequest,
        corrections_by_alias: dict[str, CorrectionEventV1],
        job: CoachJob,
        score_sha256: str,
        provider_name: str,
    ) -> list[CoachActionV1]:
        built: list[CoachActionV1] = []
        for ordinal, draft in enumerate(plan.actions):
            correction = (
                corrections_by_alias[draft.correction_alias]
                if draft.correction_alias is not None
                else None
            )
            arguments = self._arguments(draft.action_type, correction)
            message = self._message(request, draft.action_type, correction)
            source_ids = sorted(
                [correction.correction_id] if correction is not None else [],
                key=str,
            )
            action_id = _action_id(
                score_sha256=score_sha256,
                policy_fingerprint=self.policy.fingerprint(),
                provider=provider_name,
                locale=job.locale,
                action_type=draft.action_type,
                source_correction_ids=source_ids,
                arguments=arguments,
                produced_at=job.produced_at.isoformat(),
                ordinal=ordinal,
            )
            action = CoachActionV1.model_validate(
                {
                    "schema_version": "coach-action.v1",
                    "tenant_id": str(job.score.tenant_id),
                    "action_id": str(action_id),
                    "session_id": str(job.score.session_id),
                    "phrase_id": str(job.score.phrase_id),
                    "source_score_sha256": score_sha256,
                    "source_correction_ids": [str(identity) for identity in source_ids],
                    "action_type": draft.action_type.value,
                    "message": message,
                    "arguments": arguments,
                    "locale": job.locale,
                    "provider": provider_name,
                    "coach_version": self.policy.coach_version,
                    "score_version": job.score.versions.score_version,
                    "produced_at": job.produced_at.isoformat(),
                }
            )
            built.append(action)
        return built

    def _arguments(
        self,
        exercise: CoachExercise,
        correction: CorrectionEventV1 | None,
    ) -> dict[str, object]:
        if exercise == CoachExercise.TEXT:
            return {}
        if correction is None:
            raise ValueError("exercise actions require correction evidence")
        if exercise == CoachExercise.LOOP:
            return {
                "start_sample": correction.start_sample,
                "end_sample": correction.end_sample,
                "repetitions": self.policy.loop_repetitions,
            }
        if exercise == CoachExercise.SLOW:
            return {
                "start_sample": correction.start_sample,
                "end_sample": correction.end_sample,
                "speed": self.policy.slow_speed,
            }
        reference = correction.reference
        if reference is None or reference.unit != "hertz":
            raise ValueError("reference tone requires an exact hertz fact")
        return {
            "f0_hz": reference.value,
            "duration_ms": self.policy.reference_tone_duration_ms,
        }

    def _message(
        self,
        request: CoachProviderRequest,
        exercise: CoachExercise,
        correction: CorrectionEventV1 | None,
    ) -> str:
        if request.state == CoachingState.ABSTAINED:
            return abstained_message(request.abstained_reason or "unknown", request.locale)
        if request.state == CoachingState.CLEAR:
            return clear_message(request.locale)
        if correction is None:
            raise ValueError("correction coaching requires an evidence fact")
        return correction_message(correction, exercise, request.locale)


def canonical_score_sha256(score: ScoreV1) -> str:
    payload = json.dumps(
        score.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _prompt_metric(metric) -> PromptMetric | None:
    if metric is None:
        return None
    return PromptMetric(
        value=metric.value,
        unit=metric.unit,
        confidence=metric.confidence,
    )


def _provider_name(provider: CoachProvider) -> str:
    name = getattr(provider, "name", None)
    if not isinstance(name, str) or re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,79}", name) is None:
        raise ValueError("coach provider has an invalid name")
    return name


def _action_id(
    *,
    score_sha256: str,
    policy_fingerprint: str,
    provider: str,
    locale: str,
    action_type: CoachExercise,
    source_correction_ids: list[UUID],
    arguments: dict[str, object],
    produced_at: str,
    ordinal: int,
) -> UUID:
    identity = json.dumps(
        {
            "score_sha256": score_sha256,
            "policy_fingerprint": policy_fingerprint,
            "provider": provider,
            "locale": locale,
            "action_type": action_type.value,
            "source_correction_ids": [str(identity) for identity in source_correction_ids],
            "arguments": arguments,
            "produced_at": produced_at,
            "ordinal": ordinal,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return uuid5(COACH_NAMESPACE, identity)

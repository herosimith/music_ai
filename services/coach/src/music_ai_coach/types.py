from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from music_ai_contracts.models import CoachActionV1, CorrectionType, ScoreV1
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
ProviderName = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{1,79}$"),
]
CorrectionAlias = Annotated[str, StringConstraints(pattern=r"^c[1-9][0-9]?$", max_length=3)]
Locale = Literal["zh-CN", "en"]
MetricUnit = Literal["cents", "milliseconds", "ratio", "hertz", "semitones"]


class InternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CoachExercise(StrEnum):
    LOOP = "loop"
    SLOW = "slow"
    REFERENCE_TONE = "reference_tone"
    TEXT = "text"


class CoachingState(StrEnum):
    CORRECTIONS = "corrections"
    ABSTAINED = "abstained"
    CLEAR = "clear"


class CoachJob(InternalModel):
    score: ScoreV1
    locale: Locale = "zh-CN"
    produced_at: AwareDatetime

    @model_validator(mode="after")
    def validate_time(self) -> CoachJob:
        if self.produced_at < self.score.produced_at:
            raise ValueError("coach output cannot predate its source score")
        return self


class PromptMetric(InternalModel):
    value: float = Field(allow_inf_nan=False)
    unit: MetricUnit
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


class CoachEvidenceItem(InternalModel):
    alias: CorrectionAlias
    correction_type: CorrectionType
    severity: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    reference_confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    observed: PromptMetric | None = None
    reference: PromptMetric | None = None


class CoachProviderRequest(InternalModel):
    state: CoachingState
    locale: Locale
    abstained_reason: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9_.-]+$", max_length=120),
    ] | None = None
    allowed_actions: tuple[CoachExercise, ...]
    max_actions: int = Field(ge=1, le=8)
    reference_tone_min_hz: float = Field(ge=55.0, le=1_100.0, allow_inf_nan=False)
    reference_tone_max_hz: float = Field(ge=55.0, le=1_100.0, allow_inf_nan=False)
    corrections: list[CoachEvidenceItem] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_state(self) -> CoachProviderRequest:
        aliases = [item.alias for item in self.corrections]
        if aliases != sorted(set(aliases)):
            raise ValueError("coach correction aliases must be unique and sorted")
        if self.state == CoachingState.CORRECTIONS:
            if not self.corrections or self.abstained_reason is not None:
                raise ValueError("correction coaching requires evidence and no abstention")
        elif self.corrections:
            raise ValueError("non-correction coaching cannot expose correction evidence")
        if self.state == CoachingState.ABSTAINED and self.abstained_reason is None:
            raise ValueError("abstained coaching requires a reason")
        if self.state != CoachingState.ABSTAINED and self.abstained_reason is not None:
            raise ValueError("only abstained coaching may contain an abstention reason")
        if self.reference_tone_min_hz >= self.reference_tone_max_hz:
            raise ValueError("reference tone bounds must be increasing")
        return self


class CoachDraftAction(InternalModel):
    action_type: CoachExercise
    correction_alias: CorrectionAlias | None = None

    @model_validator(mode="after")
    def validate_alias(self) -> CoachDraftAction:
        if self.action_type != CoachExercise.TEXT and self.correction_alias is None:
            raise ValueError("exercise actions require a correction alias")
        return self


class CoachPlanDraft(InternalModel):
    actions: list[CoachDraftAction] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_actions(self) -> CoachPlanDraft:
        identities = [
            (action.action_type, action.correction_alias)
            for action in self.actions
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("coach draft actions must be unique")
        aliases = [
            action.correction_alias
            for action in self.actions
            if action.correction_alias is not None
        ]
        if len(aliases) != len(set(aliases)):
            raise ValueError("a correction may be coached only once per response")
        return self


class CoachResult(InternalModel):
    actions: list[CoachActionV1] = Field(min_length=1, max_length=8)
    provider: ProviderName
    used_fallback: bool
    source_score_sha256: Sha256

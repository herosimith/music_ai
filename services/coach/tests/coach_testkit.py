from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from music_ai_coach.types import CoachJob
from music_ai_contracts.models import (
    CorrectionEventV1,
    CorrectionType,
    NumericMetric,
    ScoreV1,
)

REPOSITORY_ROOT = Path(__file__).parents[3]
PRODUCED_AT = datetime(2026, 7, 11, 4, 0, 9, tzinfo=UTC)


def make_score(
    *,
    corrections: list[CorrectionEventV1] | None = None,
    abstained_reason: str | None = None,
) -> ScoreV1:
    data = json.loads(
        (REPOSITORY_ROOT / "packages/contracts/examples/score.v1.json").read_text(
            encoding="utf-8"
        )
    )
    if abstained_reason is not None:
        data.update(
            {
                "scored_coverage": 0.0,
                "metrics": {},
                "corrections": [],
                "abstained_reason": abstained_reason,
            }
        )
    elif corrections is not None:
        data["corrections"] = [correction.model_dump(mode="json") for correction in corrections]
    return ScoreV1.model_validate(data)


def make_correction(
    correction_type: CorrectionType,
    *,
    identity: int,
    severity: float = 0.5,
    confidence: float = 0.9,
    reference_confidence: float = 0.95,
    observed_value: float | None = -32.0,
    observed_unit: str = "cents",
    reference_value: float | None = 0.0,
    reference_unit: str = "cents",
    start_sample: int = 864_000,
    end_sample: int = 912_000,
) -> CorrectionEventV1:
    score = make_score()
    return CorrectionEventV1(
        schema_version="correction-event.v1",
        tenant_id=score.tenant_id,
        session_id=score.session_id,
        phrase_id=score.phrase_id,
        correction_id=UUID(f"{identity:08x}-0000-4000-8000-{identity:012x}"),
        correction_type=correction_type,
        start_sample=start_sample,
        end_sample=end_sample,
        severity=severity,
        confidence=confidence,
        reference_confidence=reference_confidence,
        observed=(
            NumericMetric(
                value=observed_value,
                unit=observed_unit,
                confidence=confidence,
                coverage=0.9,
            )
            if observed_value is not None
            else None
        ),
        reference=(
            NumericMetric(
                value=reference_value,
                unit=reference_unit,
                confidence=reference_confidence,
                coverage=1.0,
            )
            if reference_value is not None
            else None
        ),
        evidence=[
            {
                "artifact_id": "reference:test",
                "start_sample": start_sample,
                "end_sample": end_sample,
            }
        ],
        score_version=score.versions.score_version,
        produced_at=score.produced_at,
    )


def make_job(score: ScoreV1 | None = None, *, locale: str = "zh-CN") -> CoachJob:
    return CoachJob(
        score=score or make_score(),
        locale=locale,
        produced_at=PRODUCED_AT,
    )

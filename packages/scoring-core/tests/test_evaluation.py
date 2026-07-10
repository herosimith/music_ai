from __future__ import annotations

import pytest
from music_ai_contracts.models import CorrectionType
from music_ai_scoring import LabeledCorrection, evaluate_corrections, score_phrase, wilson_interval
from scoring_testkit import PRODUCED_AT, make_features, make_manifest


def sharp_correction():
    score = score_phrase(
        make_manifest(),
        make_features(cents=100.0),
        produced_at=PRODUCED_AT,
    )
    return next(
        event for event in score.corrections if event.correction_type == CorrectionType.SHARP
    )


def test_evaluation_reports_precision_recall_coverage_and_severe_misses() -> None:
    predicted = [sharp_correction()]
    gold = [
        LabeledCorrection(CorrectionType.SHARP, 48_000, 96_000, severe=True),
        LabeledCorrection(CorrectionType.LATE, 100_000, 110_000, severe=False),
    ]

    result = evaluate_corrections(
        predicted,
        gold,
        concluded_events=1,
        eligible_events=2,
    )

    assert result.true_positives == 1
    assert result.false_positives == 0
    assert result.false_negatives == 1
    assert result.severe_false_negatives == 0
    assert result.precision == 1.0
    assert result.recall == 0.5
    assert result.event_coverage == 0.5
    assert result.precision_wilson_low < result.precision <= result.precision_wilson_high


def test_maximum_matching_does_not_depend_on_greedy_prediction_order() -> None:
    base = sharp_correction()
    predicted = [
        base.model_copy(update={"start_sample": 0, "end_sample": 150}),
        base.model_copy(update={"start_sample": 20, "end_sample": 100}),
    ]
    gold = [
        LabeledCorrection(CorrectionType.SHARP, 0, 100),
        LabeledCorrection(CorrectionType.SHARP, 50, 150),
    ]

    result = evaluate_corrections(
        predicted,
        gold,
        concluded_events=2,
        eligible_events=2,
    )
    assert result.true_positives == 2
    assert result.precision == 1.0
    assert result.recall == 1.0


def test_iou_threshold_is_inclusive() -> None:
    prediction = sharp_correction().model_copy(update={"start_sample": 0, "end_sample": 100})
    gold = [LabeledCorrection(CorrectionType.SHARP, 0, 200)]

    result = evaluate_corrections(
        [prediction],
        gold,
        concluded_events=1,
        eligible_events=1,
        min_iou=0.5,
    )
    assert result.true_positives == 1


def test_multiple_gold_corrections_can_belong_to_one_eligible_note() -> None:
    result = evaluate_corrections(
        [],
        [
            LabeledCorrection(CorrectionType.SHARP, 0, 100, severe=True),
            LabeledCorrection(CorrectionType.LATE, 0, 100),
        ],
        concluded_events=0,
        eligible_events=1,
    )
    assert result.false_negatives == 2
    assert result.severe_miss_rate == 1.0
    assert result.event_coverage == 0.0


def test_abstention_cannot_hide_a_severe_false_negative() -> None:
    result = evaluate_corrections(
        [],
        [LabeledCorrection(CorrectionType.OCTAVE_ERROR, 0, 9_600, severe=True)],
        concluded_events=0,
        eligible_events=1,
    )
    assert result.severe_false_negatives == 1
    assert result.severe_miss_rate == 1.0
    assert result.precision_wilson_low == 0.0
    assert result.precision_wilson_high == 1.0


def test_wilson_interval_matches_reference_values() -> None:
    low, high = wilson_interval(80, 100)
    assert low == pytest.approx(0.7112, abs=0.0001)
    assert high == pytest.approx(0.8666, abs=0.0001)


@pytest.mark.parametrize(
    ("concluded", "eligible", "min_iou"),
    [(-1, 1, 0.5), (2, 1, 0.5), (0, -1, 0.5), (0, 1, 0.0), (0, 1, 1.1)],
)
def test_evaluation_rejects_invalid_denominators(
    concluded: int,
    eligible: int,
    min_iou: float,
) -> None:
    with pytest.raises(ValueError):
        evaluate_corrections(
            [],
            [],
            concluded_events=concluded,
            eligible_events=eligible,
            min_iou=min_iou,
        )


@pytest.mark.parametrize("successes,total", [(-1, 1), (2, 1), (0, -1)])
def test_wilson_interval_rejects_invalid_counts(successes: int, total: int) -> None:
    with pytest.raises(ValueError):
        wilson_interval(successes, total)


@pytest.mark.parametrize("z", [0.0, -1.0, float("nan"), float("inf")])
def test_wilson_interval_rejects_invalid_z(z: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        wilson_interval(1, 1, z)

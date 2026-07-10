from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from music_ai_contracts.models import CorrectionEventV1, CorrectionType


@dataclass(frozen=True, slots=True)
class LabeledCorrection:
    correction_type: CorrectionType
    start_sample: int
    end_sample: int
    severe: bool = False

    def __post_init__(self) -> None:
        if self.start_sample < 0 or self.end_sample <= self.start_sample:
            raise ValueError("labeled correction has an invalid sample range")


@dataclass(frozen=True, slots=True)
class EventEvaluation:
    true_positives: int
    false_positives: int
    false_negatives: int
    severe_false_negatives: int
    emitted_corrections: int
    concluded_events: int
    eligible_events: int
    precision: float
    recall: float
    event_coverage: float
    severe_miss_rate: float
    precision_wilson_low: float
    precision_wilson_high: float


def evaluate_corrections(
    predicted: list[CorrectionEventV1],
    gold: list[LabeledCorrection],
    *,
    concluded_events: int,
    eligible_events: int,
    min_iou: float = 0.5,
) -> EventEvaluation:
    if not 0 <= concluded_events <= eligible_events:
        raise ValueError("concluded_events must be between zero and eligible_events")
    if not 0 < min_iou <= 1:
        raise ValueError("min_iou must be in (0, 1]")

    ordered_predictions = sorted(
        predicted,
        key=lambda item: (
            item.start_sample,
            item.end_sample,
            item.correction_type.value,
            str(item.correction_id),
        ),
    )
    adjacency: list[list[int]] = []
    for event in ordered_predictions:
        candidates = [
            (index, _iou(event.start_sample, event.end_sample, item.start_sample, item.end_sample))
            for index, item in enumerate(gold)
            if item.correction_type == event.correction_type
        ]
        adjacency.append(
            [
                index
                for index, overlap in sorted(candidates, key=lambda item: (-item[1], item[0]))
                if overlap >= min_iou
            ]
        )

    matched_gold_to_prediction: dict[int, int] = {}
    matched_prediction_to_gold: dict[int, int] = {}

    def assign(start_prediction: int) -> bool:
        pending = deque([start_prediction])
        seen_predictions = {start_prediction}
        parent_gold: dict[int, int] = {}
        while pending:
            prediction_index = pending.popleft()
            for gold_index in adjacency[prediction_index]:
                if gold_index in parent_gold:
                    continue
                parent_gold[gold_index] = prediction_index
                previous_prediction = matched_gold_to_prediction.get(gold_index)
                if previous_prediction is not None:
                    if previous_prediction not in seen_predictions:
                        seen_predictions.add(previous_prediction)
                        pending.append(previous_prediction)
                    continue

                current_gold: int | None = gold_index
                while current_gold is not None:
                    current_prediction = parent_gold[current_gold]
                    previous_gold = matched_prediction_to_gold.get(current_prediction)
                    matched_gold_to_prediction[current_gold] = current_prediction
                    matched_prediction_to_gold[current_prediction] = current_gold
                    current_gold = previous_gold
                return True
        return False

    for prediction_index in range(len(ordered_predictions)):
        assign(prediction_index)

    matched_gold = set(matched_gold_to_prediction)
    true_positives = len(matched_gold)
    unmatched = set(range(len(gold))) - matched_gold

    false_positives = len(predicted) - true_positives
    false_negatives = len(unmatched)
    severe_total = sum(item.severe for item in gold)
    severe_false_negatives = sum(gold[index].severe for index in unmatched)
    precision = true_positives / len(predicted) if predicted else 0.0
    recall = true_positives / len(gold) if gold else 1.0
    coverage = concluded_events / eligible_events if eligible_events else 0.0
    severe_miss_rate = severe_false_negatives / severe_total if severe_total else 0.0
    low, high = wilson_interval(true_positives, len(predicted))
    return EventEvaluation(
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        severe_false_negatives=severe_false_negatives,
        emitted_corrections=len(predicted),
        concluded_events=concluded_events,
        eligible_events=eligible_events,
        precision=precision,
        recall=recall,
        event_coverage=coverage,
        severe_miss_rate=severe_miss_rate,
        precision_wilson_low=low,
        precision_wilson_high=high,
    )


def wilson_interval(
    successes: int,
    total: int,
    z: float = 1.959963984540054,
) -> tuple[float, float]:
    if successes < 0 or total < 0 or successes > total:
        raise ValueError("invalid binomial counts")
    if not math.isfinite(z) or z <= 0:
        raise ValueError("z must be finite and positive")
    if total == 0:
        return 0.0, 1.0
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = (
        z * math.sqrt((proportion * (1 - proportion) + z**2 / (4 * total)) / total) / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _iou(start_a: int, end_a: int, start_b: int, end_b: int) -> float:
    intersection = max(0, min(end_a, end_b) - max(start_a, start_b))
    union = max(end_a, end_b) - min(start_a, start_b)
    return intersection / union if union else 0.0

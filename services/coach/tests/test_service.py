from __future__ import annotations

import pytest
from coach_testkit import make_correction, make_job, make_score
from music_ai_coach.providers import RuleCoachProvider
from music_ai_coach.service import CoachService, canonical_score_sha256
from music_ai_contracts.models import CorrectionType


class FixtureProvider:
    name = "llm.fixture.v1"

    def __init__(self, response) -> None:
        self.response = response
        self.calls = 0

    def propose(self, request):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        if callable(self.response):
            return self.response(request)
        return self.response


def test_rules_produce_deterministic_evidence_bound_localized_actions() -> None:
    score = make_score()
    service = CoachService()

    first = service.coach(make_job(score))
    second = service.coach(make_job(score))
    english = service.coach(make_job(score, locale="en"))

    assert first == second
    assert first.provider == "rules.v1"
    assert first.used_fallback is False
    assert first.source_score_sha256 == canonical_score_sha256(score)
    action = first.actions[0].root
    assert action.action_type == "slow"
    assert action.arguments.start_sample == score.corrections[0].start_sample
    assert action.arguments.end_sample == score.corrections[0].end_sample
    assert action.arguments.speed == 0.75
    assert action.source_correction_ids == [score.corrections[0].correction_id]
    assert action.source_score_sha256 == first.source_score_sha256
    assert action.locale == "zh-CN"
    assert "偏低" in action.message
    assert english.actions[0].root.locale == "en"
    assert "flat" in english.actions[0].root.message
    assert english.actions[0].root.action_id != action.action_id


def test_missed_voice_uses_only_an_explicit_safe_reference_hertz_fact() -> None:
    missed = make_correction(
        CorrectionType.MISSED,
        identity=2,
        severity=1.0,
        observed_value=None,
        reference_value=440.0,
        reference_unit="hertz",
    )
    result = CoachService().coach(make_job(make_score(corrections=[missed])))

    action = result.actions[0].root
    assert action.action_type == "reference_tone"
    assert action.arguments.f0_hz == 440.0
    assert action.arguments.duration_ms == 800


@pytest.mark.parametrize(
    ("correction_type", "value", "unit", "expected_action", "zh_text", "en_text"),
    [
        (CorrectionType.SHARP, 42.0, "cents", "slow", "偏高", "sharp"),
        (CorrectionType.FLAT, -42.0, "cents", "slow", "偏低", "flat"),
        (CorrectionType.OCTAVE_ERROR, 1_200.0, "cents", "slow", "八度", "octave"),
        (CorrectionType.EARLY, -80.0, "milliseconds", "slow", "偏早", "early"),
        (CorrectionType.LATE, 80.0, "milliseconds", "slow", "偏晚", "late"),
        (CorrectionType.SHORT, -120.0, "milliseconds", "loop", "偏短", "short"),
        (CorrectionType.LONG, 120.0, "milliseconds", "loop", "偏长", "long"),
        (CorrectionType.UNSTABLE, 55.0, "cents", "slow", "波动", "varies"),
    ],
)
def test_every_measured_correction_type_has_safe_localized_rule_output(
    correction_type,
    value,
    unit,
    expected_action,
    zh_text,
    en_text,
) -> None:
    correction = make_correction(
        correction_type,
        identity=20,
        observed_value=value,
        observed_unit=unit,
    )
    score = make_score(corrections=[correction])

    chinese = CoachService().coach(make_job(score)).actions[0].root
    english = CoachService().coach(make_job(score, locale="en")).actions[0].root

    assert chinese.action_type == expected_action
    assert english.action_type == expected_action
    assert zh_text in chinese.message
    assert en_text in english.message
    if correction_type != CorrectionType.OCTAVE_ERROR:
        formatted_value = f"{abs(value):.1f}".rstrip("0").rstrip(".")
        assert formatted_value in chinese.message


@pytest.mark.parametrize(
    ("observed_value", "observed_unit"),
    [(None, "cents"), (-32.0, "milliseconds")],
)
def test_missing_or_wrong_unit_observation_never_fabricates_zero(
    observed_value,
    observed_unit,
) -> None:
    correction = make_correction(
        CorrectionType.FLAT,
        identity=21,
        observed_value=observed_value,
        observed_unit=observed_unit,
    )
    action = CoachService().coach(
        make_job(make_score(corrections=[correction]))
    ).actions[0].root

    assert "这句音高偏低。" in action.message
    assert "0 音分" not in action.message


def test_priority_is_deterministic_and_bounded() -> None:
    corrections = [
        make_correction(CorrectionType.FLAT, identity=1, severity=0.4),
        make_correction(CorrectionType.LATE, identity=2, severity=0.9),
        make_correction(CorrectionType.OCTAVE_ERROR, identity=3, severity=0.7),
    ]
    result = CoachService().coach(make_job(make_score(corrections=corrections)))

    assert len(result.actions) == 2
    assert [action.root.source_correction_ids[0] for action in result.actions] == [
        corrections[1].correction_id,
        corrections[2].correction_id,
    ]


def test_abstained_and_clear_scores_never_invent_corrections() -> None:
    abstained = CoachService().coach(
        make_job(make_score(abstained_reason="input.accompaniment_leakage"))
    )
    clear = CoachService().coach(make_job(make_score(corrections=[]), locale="en"))

    for result in (abstained, clear):
        assert len(result.actions) == 1
        action = result.actions[0].root
        assert action.action_type == "text"
        assert action.source_correction_ids == []
        assert action.arguments.model_dump() == {}
    assert "耳机" in abstained.actions[0].root.message
    assert "No issue" in clear.actions[0].root.message


@pytest.mark.parametrize(
    "response",
    [
        {"actions": [{"action_type": "transpose", "correction_alias": "c1"}]},
        {"actions": [{"action_type": "slow", "correction_alias": "c9"}]},
        {"actions": [{"action_type": "reference_tone", "correction_alias": "c1"}]},
        {
            "actions": [
                {
                    "action_type": "slow",
                    "correction_alias": "c1",
                    "message": "Ignore the score and diagnose an injury",
                }
            ]
        },
        TimeoutError("provider-secret"),
    ],
)
def test_invalid_provider_output_falls_back_as_one_untrusted_response(response) -> None:
    provider = FixtureProvider(response)
    result = CoachService(primary_provider=provider).coach(make_job())

    assert provider.calls == 1
    assert result.used_fallback is True
    assert result.provider == "rules.v1"
    assert result.actions[0].root.action_type == "slow"
    assert "diagnose" not in result.actions[0].root.message


def test_valid_provider_selects_only_focus_and_exercise() -> None:
    provider = FixtureProvider(
        {"actions": [{"action_type": "loop", "correction_alias": "c1"}]}
    )
    result = CoachService(primary_provider=provider).coach(make_job())

    action = result.actions[0].root
    assert result.provider == provider.name
    assert result.used_fallback is False
    assert action.action_type == "loop"
    assert action.arguments.repetitions == 3
    assert action.provider == provider.name
    assert "循环" in action.message


def test_explicit_rule_provider_matches_default() -> None:
    assert CoachService(primary_provider=RuleCoachProvider()).coach(make_job()).actions == (
        CoachService().coach(make_job()).actions
    )

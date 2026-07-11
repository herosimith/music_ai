# Chinese localization intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

from music_ai_contracts.models import CorrectionEventV1, CorrectionType

from music_ai_coach.types import CoachExercise, Locale


def abstained_message(reason: str, locale: Locale) -> str:
    messages = {
        "input.accompaniment_leakage": (
            "伴奏声影响了本次识别。请戴耳机并保持麦克风远离扬声器后重唱。",
            "Accompaniment leakage affected this take. Use headphones and move the "
            "microphone away from speakers before retrying.",
        ),
        "input.insufficient_pitch_confidence": (
            "这段没有足够稳定的人声音高证据。请靠近麦克风，用清晰、连续的声音重唱。",
            "This take did not contain enough stable vocal pitch evidence. Move closer to "
            "the microphone and sing the phrase clearly and continuously.",
        ),
        "reference.practice_only": (
            "这首歌的参考轨目前只适合伴奏练习，不能给出权威纠错分数。",
            "This song reference currently supports accompaniment practice only, so "
            "authoritative corrections are unavailable.",
        ),
        "reference.rejected": (
            "这首歌的参考证据未通过质量门槛，当前不会生成纠错建议。",
            "This song reference did not pass the quality gate, so no corrections are generated.",
        ),
    }
    selected = messages.get(
        reason,
        (
            "本次证据不足，未生成分数。请检查录音环境后重唱。",
            "There was not enough reliable evidence to score this take. Check the recording "
            "setup and try again.",
        ),
    )
    return selected[0] if locale == "zh-CN" else selected[1]


def clear_message(locale: Locale) -> str:
    if locale == "zh-CN":
        return "这段没有检测到达到纠错阈值的问题。保持当前方式，再完整唱一遍巩固稳定性。"
    return (
        "No issue crossed the correction threshold in this phrase. Keep the same approach "
        "and repeat the full phrase once for consistency."
    )


def correction_message(
    correction: CorrectionEventV1,
    exercise: CoachExercise,
    locale: Locale,
) -> str:
    finding = _finding(correction, locale)
    instruction = _instruction(exercise, locale)
    return f"{finding}{instruction}"


def _finding(correction: CorrectionEventV1, locale: Locale) -> str:
    kind = correction.correction_type
    expected_unit = (
        "milliseconds"
        if kind
        in {
            CorrectionType.EARLY,
            CorrectionType.LATE,
            CorrectionType.SHORT,
            CorrectionType.LONG,
        }
        else "cents"
    )
    value = (
        abs(correction.observed.value)
        if correction.observed is not None and correction.observed.unit == expected_unit
        else None
    )
    if locale == "zh-CN":
        if kind == CorrectionType.SHARP:
            return _zh_fact("这句音高偏高", value, "音分")
        if kind == CorrectionType.FLAT:
            return _zh_fact("这句音高偏低", value, "音分")
        if kind == CorrectionType.OCTAVE_ERROR:
            return "这句出现了约一个八度的音区偏差。"
        if kind == CorrectionType.EARLY:
            return _zh_fact("这句进入偏早", value, "毫秒")
        if kind == CorrectionType.LATE:
            return _zh_fact("这句进入偏晚", value, "毫秒")
        if kind == CorrectionType.SHORT:
            return _zh_fact("这句持续时间偏短", value, "毫秒")
        if kind == CorrectionType.LONG:
            return _zh_fact("这句持续时间偏长", value, "毫秒")
        if kind == CorrectionType.MISSED:
            return "这一句没有检测到足够的人声。"
        return _zh_fact("这句长音波动较大", value, "音分")
    if kind == CorrectionType.SHARP:
        return _en_fact("This phrase is sharp", value, "cents")
    if kind == CorrectionType.FLAT:
        return _en_fact("This phrase is flat", value, "cents")
    if kind == CorrectionType.OCTAVE_ERROR:
        return "This phrase is displaced by about one octave. "
    if kind == CorrectionType.EARLY:
        return _en_fact("This phrase starts early", value, "milliseconds")
    if kind == CorrectionType.LATE:
        return _en_fact("This phrase starts late", value, "milliseconds")
    if kind == CorrectionType.SHORT:
        return _en_fact("This phrase is short", value, "milliseconds")
    if kind == CorrectionType.LONG:
        return _en_fact("This phrase is long", value, "milliseconds")
    if kind == CorrectionType.MISSED:
        return "There was not enough detected voice in this phrase. "
    return _en_fact("The sustained pitch varies too much", value, "cents")


def _instruction(exercise: CoachExercise, locale: Locale) -> str:
    if locale == "zh-CN":
        return {
            CoachExercise.LOOP: "循环这一小段三次，每次保持相同的进入点和结束点。",
            CoachExercise.SLOW: "先用 75% 速度练习这一小段，再恢复原速。",
            CoachExercise.REFERENCE_TONE: "先听参考音，再循环重唱这一句。",
            CoachExercise.TEXT: "按提示重唱这一句。",
        }[exercise]
    return {
        CoachExercise.LOOP: (
            "Loop this short range three times with the same entry and release points."
        ),
        CoachExercise.SLOW: "Practice this short range at 75% speed, then return to full speed.",
        CoachExercise.REFERENCE_TONE: "Listen to the reference tone, then repeat this phrase.",
        CoachExercise.TEXT: "Repeat the phrase using this cue.",
    }[exercise]


def _zh_fact(finding: str, value: float | None, unit: str) -> str:
    if value is None:
        return f"{finding}。"
    return f"{finding}约 {_number(value)} {unit}。"


def _en_fact(finding: str, value: float | None, unit: str) -> str:
    if value is None:
        return f"{finding}. "
    return f"{finding} by about {_number(value)} {unit}. "


def _number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")

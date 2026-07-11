from __future__ import annotations

import hashlib

import pytest
from music_ai_scoring_service.audio import AudioIntegrityError, decode_phrase_audio, energy_dbfs
from scoring_service_testkit import SAMPLE_RATE, make_phrase, wav_payload


def test_raw_pcm_and_wav_decode_to_identical_samples() -> None:
    raw_phrase, raw = make_phrase()
    wav = wav_payload(raw)
    wav_phrase, _ = make_phrase(wav, codec="wav_pcm_s16le")

    decoded_raw = decode_phrase_audio(raw_phrase, raw)
    decoded_wav = decode_phrase_audio(wav_phrase, wav)

    assert decoded_raw.samples == decoded_wav.samples
    assert decoded_raw.sample_rate == SAMPLE_RATE
    assert decoded_raw.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert -16 < energy_dbfs(decoded_raw.samples) < -15
    assert energy_dbfs([0] * 100) == -160.0


def test_audio_hash_and_length_mismatch_are_task_integrity_errors() -> None:
    phrase, payload = make_phrase()
    changed = bytes([payload[0] ^ 1]) + payload[1:]
    with pytest.raises(AudioIntegrityError, match="SHA-256"):
        decode_phrase_audio(phrase, changed)
    with pytest.raises(AudioIntegrityError, match="byte length"):
        decode_phrase_audio(phrase, payload[:-2])


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (wav_payload(channels=2), "must be mono"),
        (wav_payload(sample_rate=44_100), "sample rate"),
        (wav_payload() + b"trailing", "RIFF size"),
    ],
)
def test_wav_header_invariants_are_enforced(payload: bytes, expected: str) -> None:
    phrase, _ = make_phrase(payload, codec="wav_pcm_s16le")
    with pytest.raises(AudioIntegrityError, match=expected):
        decode_phrase_audio(phrase, payload)

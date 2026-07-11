from __future__ import annotations

import hashlib
import hmac
import io
import math
import sys
import wave
from array import array
from collections.abc import Sequence

from music_ai_contracts.models import PhraseAudioV1

from music_ai_scoring_service.types import DecodedPhrase


class AudioIntegrityError(ValueError):
    pass


def decode_phrase_audio(phrase: PhraseAudioV1, payload: bytes) -> DecodedPhrase:
    if len(payload) != phrase.byte_length:
        raise AudioIntegrityError("audio byte length does not match the phrase contract")
    digest = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(digest, phrase.sha256):
        raise AudioIntegrityError("audio SHA-256 does not match the phrase contract")
    expected_frames = phrase.sample_end - phrase.sample_start
    if phrase.codec == "pcm_s16le":
        pcm_bytes = payload
    else:
        pcm_bytes = _decode_wav(phrase, payload, expected_frames)
    if len(pcm_bytes) != expected_frames * 2:
        raise AudioIntegrityError("decoded PCM length does not match the phrase sample range")
    samples = array("h")
    samples.frombytes(pcm_bytes)
    if sys.byteorder != "little":  # pragma: no cover
        samples.byteswap()
    return DecodedPhrase(
        samples=tuple(samples),
        sample_rate=phrase.sample_rate,
        source_sha256=digest,
    )


def energy_dbfs(samples: Sequence[int]) -> float:
    if not samples:
        return -160.0
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    if mean_square <= 0:
        return -160.0
    value = 20.0 * math.log10(math.sqrt(mean_square) / 32_768.0)
    return round(max(-160.0, min(12.0, value)), 6)


def _decode_wav(phrase: PhraseAudioV1, payload: bytes, expected_frames: int) -> bytes:
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        raise AudioIntegrityError("WAV payload is missing a valid RIFF/WAVE header")
    if int.from_bytes(payload[4:8], "little") + 8 != len(payload):
        raise AudioIntegrityError("WAV RIFF size does not match the payload length")
    try:
        with wave.open(io.BytesIO(payload), "rb") as source:
            if source.getnchannels() != 1:
                raise AudioIntegrityError("WAV input must be mono")
            if source.getsampwidth() != 2:
                raise AudioIntegrityError("WAV input must use 16-bit samples")
            if source.getframerate() != phrase.sample_rate:
                raise AudioIntegrityError("WAV sample rate does not match the phrase contract")
            if source.getcomptype() != "NONE":
                raise AudioIntegrityError("WAV input must contain uncompressed PCM")
            if source.getnframes() != expected_frames:
                raise AudioIntegrityError("WAV frame count does not match the phrase sample range")
            pcm_bytes = source.readframes(expected_frames)
            if source.readframes(1):
                raise AudioIntegrityError("WAV contains samples beyond the declared phrase range")
            return pcm_bytes
    except (EOFError, wave.Error) as error:
        raise AudioIntegrityError("WAV structure is invalid") from error

from __future__ import annotations

from enum import StrEnum


class EncryptedAudioKind(StrEnum):
    MUSICEX = "musicex"
    QMC_LEGACY = "qmc_legacy"


def detect_unsupported_encrypted_audio(payload: bytes) -> EncryptedAudioKind | None:
    tail = payload[-4096:]
    if tail.endswith(b"musicex\x00"):
        return EncryptedAudioKind.MUSICEX
    if tail.endswith((b"QTag", b"STag")):
        return EncryptedAudioKind.QMC_LEGACY
    return None

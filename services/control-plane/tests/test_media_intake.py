from __future__ import annotations

import os
from pathlib import Path

import pytest
from music_ai_control_plane.media_intake import (
    EncryptedAudioKind,
    detect_unsupported_encrypted_audio,
)

REAL_FIXTURE = os.environ.get("MUSIC_AI_MGG_FIXTURE")


def test_detects_supported_encrypted_container_markers() -> None:
    assert (
        detect_unsupported_encrypted_audio(b"encrypted" + b"musicex\x00")
        == EncryptedAudioKind.MUSICEX
    )
    assert (
        detect_unsupported_encrypted_audio(b"encrypted" + b"QTag")
        == EncryptedAudioKind.QMC_LEGACY
    )
    assert detect_unsupported_encrypted_audio(b"OggS" + b"plain") is None


@pytest.mark.skipif(
    not REAL_FIXTURE or not Path(REAL_FIXTURE).is_file(),
    reason="external MGG fixture is not configured",
)
def test_external_mgg_sample_is_classified_without_committing_it() -> None:
    payload = Path(REAL_FIXTURE or "").read_bytes()

    assert detect_unsupported_encrypted_audio(payload) == EncryptedAudioKind.MUSICEX

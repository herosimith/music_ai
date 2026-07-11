from __future__ import annotations

import pytest
from music_ai_ingest.artifacts import bound_model_release, model_set_release, quantize


def test_model_set_release_is_order_independent() -> None:
    assert model_set_release("separator@abc", "f0@def") == model_set_release(
        "f0@def", "separator@abc"
    )


def test_artifact_release_binds_full_weight_digest_within_contract_limit() -> None:
    digest = "a" * 64
    release = bound_model_release("model-id-" + "x" * 119, digest)
    assert len(release) <= 128
    assert release.endswith(f"@sha256-{digest}")
    with pytest.raises(ValueError, match="lowercase hexadecimal"):
        bound_model_release("model.v1", "A" * 64)


def test_quantization_uses_stable_half_even_rounding() -> None:
    assert quantize(0.0000005) == 0.0
    assert quantize(0.0000015) == 0.000002
    assert quantize(-0.0) == 0.0

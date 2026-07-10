from __future__ import annotations

import hashlib
import json
import re
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel


def canonical_model_bytes(model: BaseModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def quantize(value: float) -> float:
    rounded = float(Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN))
    return 0.0 if rounded == 0 else rounded


def model_set_release(*model_ids: str) -> str:
    encoded = "\n".join(sorted(model_ids)).encode("utf-8")
    return f"model-set.{hashlib.sha256(encoded).hexdigest()[:24]}"


def bound_model_release(model_id: str, artifact_sha256: str) -> str:
    if not model_id.strip():
        raise ValueError("model_id must not be empty")
    if re.fullmatch(r"[a-f0-9]{64}", artifact_sha256) is None:
        raise ValueError("model artifact SHA-256 must be lowercase hexadecimal")
    return f"{model_id[:55]}@sha256-{artifact_sha256}"


def region_id(
    *,
    song_id: UUID,
    source_sha256: str,
    reference_sha256: str,
    model_release: str,
    policy_fingerprint: str,
    start_sample: int,
    end_sample: int,
    ornament: bool,
) -> str:
    identity = ":".join(
        (
            "music-ai-region-v1",
            str(song_id),
            source_sha256,
            reference_sha256,
            model_release,
            policy_fingerprint,
            str(start_sample),
            str(end_sample),
            "ornament" if ornament else "plain",
        )
    )
    return str(uuid5(NAMESPACE_URL, identity))

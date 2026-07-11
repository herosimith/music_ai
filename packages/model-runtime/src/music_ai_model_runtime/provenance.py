from __future__ import annotations

import hashlib
import re


def bound_model_release(model_id: str, artifact_sha256: str) -> str:
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", model_id) is None:
        raise ValueError("model_id must use the registry identifier format")
    if re.fullmatch(r"[a-f0-9]{64}", artifact_sha256) is None:
        raise ValueError("model artifact SHA-256 must be lowercase hexadecimal")
    compact_id = model_id
    if len(model_id) > 55:
        identity_digest = hashlib.sha256(model_id.encode("ascii")).hexdigest()
        compact_id = f"{model_id[:22]}~{identity_digest[:32]}"
    return f"{compact_id}@sha256-{artifact_sha256}"


def model_set_release(*model_releases: str) -> str:
    if not model_releases or any(not release.strip() for release in model_releases):
        raise ValueError("model releases must not be empty")
    if len(model_releases) != len(set(model_releases)):
        raise ValueError("model releases must be unique")
    encoded = "\n".join(sorted(model_releases)).encode("utf-8")
    return f"model-set.{hashlib.sha256(encoded).hexdigest()[:24]}"

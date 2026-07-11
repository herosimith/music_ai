from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path

from music_ai_contracts.registry import (
    ModelRecord,
    ModelRegistryV1,
    ModelTask,
    TrainingDataReview,
)


class ModelAuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelBinding:
    model_id: str
    task: ModelTask
    artifact_path: Path

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("provider model_id must not be empty")


@dataclass(frozen=True, slots=True)
class AuthorizedModel:
    record: ModelRecord
    artifact_path: Path
    artifact_size: int


class ModelAuthorizer:
    def __init__(
        self,
        registry: ModelRegistryV1,
        *,
        satisfied_constraints: frozenset[str] = frozenset(),
    ) -> None:
        self._models = {model.model_id: model for model in registry.models}
        self._satisfied_constraints = satisfied_constraints

    def authorize(
        self,
        binding: ModelBinding,
        expected_task: ModelTask,
    ) -> AuthorizedModel:
        if binding.task != expected_task:
            raise ModelAuthorizationError("provider binding declares the wrong model task")
        record = self._models.get(binding.model_id)
        if record is None:
            raise ModelAuthorizationError("provider model is absent from the approved registry")
        if record.task != expected_task:
            raise ModelAuthorizationError("registered model task does not match the provider")
        if (
            not record.commercial_use_approved
            or record.training_data_review != TrainingDataReview.APPROVED
        ):
            raise ModelAuthorizationError("provider model is not approved for commercial use")
        if set(record.constraints) - self._satisfied_constraints:
            raise ModelAuthorizationError("provider model has unsatisfied deployment constraints")

        try:
            path = binding.artifact_path.resolve(strict=True)
        except OSError as error:
            raise ModelAuthorizationError("provider model artifact is unavailable") from error
        if not path.is_file():
            raise ModelAuthorizationError("provider model artifact is not a regular file")
        before = path.stat()
        digest = _file_sha256(path)
        after = path.stat()
        snapshot_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        snapshot_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if snapshot_before != snapshot_after:
            raise ModelAuthorizationError("provider model artifact changed during verification")
        if not hmac.compare_digest(digest, record.artifact_sha256):
            raise ModelAuthorizationError(
                "provider model artifact digest does not match the registry"
            )
        return AuthorizedModel(record=record, artifact_path=path, artifact_size=after.st_size)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

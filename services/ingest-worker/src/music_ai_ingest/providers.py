from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from music_ai_contracts.registry import ModelTask

from music_ai_ingest.types import IngestJob, ReferenceAnalysis, StemResult

if TYPE_CHECKING:
    from music_ai_ingest.model_gate import AuthorizedModel


@dataclass(frozen=True, slots=True)
class ModelBinding:
    model_id: str
    task: ModelTask
    artifact_path: Path

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("provider model_id must not be empty")


class SeparationProvider(Protocol):
    binding: ModelBinding

    def separate(self, job: IngestJob, model: AuthorizedModel) -> StemResult: ...


class ReferenceF0Provider(Protocol):
    binding: ModelBinding

    def analyze(
        self,
        vocal_wav: bytes,
        sample_rate: int,
        duration_samples: int,
        model: AuthorizedModel,
    ) -> ReferenceAnalysis: ...

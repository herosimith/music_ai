from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from music_ai_model_runtime import ModelBinding

from music_ai_ingest.types import IngestJob, ReferenceAnalysis, StemResult

if TYPE_CHECKING:
    from music_ai_ingest.model_gate import AuthorizedModel


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

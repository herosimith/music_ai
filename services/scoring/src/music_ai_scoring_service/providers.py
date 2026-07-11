from __future__ import annotations

from typing import Protocol

from music_ai_model_runtime import AuthorizedModel, ModelBinding

from music_ai_scoring_service.types import DecodedPhrase, LeakageAnalysis, PitchAnalysis


class PitchProvider(Protocol):
    binding: ModelBinding

    def analyze(
        self,
        audio: DecodedPhrase,
        hop_samples: int,
        model: AuthorizedModel,
    ) -> PitchAnalysis: ...


class LeakageProvider(Protocol):
    binding: ModelBinding

    def analyze(
        self,
        audio: DecodedPhrase,
        hop_samples: int,
        model: AuthorizedModel,
    ) -> LeakageAnalysis: ...

# ADR 0006: Authoritative phrase scoring and transport evidence

Status: Accepted

## Decision

Authoritative scoring consumes only hash-verified mono PCM16/WAV phrase bytes, an immutable `TransportEvidenceV1`, the exact manifest record selected by the practice session, and registry-authorized F0 and leakage providers. Deterministic DSP computes frame energy; `ScoringCore` remains the sole owner of correction and score semantics.

Transport revisions are normalized before use. A phrase must be bracketed at both boundaries by nearby events from one continuous transport segment; a single start anchor is not enough to prove uninterrupted playback. Seeks or loops through the phrase, contradictory anchors, unsupported drift, or an accumulated drift error above policy fail the task without publishing a score. Small drift is applied to the phrase start and bounded tightly enough that fixed-hop frames remain on a contiguous reference grid.

Trusted but weak evidence may produce a first-class abstained score. Corrupt bytes, invalid audio headers, unauthorized models, malformed provider output, and invalid transport are task failures, never abstentions.

Canonical transport evidence and `UserFeaturesV1` are archived as tenant-scoped derived assets before score publication. Their SHA-256 digests are carried by `UserFeaturesV1` and `ScoreV1`, so a score can be reproduced without extending the raw microphone-audio TTL. Derived evidence is removed by the existing song deletion lifecycle.

Model authorization and model-release provenance live in the shared `music-ai-model-runtime` package and are identical for ingest and scoring workers.

# ADR 0001: Evidence-first modular architecture

Status: Accepted

## Context

No reviewed reference repository is a suitable production foundation. The product must support tenant isolation, replaceable audio models, deterministic corrections, short-lived raw voice data, and explicit uncertainty.

## Decision

Build a greenfield monorepo with these logical boundaries:

- Next.js and AudioWorklet provide playback, local visual feedback, clock calibration, and lossless phrase capture.
- The control plane owns identity, tenancy, assets, sessions, version history, and deletion state.
- The ingest worker creates a versioned `SongManifestV1` and never silently promotes a noisy extracted performance to canonical notation.
- The scoring service extracts features; the pure `ScoringCore` turns frozen references and features into deterministic results.
- The coach consumes only validated score evidence through `CoachProvider` and has a rule-based fallback.

MVP authoritative audio uses reliable PCM16/WAV phrase uploads. WebRTC and LiveKit are deferred to an optional full-duplex coach and never become the authoritative scoring transport without a separate lossless path.

## Consequences

The first release favors correctness and abstention over catalog coverage. A song can be accepted for full scoring, downgraded to accompaniment-only practice, or rejected with stable reason codes. Model code, weights, training data, and commercial-use approval are reviewed independently.

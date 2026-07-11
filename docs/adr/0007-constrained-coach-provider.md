# ADR 0007: Constrained coaching over immutable score facts

Status: Accepted

## Decision

The coach consumes `ScoreV1` only. It never receives raw audio, transport events, tenant profile text, or artifact bytes. Score metrics, correction identities, correction ranges, and score versions are immutable facts and are never recomputed by an LLM.

An interchangeable `CoachProvider` may select a focus correction and an exercise from a small allowlist. Provider output is an untrusted draft containing only opaque correction aliases and action types. The service validates the entire draft, resolves aliases against a deterministic priority shortlist, supplies fixed exercise parameters, renders localized evidence-backed messages, and constructs `CoachActionV1` identities itself. Invalid, empty, timed-out, or incompatible provider output is discarded as a whole and replaced by the deterministic rule provider.

The first coach policy permits `loop`, `slow`, `reference_tone`, and `text`. `transpose` and `compare_take` remain contract capabilities but require range history or multiple takes that are not present in one `ScoreV1`. Reference tones must come from a correction's explicit hertz reference and remain between 55 Hz and 1100 Hz.

Coach actions bind the canonical score SHA-256, locale, coach policy version, provider, and source correction IDs. The service is a pure, reproducible computation in this release, so actions are returned on demand instead of adding a control-plane persistence lifecycle prematurely.

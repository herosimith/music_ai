# ADR 0003: Deterministic scoring and abstention semantics

Status: Accepted

## Decision

`ScoringCore` consumes only a frozen `SongManifestV1`, a frozen `UserFeaturesV1`, an explicit aware production time, and a versioned scoring policy. It performs no audio decoding, model inference, network access, database access, or LLM call.

Callers may supply the exact manifest `region_ids` assigned to a phrase. This is required when a manifest contains regions outside the submitted phrase; it prevents unrelated song regions from reducing phrase coverage.

The feature frame `sample_index` is the position on the calibrated reference timeline. Raw microphone positions and playhead mappings remain in `transport.v1`; the audio-to-features stage must preserve those artifacts for audit.

Scoring rules:

- Never fold pitch modulo an octave. A likely octave displacement is a distinct correction.
- A quiet, complete, low-leakage observation can be assessed as missed singing.
- Missed singing requires enough clean frames to satisfy the timeline coverage gate; heavily contaminated silence is an abstention.
- Voiced frames with weak F0 confidence are not called missed; the scorer abstains if no region can be resolved.
- Timing uses a bounded window and pitch proximity. It does not use unconstrained DTW.
- Timing uses one contiguous performance run, masks neighboring reference regions, and reports performed-duration delta rather than note-end offset.
- Ornamented or low-confidence reference regions are not authoritative targets.
- Confidence and coverage are emitted together. Abstention is not a zero score.
- Correction IDs are deterministic UUIDv5 values bound to tenant/session/phrase/region/type, score policy fingerprint, model releases, and reference/user input hashes.
- Reference evidence points to canonical notes for canonical sources and to the F0 artifact for stem or extracted sources; optional alignment artifacts never replace the authoritative reference.

Any threshold change that can alter a result requires a new `score_version`. The default policy has a committed fingerprint tested in CI.

The scorer rejects policy fingerprints that are not explicitly registered for their `score_version`. A caller cannot silently change thresholds while continuing to emit an existing score version.

## Evaluation

Correction precision is always reported with event coverage and a Wilson confidence interval. Severe pitch errors are stable errors of at least 100 cents for at least 200 ms. An abstention cannot remove a severe event from the miss-rate denominator.

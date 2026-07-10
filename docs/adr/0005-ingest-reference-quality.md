# ADR 0005: Fail-closed reference ingestion

Status: Accepted

## Decision

The ingest worker is a deterministic orchestration layer around replaceable source-separation and reference-F0 providers. Before inference, each provider must resolve to a model-registry entry with the expected task, commercial-use approval, satisfied deployment constraints, and a matching weight SHA-256. An empty registry or altered weight file stops the job without publishing a manifest.

Extracted recordings always use `extracted_recording`; they never emit canonical-note artifacts or claim a unique musical truth. Canonical notation requires a separate authorized source path.

Reference F0 is serialized as canonical `reference-f0.v1` JSON. Floats are quantized, artifact hashes are content-derived, each artifact release binds the full approved weight digest, and region IDs are UUIDv5 values bound to the source, model set, quality policy, and sample range. The job timestamp is supplied by the durable job record so retries produce the same manifest.

Quality thresholds are frozen behind an approved policy fingerprint. The gate rejects recordings without detectable vocals, downgrades unreliable separation or insufficient high-confidence monophonic coverage to practice-only, and accepts only references that ScoringCore can use meaningfully. Non-accepted manifests expose no scorable regions or coverage.

## Consequences

- Test providers exercise the complete pipeline but are not production model fallbacks.
- Real model adapters can be added without changing manifest or quality semantics after their code, weights, training data, and deployment constraints are approved.
- Artifacts are reserved, uploaded, and published only through the tenant-authenticated control plane; the worker never writes its database directly.
- Identical jobs and model releases must converge through content hashing and control-plane idempotency.

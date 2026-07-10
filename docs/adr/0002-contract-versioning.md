# ADR 0002: JSON Schema contracts and immutable result versions

Status: Accepted

## Decision

Pydantic models in `packages/contracts/python` are the contract source of truth. They generate committed JSON Schemas, which generate committed TypeScript types. CI fails when generated artifacts drift.

Every message has a literal `schema_version`. Every analysis result also records:

- `pipeline_version`
- `model_release`
- `score_version`
- `calibration_version`

Historical results are never silently rewritten. Re-scoring creates a new result. Consumers reject unknown major schema versions and unknown fields.

## Compatibility rules

- Additive optional fields may remain in the same major version.
- Required-field, semantic, enum, unit, or identifier changes require a new major version.
- Confidence and coverage are always reported together.
- Abstention is a first-class result, not a zero score.

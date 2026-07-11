# Scoring Service

This service turns an authoritative PCM16/WAV phrase plus immutable transport evidence into `UserFeaturesV1`, then delegates all correction semantics to `ScoringCore` and publishes the resulting `ScoreV1` through the control plane.

Input integrity, transport calibration, model authorization, and provider shape errors are task failures and never become fake abstentions. Abstention remains a valid score only when trusted evidence is insufficient under ScoringCore's coverage or confidence rules.

The committed model registry starts empty. Tests use injected synthetic F0 and leakage providers; production inference remains fail-closed until approved weights and exact digests are registered.

Run tests with:

```bash
uv run --package music-ai-scoring-service pytest services/scoring/tests
```

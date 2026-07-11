# Coach Service

The coach turns a validated `ScoreV1` into localized, evidence-bound `CoachActionV1` commands. It never reads audio and never allows an LLM to create score facts, final parameters, identities, or free-form authoritative claims.

`RuleCoachProvider` is always available. `GatewayCoachProvider` accepts any structured Claude, OpenAI, or local-model gateway through a small protocol; malformed or incompatible output falls back to the rules for the entire response.

Run tests with:

```bash
uv run --package music-ai-coach pytest services/coach/tests
```

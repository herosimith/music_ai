# Coach Service

The coach turns a validated `ScoreV1` into localized, evidence-bound `CoachActionV1` commands. It never reads audio and never allows an LLM to create score facts, final parameters, identities, or free-form authoritative claims.

`RuleCoachProvider` is always available. `GatewayCoachProvider` accepts any structured Claude, OpenAI, or local-model gateway through a small protocol; malformed or incompatible output falls back to the rules for the entire response.

`OpenAIResponsesGateway` is the production HTTP adapter for Responses-compatible gateways. It
uses strict JSON Schema output, disables response storage, caps response size and tokens, and
removes provider details from raised errors. Configure the control plane with all three values or
none of them:

```text
MUSIC_AI_COACH_BASE_URL=https://api.openai.com/v1
MUSIC_AI_COACH_MODEL=gpt-5.6-luna
MUSIC_AI_COACH_API_KEY=<secret>
```

Production launchers may set `MUSIC_AI_COACH_API_KEY_FILE` instead; the launcher reads the mounted
file into the process environment. If configuration is absent or the gateway fails, the API uses
the deterministic rule plan. The gateway receives correction aliases and bounded metrics, never
audio, tenant IDs, session IDs, sample ranges, or mutable score fields.

Run tests with:

```bash
uv run --package music-ai-coach pytest services/coach/tests
```

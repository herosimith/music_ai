# music_ai

An evidence-based AI singing coach for practicing against authorized popular music.

The product deliberately separates measurement from coaching:

- Small audio models and deterministic DSP produce versioned, confidence-gated evidence.
- `ScoringCore` turns frozen features into reproducible correction events.
- An interchangeable LLM explains those events and selects approved exercises; it never invents scores.

## Repository layout

```text
apps/web                 Next.js practice client and AudioWorklet capture
services/control-plane   Authentication, tenants, songs, sessions, retention
services/ingest-worker   Offline song analysis and reference construction
services/scoring         Audio-to-features and authoritative phrase scoring
services/coach           Rule fallback and interchangeable CoachProvider
packages/contracts       Versioned Python/TypeScript protocol contracts
packages/scoring-core    Deterministic scoring package
models/registry          Model provenance and commercial-use gate
tests/golden-audio       Licensed synthetic and expert-reviewed fixtures
docs/adr                 Architecture decision records
```

## Development

Prerequisites: Node 24+, pnpm 10+, Python 3.12+, and uv 0.11+.

```bash
uv sync --all-packages
pnpm install
pnpm contracts:generate
uv run --package music-ai-contracts pytest packages/contracts/python/tests
uv run --package music-ai-model-runtime pytest packages/model-runtime/tests
uv run --package music-ai-scoring pytest packages/scoring-core/tests
uv run --package music-ai-control-plane pytest services/control-plane/tests
uv run --package music-ai-ingest pytest services/ingest-worker/tests
uv run --package music-ai-scoring-service pytest services/scoring/tests
uv run --package music-ai-coach pytest services/coach/tests
pnpm test
pnpm build
```

Start the browser practice workbench with:

```bash
pnpm --filter @music-ai/web dev
```

The first screen supports local audio files, including locally classified `.mgg` inputs, a
synthetic demo, waveform range selection,
AudioWorklet microphone capture, Pitchy-based preview corrections, session history, and
aligned recording playback, correction-range source switching, WAV/transport downloads, and a
same-origin AI coach are included. The AI route receives bounded measurement evidence only; raw
audio stays in the browser. Browser results are explicitly a local preview; authoritative
server scoring remains confidence-gated by the model registry and scoring service. A genuine Ogg
stream with an MGG extension is normalized locally and accepted. MusicEx/QTag/STag encrypted
containers are rejected before storage with export guidance; the application never extracts
account or device keys.

For authorized MusicEx files on macOS, an optional independently built GPL-3.0-only companion is
available under `companions/mgg-helper`. It reads the local QQ Music session and performs conversion
on the user's Mac; it is never linked into or run by the Web/server applications. Build and usage,
including the required explicit authorized-use confirmation, are documented in the companion
README. The validated Ogg is then selected through the ordinary audio picker.

The Web coach route and control plane can call an OpenAI-compatible Responses API for constrained,
schema-validated coaching. Configure `MUSIC_AI_COACH_BASE_URL`, `MUSIC_AI_COACH_MODEL`, and either
`MUSIC_AI_COACH_API_KEY` or `MUSIC_AI_COACH_API_KEY_FILE`; without them, or whenever the provider
fails validation, the UI explicitly reports and uses the deterministic rule fallback.

Production container manifests are documented in `docs/deployment.md`. They deploy the Web,
control-plane, PostgreSQL, retention maintenance, and HTTPS gateway; model-backed workers remain
disabled until the production model registry is approved.

## Product boundary

Automatically extracted references describe similarity to a particular recording, not a unique musical truth. Only licensed notation or an explicitly reviewed target may be labeled canonical. Low-confidence material is rejected or offered as accompaniment-only practice instead of receiving a fabricated score.

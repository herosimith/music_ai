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
uv run --package music-ai-scoring pytest packages/scoring-core/tests
uv run --package music-ai-control-plane pytest services/control-plane/tests
uv run --package music-ai-ingest pytest services/ingest-worker/tests
pnpm test
pnpm build
```

Docker manifests are included later in the implementation, but local development and CI do not depend on Docker.

## Product boundary

Automatically extracted references describe similarity to a particular recording, not a unique musical truth. Only licensed notation or an explicitly reviewed target may be labeled canonical. Low-confidence material is rejected or offered as accompaniment-only practice instead of receiving a fabricated score.

# Ingest Worker

The ingest worker converts an authorized song source into a versioned, confidence-gated `SongManifestV1`. It is intentionally model-agnostic: separation and F0 adapters receive an `AuthorizedModel` only after the model registry and on-disk weight digest pass.

The committed production model registry starts empty. Synthetic providers in the tests prove pipeline behavior but are never selected at runtime. To enable a real adapter, complete the source-code, weight-license, training-data, commercial-use, and deployment-constraint review, then commit its exact weight SHA-256 to `models/registry/models.json`.

The first supported truth source is `extracted_recording`. It describes similarity to the supplied performance, not canonical notation.

Run the module tests with:

```bash
uv run --package music-ai-ingest pytest services/ingest-worker/tests
```

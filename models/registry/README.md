# Model registry

No model may be used by a production worker until it appears in `models.json` with `commercial_use_approved: true` and a verified SHA-256 digest.

Approval covers four independent surfaces:

1. Source-code license.
2. Weight license.
3. Training-data review.
4. Intended commercial and geographic use.

Research approval never implies production approval. Runtime code must resolve models by registry ID and verify the downloaded artifact digest before loading it.

Workers must load this file through `music_ai_contracts.registry.load_registry`. That loader rejects duplicate IDs and contradictory commercial/training-data approval states that JSON Schema alone cannot express portably.

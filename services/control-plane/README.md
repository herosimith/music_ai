# Control Plane

The control plane owns tenant identity, authorized song sources, immutable reference versions, practice sessions, phrase uploads, scores, retention, and deletion tasks.

## Local Run

Set the values from the repository `.env.example`, then run:

```bash
uv run --package music-ai-control-plane python -m music_ai_control_plane
```

The development server listens on `http://127.0.0.1:8000`. The bootstrap token is only accepted outside production and is stored as a peppered HMAC digest.

## Database Migrations

Production must set `MUSIC_AI_AUTO_CREATE_SCHEMA=false` and apply migrations before starting the API:

```bash
uv run alembic -c services/control-plane/alembic.ini upgrade head
```

To verify the migration matches the SQLAlchemy model metadata:

```bash
uv run alembic -c services/control-plane/alembic.ini check
```

## API Flow

1. Reserve and upload a song source through `/v1/songs`.
2. Workers reserve/upload derived assets, then publish an immutable manifest.
3. Create a practice session with the selected `manifest_record_id`.
4. Reserve and upload a PCM/WAV phrase.
5. The scoring service writes an immutable score with `Idempotency-Key` and `Reference-Manifest-Id` headers.
6. Maintenance expires raw audio and processes durable deletion tasks.

## Retention Operations

Production must call `/internal/v1/maintenance/expire` for every tenant more frequently than `MUSIC_AI_RAW_AUDIO_TTL_SECONDS`. Alert on deletion requests that reach `failed`; exhausted tasks require an operator to investigate and explicitly retry them before the related database records can be purged.

# Production Deployment

This deployment runs the browser-local practice workbench, PostgreSQL, the control plane, global
retention maintenance, and a same-origin HTTPS gateway. It does **not** run authoritative ingest,
scoring, or LLM coaching: those modules intentionally have no production daemon or approved model
entry in `models/registry/models.json` yet.

## Prerequisites

- A Linux server with Docker Engine and Docker Compose v2
- A DNS name whose A/AAAA record points at the server
- Inbound TCP 80/443 and UDP 443 allowed
- Outbound access for Caddy to obtain TLS certificates

Microphone capture requires HTTPS on a real host. For local-only testing, browsers treat
`http://localhost` as a secure context.

## Prepare Secrets

From the repository root:

```bash
mkdir -p deploy/secrets
chmod 700 deploy/secrets
umask 077
openssl rand -base64 48 > deploy/secrets/database_password
openssl rand -base64 48 > deploy/secrets/token_pepper
cp deploy/.env.production.example deploy/.env.production
```

Edit `deploy/.env.production` and replace both angle-bracket placeholders. Use an immutable image
tag and a hostname such as `practice.example.com`. Never commit `deploy/.env.production` or files
under `deploy/secrets/`.

## Build And Start

```bash
docker compose \
  --env-file deploy/.env.production \
  -f deploy/compose.production.yaml \
  build

docker compose \
  --env-file deploy/.env.production \
  -f deploy/compose.production.yaml \
  up -d
```

`migrate` waits for PostgreSQL, applies `alembic upgrade head`, and must exit successfully before
the API starts. Check the result:

```bash
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml ps
curl --fail --silent https://practice.example.com/api/ready
curl --fail --silent https://practice.example.com/ >/dev/null
```

Only Caddy is published. Do not add host port mappings for PostgreSQL or the control plane.

## Provision A Tenant

Generate and store an API token in your password manager before provisioning. The command reads it
without placing it in the process arguments and prints only the tenant identity:

```bash
read -r -s -p "New API token: " MUSIC_AI_NEW_TOKEN
printf '%s' "$MUSIC_AI_NEW_TOKEN" | docker compose \
  --env-file deploy/.env.production \
  -f deploy/compose.production.yaml \
  run --rm -T control-plane provision \
  --tenant-slug production \
  --tenant-name "Production Tenant" \
  --credential-name "initial operator" \
  --token-stdin
unset MUSIC_AI_NEW_TOKEN
```

Use a random token containing at least 32 characters. The database stores only a peppered HMAC
digest. Re-running with the same token and tenant is idempotent.

## Retention And Monitoring

The `maintenance` service runs every 300 seconds by default, below the 900-second raw-audio TTL.
It expires phrase audio and processes durable object-deletion tasks for every active tenant. Alert
on either of these log messages:

- `maintenance pass failed`
- `failed_tasks` greater than zero

Keep `MUSIC_AI_MAINTENANCE_INTERVAL_SECONDS` strictly below
`MUSIC_AI_RAW_AUDIO_TTL_SECONDS`; configuration validation refuses an unsafe schedule.

## Backup

Create application-consistent database and object snapshots before every upgrade. The example
uses the Compose project name `music-ai`:

```bash
mkdir -p backups
chmod 700 backups
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml \
  stop caddy control-plane maintenance

docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml \
  exec -T postgres pg_dump -U music_ai_api -Fc music_ai > backups/postgres.dump

docker run --rm \
  -v music-ai_object-store:/data:ro \
  -v "$PWD/backups":/backup \
  alpine:3.22 \
  tar -C /data -czf /backup/object-store.tgz .

docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml \
  start control-plane maintenance caddy
```

Back up `caddy-data` separately if preserving certificate state matters. Test `pg_restore --list`
and the object archive before relying on either backup. Keep the public gateway, API, and
maintenance stopped for the whole database/object snapshot window; restart them even if a backup
command fails. For larger installations, use managed PostgreSQL point-in-time recovery and
versioned object storage instead of local named volumes.

## Upgrade And Rollback

1. Record the running image tag and take verified database/object backups.
2. Change `MUSIC_AI_IMAGE_TAG` to the new immutable release and run `build` then `up -d`.
3. Wait for `migrate`, API, Web, Caddy, and maintenance status; verify both HTTP checks above.
4. If the release fails before a migration, restore the previous tag and run `up -d`.
5. If a migration ran, stop Caddy, API, and maintenance; restore the matching PostgreSQL and object
   snapshots; restore the previous tag; then start the stack. Do not assume an Alembic downgrade is
   data-safe unless that exact downgrade has been tested on a backup clone.

The object-store volume is initialized with UID/GID 10001. If replacing it with a bind mount,
create the host directory and `chown 10001:10001` before startup.

## Enabling Authoritative Scoring Later

Do not add synthetic providers to Compose. A production scoring release must first provide:

- daemon/queue semantics and bounded retries for ingest and scoring;
- reviewed source and weight licenses, training-data provenance, and commercial approval;
- exact weight SHA-256 entries in the model registry;
- lossless phrase and transport-evidence integration tests;
- operational capacity, observability, and deletion behavior.

Until then, the UI label `本地预览` is the accurate product boundary.

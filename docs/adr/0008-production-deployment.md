# ADR 0008: Production deployment remains honest and fail-closed

Status: Accepted

## Context

The first deployable release contains a browser-local preview and one network service: the
control plane. Ingest, authoritative scoring, and coaching are library boundaries rather than
long-running workers. The committed model registry contains no approved production models.
Packaging synthetic test providers as production services would turn missing model governance
into fabricated capability.

Raw microphone audio has a short retention window, so deployment is not complete unless schema
migrations, durable object storage, and deletion maintenance are operational. Browser microphone
capture also requires a secure context outside localhost.

## Decision

- Deploy the standalone Next.js Web process and FastAPI control plane behind one Caddy origin.
- Publish only Caddy on ports 80 and 443. PostgreSQL and the control plane stay on an internal
  network with no host port mappings.
- Use Caddy automatic HTTPS for a real domain. Plain HTTP is permitted only for localhost testing.
- Run Alembic as a one-shot service after PostgreSQL is healthy. API and maintenance processes
  start only after the migration exits successfully.
- Store PostgreSQL data, uploaded objects, and Caddy state in separate named volumes.
- Read database and token-pepper secrets from mounted files. Compose contains paths and required
  placeholders, never usable credential values.
- Provision tenant credentials explicitly. Operators provide the token through a hidden prompt or
  stdin; the CLI returns only tenant identity and never echoes the token.
- Run one internal maintenance process across all active tenants more frequently than the raw-audio
  TTL. It uses database row locking and requires no reusable tenant credential.
- Keep ingest, scoring, and coach workers absent from production Compose until approved adapters,
  weights, exact digests, licenses, and daemon contracts exist.

## Consequences

The deployment is useful immediately for the local-preview practice workflow and durable control
plane APIs, but it does not claim authoritative server scoring. Enabling such scoring is a separate
release gate. Database rollback uses a tested backup restore rather than assuming every migration
has a safe downgrade. Empty named volumes inherit the non-root object directory ownership from the
control-plane image; bind mounts require the operator to set UID/GID 10001 explicitly.

# ADR 0004: Tenant-scoped control plane and deletion lifecycle

Status: Accepted

## Decision

The control plane derives tenant identity from a peppered bearer credential. Tenant identifiers supplied inside protocol payloads are assertions to verify, never authorization inputs. Every externally reachable resource query includes the authenticated `tenant_id`; an inaccessible resource is reported as not found.

Uploads use two steps. A validated metadata reservation creates a server-controlled object key, then a bounded streaming upload must match the reserved media type, byte length, and SHA-256 digest. Clients and workers cannot choose storage paths.

Song manifests and scores are append-only records. A practice session names an exact immutable `manifest_record_id`, and a score write must repeat that identifier. Publishing another manifest cannot change the reference behind a historical session or score. Idempotency retries return the original record only when both content and reference version match.

Raw phrase audio expires after 15 minutes by default. Expiry and user deletion first commit a database tombstone and durable object-deletion task, making content inaccessible before storage cleanup begins. Object deletion is idempotent and retried with bounded backoff. A song deletion physically removes song, asset, manifest, session, phrase, and score rows only after every object task succeeds; the content-free deletion request remains as the audit record.

TTL expiry retains the phrase's content hash and idempotency key so an immutable score remains bound to the deleted input and a retired upload key cannot be reused. A user-requested song deletion removes those remaining identifiers as part of the full privacy purge.

Mutating flows use PostgreSQL row locks. Song-scoped writes lock the song first; destructive traversal then locks manifests, sessions, phrases, assets, and scores in that order. Expiry and deletion workers use `FOR UPDATE SKIP LOCKED`, and each maintenance pass also reconciles pending deletion requests whose tasks may have been completed by different workers.

## Operational Rules

- Production uses PostgreSQL migrations and cannot enable automatic schema creation or static bootstrap credentials.
- Normal application paths cannot update manifest or score records. Privacy purge is the only temporary mutation allowed before physical deletion.
- Object deletion errors expose only a bounded error class, never object keys or provider details.
- Raw audio TTL removes the audio object but retains an already-derived immutable score until the user deletes the song.
- Operations must schedule maintenance more frequently than the raw-audio TTL for every tenant and alert on failed deletion requests.

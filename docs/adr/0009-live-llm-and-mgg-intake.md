# ADR 0009: Live structured coaching and fail-closed MGG intake

Status: Accepted

## Context

The product needs a real hosted language model for coaching and must let users select `.mgg`
files without mistaking encrypted subscription containers for decodable audio. The model must not
become a second scoring authority, and upload support must not depend on extracting account or
device secrets.

## Decision

- Use an OpenAI-compatible Responses gateway with a strict JSON Schema. The gateway receives only
  the bounded correction shortlist derived from immutable `ScoreV1`; it never receives raw audio.
- Treat the configured model identifier as deployment configuration. Keep API credentials in the
  process secret environment or a mounted secret file, never in the repository or response logs.
- Set `store: false`, cap response bytes and output tokens, validate the complete draft, and fall
  back to the deterministic rule provider on timeout, refusal, malformed output, or unknown action.
- Let the browser file picker accept MGG variants and inspect only a small header and tail locally.
  A file that actually starts with an Ogg stream and has no known encrypted trailer is normalized
  to `.ogg` / `audio/ogg` and can be practiced with normally.
- Classify MusicEx, QTag, and STag trailers as unsupported encrypted audio. Show an authorized
  export-to-WAV/FLAC/MP3 instruction and never attempt key extraction or remote key lookup.
- Repeat encrypted-container detection in the control plane after hash and length verification but
  before object storage. Return stable `mgg.key_unavailable` or `mgg.encrypted_unsupported` codes.

## Consequences

The hosted model is used for exercise selection and explanation while deterministic scoring remains
authoritative and reproducible. Plain Ogg data mislabeled as MGG is supported end to end. Encrypted
MGG files remain selectable and receive an accurate recovery path, but cannot be analyzed until the
user exports audio through a client in which they are authorized to access the recording.

This decision does not approve production source-separation or F0 weights. Those adapters still
require a compatible runtime, exact weight digests, training-data provenance, and commercial-use
approval in the model registry.

## Amendment 2026-07: Optional local MGG companion

MusicEx conversion may be performed by the independently built macOS program in
`companions/mgg-helper`. The companion is GPL-3.0-only software derived from
`ownlight6/qmc-decoder` v1.2.0. It is not linked into the Web, control plane, or model services and
is not a root workspace member. No companion binary is committed or loaded by the server.

The companion runs only after explicit authorized-use confirmation. It reads the local QQ Music
login archive, sends a bounded request only to `https://u.y.qq.com/cgi-bin/musicu.fcg`, decrypts
locally, validates the entire Ogg structure, and commits a new output atomically. UIN, `authst`,
eKey, API response bodies, encrypted MGG bytes, and temporary plaintext never enter music_ai
services or logs. The user manually selects the validated Ogg, which then follows the ordinary
authorized-audio workflow.

The main application remains fail closed: encrypted MGG is still rejected before storage, and an
`audio/ogg` upload must at least carry the `OggS` capture pattern. Browser localhost discovery,
background daemons, automatic installation, Windows process-memory scanning, batch conversion,
and server-side key retrieval are explicitly out of scope.

Keeping an independently compiled GPL program in the same repository is an engineering boundary,
not a legal determination that the repository is mere aggregation. Downstream distributors should
obtain qualified legal advice about GPL compliance, copyright, service terms, and applicable
access-control law.

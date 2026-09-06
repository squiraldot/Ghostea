# Phase H15 — Input Boundary & Schema Fuzz Hardening

H15 hardens the edges where Ghostea consumes untrusted or potentially stale
values. The goal is availability without weakening safety: malformed values
are rejected or normalized to the safest existing state.

## Covered boundaries

- malformed Telegram `message_thread_id`
- malformed chat IDs
- unhashable/invalid update-type values
- non-mapping permission payloads
- invalid topic IDs in scope resolution
- malformed persisted visibility rows
- malformed dashboard admin records
- Unicode normalization probes
- extreme message-length input
- null/primitive dashboard authorization values

## Safety invariant

Invalid input must not create a broader capability, a topic scope, a public
identity, an admin identity, or a destructive authorization decision.

The regression harness is deterministic, offline, and safe for CI/readiness
checks.

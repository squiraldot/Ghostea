# Ghostea Phase 7 — Existing Services Scope Audit

Phase 7 does not add a new user-facing moderation feature. It makes the scope
of existing services explicit and prevents forum-topic context from leaking
into chat-wide member/security state.

## Service classification

### Chat-wide
- warnings / warning history
- reputation
- verification
- anti-raid / default permission locks
- welcome and join lifecycle
- user management
- dashboard RBAC/admin state
- group settings
- custom filter definitions
- join events
- security recovery

### Topic-aware
- moderation request context
- flood protection
- repeated-message protection
- moderation logs
- moderation-event analytics
- event-derived risk

### Forum-only
- topic registry metadata

## Rules

1. Topic identity is always `(chat_id, topic_id)`.
2. Normal groups and non-forum supergroups use `topic_id=None`.
3. Warning counts and punishment thresholds remain chat-wide.
4. Verification is chat-wide and cannot be bypassed by changing topics.
5. Anti-raid is chat-wide because it changes default chat permissions.
6. Reputation and user-management state remain chat-wide.
7. Custom filter definitions remain chat-wide; topic settings only enable/disable
   supported moderation controls.
8. Topic-scoped analytics/risk filters moderation events only. Warning and join
   state remains chat-wide.
9. A service must use its declared scope rather than inventing a new topic key.

## Phase 7 verification

- Python compilation: PASS
- Scope policy unit tests: PASS
- Normal group topic isolation: PASS
- Non-forum supergroup fallback: PASS
- Forum topic `(chat_id, topic_id)` identity: PASS
- Chat-wide warning/security scope: PASS


## Phase 12 — Unified Capability Engine
The capability layer centralizes chat-type/visibility/forum decisions in
`ghostea.services.chat_capabilities`. Stable capabilities are pure and cheap;
dynamic bot-admin permissions are separate and must be cached by high-volume
callers. Forum support is derived only from `supergroup + is_forum`, while
`topic_id` is treated as current message context.

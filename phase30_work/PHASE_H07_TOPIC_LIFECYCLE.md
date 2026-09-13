# Phase H07 — Forum & Topic Lifecycle Hardening

This phase hardens existing topic behavior; it does not add a new user-facing
topic feature.

## Telegram contract

Telegram exposes service messages for topic creation, edits, closing and
reopening. There is no dedicated Bot API update for topic deletion. Telegram's
forum documentation says deletion is propagated through message deletion
mechanisms and clients can confirm deletion using the lower-level topic
fetching APIs; the Bot API does not expose a general topic-list/fetch method.

Ghostea therefore never treats the local registry as proof that a topic still
exists on Telegram.

## Local lifecycle rules

- created => active/open/not hidden
- edited => preserve active/closed/hidden state; update name when supplied
- closed => active/closed
- reopened => active/open/not hidden
- General hidden => active/closed/hidden
- General unhidden => active/open/not hidden
- deleted/confirmed stale => inactive/closed/not hidden

Only definitive topic-id/not-found Telegram errors retire a known topic. Generic
400/403/429/network failures never mark a topic deleted.

## General topic

General has topic ID 1 and cannot be deleted. Hide/close and reopen semantics
remain separate from ordinary topic deletion.

## Reconciliation limitation

The Bot API currently does not provide a generic `getForumTopics`/topic lookup
method for bots. H07 therefore uses:
1. lifecycle service messages when available;
2. explicit local lifecycle actions;
3. definitive topic-id failures as negative evidence;
4. chat/forum capability reconciliation.

No code fabricates a successful external deletion event that Telegram did not
provide.

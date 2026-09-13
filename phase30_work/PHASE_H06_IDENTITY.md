# Phase H06 — Member / Sender Identity Hardening

## Scope
Compatibility hardening only; no new user-facing feature.

## Rules
- `from_user` is a human/bot identity only when Telegram supplies a usable user.
- `sender_chat` represents a chat-backed sender and is never converted to a human target.
- Anonymous administrators are treated conservatively as chat-backed/unknown for automated member moderation.
- Bot senders are not moderation targets.
- Missing identity is unknown, never privileged.
- Target administrator lookup failures fail closed for destructive commands.
- Replied-to chat-backed senders are not dereferenced as users.
- Existing chat/topic/service bookkeeping remains available without inventing identity.

## Validation
Run the full unittest suite and Python compileall.

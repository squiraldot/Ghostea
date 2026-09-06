import re
import time
from collections import defaultdict, deque

from ghostea.services.scope_policy import CHAT_WIDE, TOPIC_AWARE, scope_key as resolve_scope_key


class ProtectionService:
    # Flood/repeat state is topic-aware; join bursts remain chat-wide.
    MESSAGE_SCOPE = "topic_aware"
    JOIN_SCOPE = "chat_wide"

    """In-memory anti-spam state for a single bot process."""

    def __init__(
        self,
        spam_patterns,
        blocked_domains,
        window_seconds: int,
        message_limit: int,
    ):
        self.spam_patterns = spam_patterns
        self.blocked_domains = blocked_domains
        self.window_seconds = window_seconds
        self.message_limit = message_limit
        self._messages = defaultdict(deque)
        self._joins = defaultdict(deque)
        # Process-local anti-spam state is bounded; durable moderation state
        # lives in Supabase.
        self._max_message_keys = 50000
        self._max_join_keys = 5000

    def find_spam_pattern(self, text: str) -> str | None:
        for pattern in self.spam_patterns.items:
            # Admin-configured regex is trusted configuration, but invalid
            # expressions must never break message processing.
            try:
                if re.search(pattern, text):
                    return pattern
            except (re.error, TypeError):
                continue
        return None

    def find_blocked_domain(self, text: str) -> str | None:
        lowered = text.casefold()
        for domain in self.blocked_domains.items:
            escaped = re.escape(domain.casefold())
            if re.search(
                rf"(?<![a-z0-9.-]){escaped}(?![a-z0-9.-])",
                lowered,
            ):
                return domain
        return None

    @staticmethod
    def _trim(queue, cutoff):
        while queue and queue[0][0] < cutoff:
            queue.popleft()

    def _prune_if_needed(self):
        if len(self._messages) <= self._max_message_keys:
            return
        # Prefer removing idle/empty queues first; this is deliberately bounded
        # so a large burst cannot turn pruning itself into an O(n) hot path.
        removed = 0
        for key in list(self._messages.keys())[:5000]:
            queue = self._messages.get(key)
            if not queue or (queue and time.monotonic() - queue[-1][0] > self.window_seconds * 2):
                self._messages.pop(key, None)
                removed += 1
            if removed >= 1000:
                break

    def _prune_joins_if_needed(self):
        if len(self._joins) <= self._max_join_keys:
            return
        removed = 0
        for key in list(self._joins.keys())[:1000]:
            queue = self._joins.get(key)
            if not queue or removed < 250:
                self._joins.pop(key, None)
                removed += 1
            if removed >= 250:
                break

    def register_message(
        self,
        chat_id: int,
        user_id: int,
        window_seconds=None,
        message_limit=None,
        scope_key=None,
    ) -> bool:
        # In forum groups, frequency protection is isolated per topic so a
        # user's activity in Topic A cannot accidentally trigger Topic B.
        scope = scope_key if scope_key is not None else (int(chat_id), None)
        key = ("flood", scope, int(user_id))
        now = time.monotonic()
        queue = self._messages[key]
        queue.append((now, None))

        window = int(window_seconds or self.window_seconds)
        limit = int(message_limit or self.message_limit)
        self._trim(queue, now - window)

        triggered = len(queue) >= limit
        if triggered:
            queue.clear()
        self._prune_if_needed()
        return triggered

    def register_join(self, chat_id, user_id, window_seconds, join_limit):
        # Join bursts are deliberately chat-wide, including forum groups.
        key = (int(chat_id), None)
        now = time.monotonic()
        queue = self._joins[key]
        queue.append((now, user_id))
        self._trim(queue, now - int(window_seconds))

        unique_users = {uid for _, uid in queue}
        triggered = len(unique_users) >= int(join_limit)
        if triggered:
            queue.clear()
        self._prune_joins_if_needed()
        return triggered

    def find_mention_spam(self, text, mention_limit):
        return len(re.findall(r"(?<!\w)@[A-Za-z0-9_]{4,32}", text)) >= int(mention_limit)

    def register_repeated_message(
        self,
        chat_id,
        user_id,
        text,
        window_seconds,
        limit,
        scope_key=None,
    ):
        # Repeated-message detection follows the same chat/topic scope as
        # flood protection. Normal groups simply use (chat_id, None).
        scope = scope_key if scope_key is not None else (int(chat_id), None)
        key = ("repeat", scope, int(user_id))
        now = time.monotonic()
        normalized = re.sub(r"\s+", " ", text.casefold()).strip()
        queue = self._messages[key]
        queue.append((now, normalized))
        self._trim(queue, now - int(window_seconds))

        same = sum(1 for _, value in queue if value == normalized)
        triggered = same >= int(limit)
        if triggered:
            queue.clear()
        self._prune_if_needed()
        return triggered

    def clear_runtime_state(self):
        """Clear process-local flood/repeat/join state at recovery boundaries."""
        self._messages.clear()
        self._joins.clear()

    def discard_chat(self, chat_id: int):
        """Drop transient anti-spam state after a Telegram chat migration."""
        chat_id = int(chat_id)
        for mapping in (self._messages, self._joins):
            for key in list(mapping.keys()):
                if mapping is self._messages:
                    scope = key[1] if len(key) > 1 else None
                    if isinstance(scope, tuple) and scope and int(scope[0]) == chat_id:
                        mapping.pop(key, None)
                else:
                    scope = key[0] if key else None
                    if int(scope) == chat_id:
                        mapping.pop(key, None)

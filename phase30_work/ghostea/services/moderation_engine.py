import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Detection:
    category: str
    reason: str
    score: int
    action: str
    source: str


@dataclass(frozen=True)
class ModerationContext:
    """Request-local identity used by the moderation engine.

    The moderation decision remains independent from Telegram's Update object.
    ``scope_key`` is ``(chat_id, topic_id)`` for forum-aware protections and
    ``(chat_id, None)`` for ordinary groups/supergroups.
    """
    chat_id: int
    user_id: int
    topic_id: Optional[int] = None
    chat_type: Optional[str] = None
    is_forum: bool = False

    @property
    def scope_key(self):
        return (int(self.chat_id), self.topic_id)


class ModerationEngine:
    SCOPE = "topic_aware"

    """
    Central decision layer for message content.

    Detection scores are used to rank/describe violations; they do not bypass
    the normal warning limit. This keeps automatic bans controlled by the
    existing warning policy.
    """

    WEIGHTS = {
        "abuse": 60,
        "spam": 45,
        "blocked_link": 35,
        "mention_spam": 30,
        "repeat_spam": 30,
        "long_message": 20,
    }

    def __init__(self, abuse_filter, protection):
        self.abuse_filter = abuse_filter
        self.protection = protection

    @staticmethod
    def _normalize(text):
        folded = unicodedata.normalize("NFKC", str(text)).casefold()
        return "".join(
            ch for ch in folded
            if unicodedata.category(ch)[0] in ("L", "N", "M")
        )

    @classmethod
    def _custom_word(cls, text, rows):
        normalized = cls._normalize(text)
        for row in rows:
            value = str(row.get("value", "")).strip()
            normalized_value = cls._normalize(value)
            if not normalized_value:
                continue
            if len(normalized_value) <= 3:
                if re.search(
                    rf"(?<!\w){re.escape(normalized_value)}(?!\w)",
                    str(text).casefold(), flags=re.UNICODE,
                ):
                    return value
            elif normalized_value in normalized:
                return value
        return None

    @staticmethod
    def _custom_domain(text, rows):
        lowered = text.casefold()
        for row in rows:
            value = str(row.get("value", "")).strip().casefold()
            if value and re.search(
                rf"(?<![a-z0-9.-]){re.escape(value)}(?![a-z0-9.-])",
                lowered,
            ):
                return value
        return None

    @staticmethod
    def _custom_pattern(text, rows):
        for row in rows:
            pattern = str(row.get("value", "")).strip()
            if not pattern:
                continue
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                if compiled.search(text):
                    return pattern
            except re.error:
                continue
        return None

    def evaluate(
        self,
        text,
        settings,
        custom_words,
        custom_domains,
        custom_patterns,
        moderation_context: Optional[ModerationContext] = None,
    ) -> Optional[Detection]:
        """Evaluate one message using explicit request context.

        ``moderation_context`` is the preferred API. The old private settings
        identifiers remain as a compatibility fallback for callers outside
        the message handler during a rolling deployment.
        """
        detections = []
        if moderation_context is not None:
            context_chat_id = int(moderation_context.chat_id)
            context_user_id = int(moderation_context.user_id)
            context_scope_key = moderation_context.scope_key
        else:
            context_chat_id = int(settings.get("_chat_id"))
            context_user_id = int(settings.get("_user_id"))
            context_scope_key = settings.get("_scope_key")

        max_length = int(settings.get("max_message_length", 4000))
        if len(text) > max_length:
            detections.append(
                Detection(
                    "long_message",
                    "Message exceeded configured length",
                    self.WEIGHTS["long_message"],
                    "delete",
                    "message_length",
                )
            )

        mention_limit = int(settings.get("mention_spam_limit", 6))
        if self.protection.find_mention_spam(text, mention_limit):
            detections.append(
                Detection(
                    "mention_spam",
                    "Mention spam",
                    self.WEIGHTS["mention_spam"],
                    "warn",
                    "mention_spam",
                )
            )

        if self.protection.register_repeated_message(
            # These values are supplied by evaluate's caller through settings.
            context_chat_id,
            context_user_id,
            text,
            int(settings.get("repeated_message_window_seconds", 60)),
            int(settings.get("repeated_message_limit", 3)),
            scope_key=context_scope_key,
        ):
            detections.append(
                Detection(
                    "repeat_spam",
                    "Repeated message spam",
                    self.WEIGHTS["repeat_spam"],
                    "warn",
                    "repeat_spam",
                )
            )

        if settings.get("link_filter_enabled", True):
            domain = (
                self.protection.find_blocked_domain(text)
                or self._custom_domain(text, custom_domains)
            )
            if domain:
                action = (
                    "warn"
                    if settings.get("blocked_link_action", "delete") == "warn"
                    else "delete"
                )
                detections.append(
                    Detection(
                        "blocked_link",
                        f"Blocked link: {domain}",
                        self.WEIGHTS["blocked_link"],
                        action,
                        "link",
                    )
                )

        if settings.get("spam_filter_enabled", True):
            pattern = (
                self.protection.find_spam_pattern(text)
                or self._custom_pattern(text, custom_patterns)
            )
            if pattern:
                detections.append(
                    Detection(
                        "spam",
                        "Spam/advertisement pattern",
                        self.WEIGHTS["spam"],
                        "warn",
                        "spam",
                    )
                )

        if settings.get("abuse_filter_enabled", True):
            detected = (
                self.abuse_filter.find(text)
                or self._custom_word(text, custom_words)
            )
            if detected:
                detections.append(
                    Detection(
                        "abuse",
                        f"Abusive language: {detected}",
                        self.WEIGHTS["abuse"],
                        "warn",
                        "automatic",
                    )
                )

        if not detections:
            return None

        # Higher-risk detections take precedence. Abuse wins ties over the
        # other categories because it is the core moderation signal.
        priority = {
            "abuse": 6,
            "spam": 5,
            "blocked_link": 4,
            "mention_spam": 3,
            "repeat_spam": 2,
            "long_message": 1,
        }
        return max(
            detections,
            key=lambda d: (d.score, priority.get(d.category, 0)),
        )

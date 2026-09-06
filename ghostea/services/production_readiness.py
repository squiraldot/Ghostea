"""Phase 20 — final compatibility and production readiness checks.

The readiness layer is intentionally side-effect free. It validates local
configuration/runtime prerequisites and exposes one canonical compatibility
matrix for diagnostics. Telegram permissions remain dynamic and are checked
only when a live chat is inspected.
"""
from dataclasses import dataclass
from pathlib import Path
import os
import sys

from ghostea.services.chat_capabilities import resolve_chat_capabilities
from ghostea.services.chat_visibility import resolve_chat_visibility
from ghostea.services.chat_context import ChatContext
from ghostea.services.telegram_contract import TELEGRAM_CONTRACT


REQUIRED_ENV = ("BOT_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "DASHBOARD_API_KEY", "DASHBOARD_ORIGIN")
REQUIRED_FILES = (
    Path("ghostea/filters/abusive_words.txt"),
    Path("ghostea/filters/spam_patterns.txt"),
    Path("ghostea/filters/blocked_domains.txt"),
)


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    ok: bool
    detail: str

    def as_dict(self):
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def local_readiness(base_dir=None):
    """Return deterministic local production checks without network calls."""
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    checks = []
    for name in REQUIRED_ENV:
        present = bool(os.getenv(name, "").strip())
        checks.append(ReadinessCheck(name, present, "configured" if present else "missing"))
    for rel in REQUIRED_FILES:
        exists = (root / rel).is_file()
        checks.append(ReadinessCheck(str(rel), exists, "present" if exists else "missing"))
    checks.append(ReadinessCheck("python", sys.version_info >= (3, 9), sys.version.split()[0]))
    checks.append(
        ReadinessCheck(
            "telegram_api_contract",
            bool(TELEGRAM_CONTRACT.bot_api_baseline and TELEGRAM_CONTRACT.ptb_major == 22),
            f"Bot API {TELEGRAM_CONTRACT.bot_api_baseline}; python-telegram-bot major {TELEGRAM_CONTRACT.ptb_major}",
        )
    )
    return checks


def readiness_summary(checks):
    checks = list(checks)
    return {
        "ready": all(c.ok for c in checks),
        "checks": [c.as_dict() for c in checks],
    }


def compatibility_matrix():
    """Describe the stable chat-type contract used by Ghostea."""
    cases = [
        ("group", "private", False, False),
        ("supergroup", "private", False, False),
        ("supergroup", "public", False, False),
        ("supergroup", "private", True, False),
        ("supergroup", "public", True, False),
        ("private", "private", False, False),
        ("private", "private", False, True),
    ]
    result = []
    for chat_type, visibility, is_forum, private_topics in cases:
        ctx = ChatContext(
            chat_id=1,
            chat_type=chat_type,
            title="",
            username="example" if visibility == "public" and chat_type == "supergroup" else None,
            is_group=chat_type == "group",
            is_supergroup=chat_type == "supergroup",
            is_forum=is_forum,
            topic_id=42 if is_forum or private_topics else None,
            visibility=visibility,
            private_topics_enabled=private_topics,
        )
        caps = resolve_chat_capabilities(ctx)
        visibility_info = resolve_chat_visibility(ctx)
        result.append({
            "kind": caps.kind,
            "visibility": visibility_info.visibility,
            "supports_moderation": caps.supports_member_moderation,
            "supports_restriction": caps.supports_member_restriction,
            "supports_bans": caps.supports_member_ban,
            "supports_topics": caps.supports_topics,
            "topic_messages": caps.supports_forum_topic_messages,
            "public_identity": visibility_info.can_show_public_link,
        })
    return result

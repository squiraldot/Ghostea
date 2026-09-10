"""Phase 5 — live moderation-target safety checks.

A moderation decision may be produced from a stale message/member snapshot.  This
module performs a fresh Telegram membership/role check immediately before a
destructive member action so promotions, bot accounts, departed members, and
self-targeting cannot accidentally become punishment targets.
"""
from dataclasses import dataclass

from telegram.constants import ChatMemberStatus

from ghostea.services.permission_service import PermissionLookupError


@dataclass(frozen=True)
class ModerationTarget:
    user_id: int
    status: str
    is_bot: bool


class ModerationTargetError(PermissionError):
    """Target is not safe/eligible for member moderation."""


_ALLOWED_TARGET_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.RESTRICTED,
}


async def verify_moderation_target(chat, user_id: int, permission_service=None, requester_id=None):
    """Return a live target snapshot or raise a fail-closed error.

    The lookup is deliberately forced through the live permission service when
    available.  A cached admin answer is not sufficient immediately before a
    destructive moderation action.
    """
    target_id = int(user_id)
    if requester_id is not None and target_id == int(requester_id):
        raise ModerationTargetError("target_is_requester")

    try:
        if permission_service is not None:
            member = await permission_service.member(chat, target_id, force=True)
        else:
            member = await chat.get_member(target_id)
    except Exception as exc:
        raise PermissionLookupError("could_not_verify_moderation_target") from exc

    status = getattr(member, "status", None)
    user = getattr(member, "user", None)
    if user is None:
        raise ModerationTargetError("target_identity_unavailable")
    if bool(getattr(user, "is_bot", False)):
        raise ModerationTargetError("target_is_bot")
    if status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        raise ModerationTargetError("target_is_admin")
    if status not in _ALLOWED_TARGET_STATUSES:
        raise ModerationTargetError("target_is_not_active_member")

    return ModerationTarget(target_id, status, False)

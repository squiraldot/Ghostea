"""Phase 12: centralized Telegram chat capability resolution.

This module separates four concepts that must not be conflated:
- chat type (group/supergroup)
- visibility (private/public)
- chat capabilities (forum/topic support, moderation API support)
- current message context (topic_id)

The resolver is deliberately pure and cheap for the message hot path. Dynamic
bot-admin permissions are handled separately so capability detection never
causes an API call per message.
"""
from dataclasses import dataclass
from typing import Optional, Mapping, Any

from ghostea.services.chat_context import ChatContext


@dataclass(frozen=True)
class ChatCapabilities:
    """Stable capabilities derived from one canonical ChatContext.

    ``supports_*`` means Telegram/the current chat type can support the
    operation. It does not mean the bot currently has the required admin
    permission. Dynamic permission checks remain a separate concern.
    """
    chat_type: str
    visibility: str
    is_group: bool
    is_supergroup: bool
    is_forum: bool
    is_topic_message: bool
    supports_member_moderation: bool
    supports_message_deletion: bool
    supports_member_ban: bool
    supports_member_unban: bool
    supports_member_restriction: bool
    supports_default_permissions: bool
    supports_group_settings: bool
    supports_topics: bool
    supports_topic_management: bool
    supports_forum_topic_messages: bool
    supports_public_username: bool
    supports_private_chat_topics: bool

    @property
    def is_public(self) -> bool:
        return self.visibility == "public"

    @property
    def is_private(self) -> bool:
        return self.visibility == "private"

    @property
    def kind(self) -> str:
        if self.is_forum:
            return "forum_supergroup"
        if self.is_supergroup:
            return "supergroup"
        if self.is_group:
            return "group"
        return "unsupported"

    @property
    def scope_kind(self) -> str:
        return "topic" if self.is_topic_message else "chat"

    def allows_feature(self, feature: str) -> bool:
        """Central feature gate for stable chat capabilities."""
        mapping = {
            "member_moderation": self.supports_member_moderation,
            "message_deletion": self.supports_message_deletion,
            "member_ban": self.supports_member_ban,
            "member_unban": self.supports_member_unban,
            "member_restriction": self.supports_member_restriction,
            "default_permissions": self.supports_default_permissions,
            "group_settings": self.supports_group_settings,
            "topics": self.supports_topics,
            "topic_messages": self.supports_forum_topic_messages,
            "topic_creation": self.supports_topic_management,
            "topic_management": self.supports_topic_management,
            "topic_deletion": self.supports_topic_management,
            "forum_topic_messages": self.supports_forum_topic_messages,
            "public_username": self.supports_public_username,
            "private_chat_topics": self.supports_private_chat_topics,
        }
        if feature not in mapping:
            raise KeyError(f"unknown Ghostea chat capability: {feature}")
        return mapping[feature]

    def as_dict(self) -> dict:
        return {
            "chat_type": self.chat_type,
            "visibility": self.visibility,
            "is_group": self.is_group,
            "is_supergroup": self.is_supergroup,
            "is_forum": self.is_forum,
            "is_topic_message": self.is_topic_message,
            "supports_member_moderation": self.supports_member_moderation,
            "supports_message_deletion": self.supports_message_deletion,
            "supports_member_ban": self.supports_member_ban,
            "supports_member_unban": self.supports_member_unban,
            "supports_member_restriction": self.supports_member_restriction,
            "supports_default_permissions": self.supports_default_permissions,
            "supports_group_settings": self.supports_group_settings,
            "supports_topics": self.supports_topics,
            "supports_topic_management": self.supports_topic_management,
            "supports_forum_topic_messages": self.supports_forum_topic_messages,
            "supports_public_username": self.supports_public_username,
            "supports_private_chat_topics": self.supports_private_chat_topics,
            "kind": self.kind,
            "scope_kind": self.scope_kind,
        }


def resolve_chat_capabilities(context: Optional[ChatContext]) -> ChatCapabilities:
    """Resolve stable capabilities without network/database work."""
    if context is None:
        return ChatCapabilities(
            chat_type="unsupported",
            visibility="private",
            is_group=False,
            is_supergroup=False,
            is_forum=False,
            is_topic_message=False,
            supports_member_moderation=False,
            supports_message_deletion=False,
            supports_member_ban=False,
            supports_member_unban=False,
            supports_member_restriction=False,
            supports_default_permissions=False,
            supports_group_settings=False,
            supports_topics=False,
            supports_topic_management=False,
            supports_forum_topic_messages=False,
            supports_public_username=False,
            supports_private_chat_topics=False,
        )

    is_group = context.chat_type == "group"
    is_supergroup = context.chat_type == "supergroup"
    is_private = context.chat_type == "private"
    is_forum = bool(is_supergroup and context.is_forum)
    private_topics = bool(is_private and context.private_topics_enabled)

    if is_private:
        return ChatCapabilities(
            chat_type="private",
            visibility=context.visibility,
            is_group=False,
            is_supergroup=False,
            is_forum=False,
            is_topic_message=bool(private_topics and context.topic_id is not None),
            supports_member_moderation=False,
            supports_message_deletion=False,
            supports_member_ban=False,
            supports_member_unban=False,
            supports_member_restriction=False,
            supports_default_permissions=False,
            supports_group_settings=False,
            supports_topics=private_topics,
            supports_topic_management=private_topics,
            supports_forum_topic_messages=private_topics,
            supports_public_username=False,
            supports_private_chat_topics=private_topics,
        )

    # Channel direct-message chats are represented as supergroups but are not
    # ordinary moderation supergroups. Fail closed until explicitly supported.
    if getattr(context, "is_direct_messages", False):
        return ChatCapabilities(
            chat_type="supergroup_direct_messages",
            visibility=context.visibility,
            is_group=False,
            is_supergroup=True,
            is_forum=False,
            is_topic_message=False,
            supports_member_moderation=False,
            supports_message_deletion=False,
            supports_member_ban=False,
            supports_member_unban=False,
            supports_member_restriction=False,
            supports_default_permissions=False,
            supports_group_settings=False,
            supports_topics=False,
            supports_topic_management=False,
            supports_forum_topic_messages=False,
            supports_public_username=False,
            supports_private_chat_topics=False,
        )

    return ChatCapabilities(
        chat_type=context.chat_type,
        visibility=context.visibility,
        is_group=is_group,
        is_supergroup=is_supergroup,
        is_forum=is_forum,
        is_topic_message=bool(is_forum and context.topic_id is not None),
        supports_member_moderation=True,
        supports_message_deletion=True,
        supports_member_ban=True,
        supports_member_unban=is_supergroup,
        # Telegram's Bot API restrictChatMember/ChatMemberRestricted are
        # supergroup-only. Basic groups can still be moderated by deleting
        # messages and banning members, but cannot receive per-member mutes.
        supports_member_restriction=is_supergroup,
        supports_default_permissions=True,
        supports_group_settings=True,
        supports_topics=is_forum,
        supports_topic_management=is_forum,
        supports_forum_topic_messages=is_forum,
        supports_public_username=is_supergroup,
        supports_private_chat_topics=False,
    )


def capabilities_from_registry(row: Optional[Mapping[str, Any]]) -> ChatCapabilities:
    """Resolve capabilities from a persisted chat-registry row.

    This is for web/dashboard paths where a Telegram Chat object is not
    available. Registry data is normalized defensively.
    """
    if not row:
        return resolve_chat_capabilities(None)

    chat_type = str(row.get("chat_type") or "")
    if chat_type not in ("group", "supergroup"):
        return resolve_chat_capabilities(None)

    visibility = str(row.get("visibility") or "private")
    # Telegram basic groups do not have native public usernames. Normalize
    # stale/synthetic public metadata to private at the capability boundary.
    if chat_type == "group":
        visibility = "private"
    elif visibility not in ("private", "public"):
        visibility = "private"

    is_group = chat_type == "group"
    is_supergroup = chat_type == "supergroup"
    is_forum = bool(is_supergroup and row.get("is_forum"))
    context = ChatContext(
        chat_id=int(row.get("chat_id") or 0),
        chat_type=chat_type,
        title=str(row.get("title") or ""),
        username=row.get("username"),
        is_group=is_group,
        is_supergroup=is_supergroup,
        is_forum=is_forum,
        topic_id=None,
        visibility=visibility,
        private_topics_enabled=False,
        is_direct_messages=bool(row.get("is_direct_messages")),
    )
    return resolve_chat_capabilities(context)



@dataclass(frozen=True)
class PrivateChatTopicCompatibility:
    """Phase 19 contract for Bot API forum topics in private chats.

    Private-chat topics are enabled per bot account, not per Telegram group.
    Unlike forum supergroups, there is no admin ``can_manage_topics`` check.
    """
    topics_enabled_for_bot: bool
    supports_topic_creation: bool
    supports_topic_editing: bool
    supports_topic_deletion: bool
    supports_topic_messages: bool
    supports_topic_closing: bool
    supports_topic_reopening: bool
    supports_topic_listing: bool

    @property
    def is_supported(self) -> bool:
        return self.topics_enabled_for_bot and self.supports_topic_messages

    def as_dict(self) -> dict:
        return {
            "topics_enabled_for_bot": self.topics_enabled_for_bot,
            "supports_topic_creation": self.supports_topic_creation,
            "supports_topic_editing": self.supports_topic_editing,
            "supports_topic_deletion": self.supports_topic_deletion,
            "supports_topic_messages": self.supports_topic_messages,
            "supports_topic_closing": self.supports_topic_closing,
            "supports_topic_reopening": self.supports_topic_reopening,
            "supports_topic_listing": self.supports_topic_listing,
            "is_supported": self.is_supported,
        }


def resolve_private_chat_topic_compatibility(context: Optional[ChatContext]) -> PrivateChatTopicCompatibility:
    enabled = bool(
        context is not None
        and context.chat_type == "private"
        and context.private_topics_enabled
    )
    # Bot API 9.3 exposes create/edit/delete/send-to-topic for private chats.
    # close/reopen and a private-chat getForumTopics listing method are not
    # available through the Bot API, so those capabilities stay false.
    return PrivateChatTopicCompatibility(
        topics_enabled_for_bot=enabled,
        supports_topic_creation=enabled,
        supports_topic_editing=enabled,
        supports_topic_deletion=enabled,
        supports_topic_messages=enabled,
        supports_topic_closing=False,
        supports_topic_reopening=False,
        # Telegram exposes no private-chat getForumTopics API; Ghostea's
        # /topics command only lists locally observed records, so this flag
        # remains false for API-level capability reporting.
        supports_topic_listing=False,
    )


@dataclass(frozen=True)
class SupergroupCompatibility:
    """Operational contract for non-forum supergroups in Phase 14.

    This intentionally excludes forum/topic operations. Forum-specific
    behavior is reserved for the next roadmap phase.
    """
    supports_individual_restrictions: bool
    supports_bans: bool
    supports_default_permissions: bool
    supports_message_deletion: bool
    supports_group_settings: bool
    supports_public_username: bool
    supports_topics: bool

    @property
    def is_fully_moderatable(self) -> bool:
        return (
            self.supports_individual_restrictions
            and self.supports_bans
            and self.supports_message_deletion
        )

    def as_dict(self) -> dict:
        return {
            "supports_individual_restrictions": self.supports_individual_restrictions,
            "supports_bans": self.supports_bans,
            "supports_default_permissions": self.supports_default_permissions,
            "supports_message_deletion": self.supports_message_deletion,
            "supports_group_settings": self.supports_group_settings,
            "supports_public_username": self.supports_public_username,
            "supports_topics": self.supports_topics,
            "is_fully_moderatable": self.is_fully_moderatable,
        }


def resolve_supergroup_compatibility(
    capabilities: Optional[ChatCapabilities],
) -> SupergroupCompatibility:
    """Return the Phase 14 contract for a normal (non-forum) supergroup."""
    if capabilities is None or not capabilities.is_supergroup or capabilities.is_forum:
        return SupergroupCompatibility(
            False, False, False, False, False, False, False
        )
    return SupergroupCompatibility(
        supports_individual_restrictions=capabilities.supports_member_restriction,
        supports_bans=capabilities.supports_member_ban,
        supports_default_permissions=capabilities.supports_default_permissions,
        supports_message_deletion=capabilities.supports_message_deletion,
        supports_group_settings=capabilities.supports_group_settings,
        supports_public_username=capabilities.supports_public_username,
        supports_topics=False,
    )




@dataclass(frozen=True)
class ForumSupergroupCompatibility:
    """Operational contract for Telegram forum supergroups (Phase 15).

    Stable forum support is distinct from the bot's current admin rights.
    ``supports_*`` answers whether the chat type/API supports the operation;
    ``can_manage_topics`` remains a dynamic permission check.
    """
    supports_topics: bool
    supports_topic_messages: bool
    supports_topic_creation: bool
    supports_topic_editing: bool
    supports_topic_closing: bool
    supports_topic_reopening: bool
    supports_topic_deletion: bool
    supports_general_topic_management: bool
    supports_topic_scoped_moderation: bool

    @property
    def is_supported(self) -> bool:
        return self.supports_topics and self.supports_topic_messages

    def as_dict(self) -> dict:
        return {
            "supports_topics": self.supports_topics,
            "supports_topic_messages": self.supports_topic_messages,
            "supports_topic_creation": self.supports_topic_creation,
            "supports_topic_editing": self.supports_topic_editing,
            "supports_topic_closing": self.supports_topic_closing,
            "supports_topic_reopening": self.supports_topic_reopening,
            "supports_topic_deletion": self.supports_topic_deletion,
            "supports_general_topic_management": self.supports_general_topic_management,
            "supports_topic_scoped_moderation": self.supports_topic_scoped_moderation,
            "is_supported": self.is_supported,
        }


def resolve_forum_compatibility(
    capabilities: Optional[ChatCapabilities],
) -> ForumSupergroupCompatibility:
    """Return the Phase 15 contract only for forum supergroups."""
    if capabilities is None or not capabilities.is_forum:
        return ForumSupergroupCompatibility(False, False, False, False, False, False, False, False, False)

    return ForumSupergroupCompatibility(
        supports_topics=True,
        supports_topic_messages=True,
        supports_topic_creation=True,
        supports_topic_editing=True,
        supports_topic_closing=True,
        supports_topic_reopening=True,
        # Telegram has no deleteForumTopic Bot API method for the General
        # topic; regular topics can be deleted. The service enforces id=1.
        supports_topic_deletion=True,
        supports_general_topic_management=True,
        supports_topic_scoped_moderation=True,
    )


@dataclass(frozen=True)
class BotPermissions:
    """Dynamic permissions of the Ghostea bot in one chat.

    This object is intentionally separate from ChatCapabilities: a chat may
    support moderation while the bot lacks the administrator rights needed to
    perform it.
    """
    is_member: bool = False
    is_admin: bool = False
    is_owner: bool = False
    can_delete_messages: bool = False
    can_restrict_members: bool = False
    can_ban_members: bool = False
    can_manage_topics: bool = False
    can_invite_users: bool = False
    can_change_info: bool = False

    @property
    def can_moderate(self) -> bool:
        return self.is_admin and (
            self.can_delete_messages
            or self.can_restrict_members
            or self.can_ban_members
        )

    @property
    def can_manage_forum_topics(self) -> bool:
        return self.is_admin and self.can_manage_topics


async def resolve_bot_permissions(chat, bot_user_id: int, raise_on_error: bool = False) -> BotPermissions:
    """Fetch and normalize current bot permissions for a chat.

    This performs one Telegram API lookup and therefore must be cached by
    callers when used on high-volume message paths.
    """
    if not chat or not bot_user_id:
        return BotPermissions()

    try:
        member = await chat.get_member(int(bot_user_id))
    except Exception:
        if raise_on_error:
            raise
        return BotPermissions()

    status = getattr(member, "status", None)
    is_owner = str(status) == "creator"
    is_admin = is_owner or str(status) == "administrator"
    if not is_admin:
        return BotPermissions(is_member=True, is_admin=False)

    def flag(name):
        return bool(getattr(member, name, False))

    return BotPermissions(
        is_member=True,
        is_admin=True,
        is_owner=is_owner,
        can_delete_messages=is_owner or flag("can_delete_messages"),
        can_restrict_members=is_owner or flag("can_restrict_members"),
        can_ban_members=is_owner or flag("can_restrict_members"),
        can_manage_topics=is_owner or flag("can_manage_topics"),
        can_invite_users=is_owner or flag("can_invite_users"),
        can_change_info=is_owner or flag("can_change_info"),
    )

from collections import Counter
from datetime import datetime, timedelta, timezone


class AnalyticsService:
    SCOPE = "topic_aware_events_chat_wide_member_state"

    def __init__(self, store):
        self.store = store

    async def report(self, chat_id, days=7, topic_id=None):
        days = max(1, min(int(days), 90))
        since = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        data = await self.store.get_analytics(chat_id, since, topic_id=topic_id)

        log_count_query = {
            "chat_id": f"eq.{chat_id}", "created_at": f"gte.{since}"
        }
        if topic_id is not None:
            log_count_query["topic_id"] = f"eq.{int(topic_id)}"

        try:
            exact_warnings = await self.store._call(
                self.store.db.count, "ghostea_warning_history",
                {"chat_id": f"eq.{chat_id}", "created_at": f"gte.{since}"},
            )
            exact_actions = await self.store._call(
                self.store.db.count, "ghostea_moderation_logs",
                log_count_query,
            )
            exact_joins = await self.store._call(
                self.store.db.count, "ghostea_join_events",
                {"chat_id": f"eq.{chat_id}", "joined_at": f"gte.{since}"},
            )
        except Exception:
            exact_warnings = exact_actions = exact_joins = None

        warnings = Counter(
            row.get("reason") or "unknown"
            for row in data["warnings"]
        )
        actions = Counter(
            row.get("action") or "unknown"
            for row in data["logs"]
        )

        return {
            "days": days,
            "joins": exact_joins if exact_joins is not None else len(data["joins"]),
            "warnings": exact_warnings if exact_warnings is not None else len(data["warnings"]),
            "actions": exact_actions if exact_actions is not None else len(data["logs"]),
            "topic_id": int(topic_id) if topic_id is not None else None,
            "topic_scope": "moderation_events_only" if topic_id is not None else "chat",
            "warning_scope": "chat",
            "join_scope": "chat",
            "breakdown_sample_cap": 1000,
            "breakdown_partial": any(
                len(data[key]) >= 1000 for key in ("warnings", "logs", "joins")
            ),
            "warning_reasons": warnings,
            "actions_by_type": actions,
        }

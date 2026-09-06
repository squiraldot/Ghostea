import asyncio
import unittest
from types import SimpleNamespace

from ghostea.services.action_result import ActionStatus, classify_exception, execute_action


class FakeRetryError(Exception):
    retry_after = 7


class ActionReliabilityTests(unittest.TestCase):
    def test_success_is_explicit(self):
        async def run():
            return await execute_action("ban_member", lambda: asyncio.sleep(0))
        result = asyncio.run(run())
        self.assertEqual(result.status, ActionStatus.SUCCESS)
        self.assertTrue(result.ok)

    def test_rate_limit_is_transient(self):
        status, detail, retry_after = classify_exception(FakeRetryError("429"))
        self.assertEqual(status, ActionStatus.FAILED_TRANSIENT)
        self.assertEqual(retry_after, 7)

    def test_permission_failure_is_not_success(self):
        status, _, _ = classify_exception(PermissionError("missing_bot_permission:ban_member"))
        self.assertEqual(status, ActionStatus.SKIPPED_NO_PERMISSION)

    def test_unknown_failure_is_not_success(self):
        status, _, _ = classify_exception(RuntimeError("something unexpected"))
        self.assertEqual(status, ActionStatus.FAILED_UNKNOWN)


if __name__ == "__main__":
    unittest.main()

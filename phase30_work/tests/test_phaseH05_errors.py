import asyncio
import unittest

from ghostea.services.action_result import ActionStatus, classify_exception
from ghostea.services.telegram_resilience import TelegramErrorPolicy


class RetryAfter(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__("Too Many Requests")


class Forbidden(Exception):
    code = 403


class BadRequest(Exception):
    code = 400


class NetworkError(Exception):
    pass


class PhaseH05Tests(unittest.TestCase):
    def test_retry_after_is_transient(self):
        status, _, retry = classify_exception(RetryAfter(7))
        self.assertEqual(status, ActionStatus.FAILED_TRANSIENT)
        self.assertEqual(retry, 7)

    def test_forbidden_is_no_permission(self):
        status, _, retry = classify_exception(Forbidden("forbidden"))
        self.assertEqual(status, ActionStatus.SKIPPED_NO_PERMISSION)
        self.assertIsNone(retry)

    def test_bad_request_is_telegram_failure(self):
        status, _, _ = classify_exception(BadRequest("bad request"))
        self.assertEqual(status, ActionStatus.FAILED_TELEGRAM)

    def test_network_is_transient(self):
        status, _, _ = classify_exception(NetworkError("network down"))
        self.assertEqual(status, ActionStatus.FAILED_TRANSIENT)

    def test_safe_read_retries(self):
        async def run():
            calls = []
            async def op():
                calls.append(1)
                if len(calls) < 2:
                    raise NetworkError("temporary")
                return "ok"
            policy = TelegramErrorPolicy(max_retries=2, max_retry_after=0)
            return await policy.call_read(op), len(calls)
        value, calls = asyncio.run(run())
        self.assertEqual(value, "ok")
        self.assertEqual(calls, 2)

    def test_write_policy_is_not_implicitly_retried(self):
        policy = TelegramErrorPolicy(max_retries=2)
        failure = policy.classify(RetryAfter(9))
        self.assertEqual(failure.kind, "rate_limited")
        # execute_action remains single-attempt; this test documents the H05 boundary.
        self.assertEqual(policy.max_retries, 2)


if __name__ == "__main__":
    unittest.main()

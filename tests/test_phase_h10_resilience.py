import asyncio
import unittest

from ghostea.services.concurrency import UpdateDeduplicator, ConcurrencyGate


class H10ConcurrencyTests(unittest.TestCase):
    def test_duplicate_update_is_suppressed_and_bounded(self):
        async def run():
            d = UpdateDeduplicator(ttl_seconds=60, max_entries=100)
            self.assertTrue(await d.first(1))
            self.assertFalse(await d.first(1))
            for i in range(2, 140):
                self.assertTrue(await d.first(i))
            self.assertLessEqual(len(d._seen), 100)
        asyncio.run(run())

    def test_keyed_lock_serializes_same_target(self):
        async def run():
            gate = ConcurrencyGate(max_external=2)
            active = 0
            maximum = 0

            async def job():
                nonlocal active, maximum
                async with await gate.keyed((1, 2)):
                    active += 1
                    maximum = max(maximum, active)
                    await asyncio.sleep(0.01)
                    active -= 1

            await asyncio.gather(job(), job(), job())
            self.assertEqual(maximum, 1)
        asyncio.run(run())

    def test_external_gate_bounds_parallelism(self):
        async def run():
            gate = ConcurrencyGate(max_external=2)
            active = 0
            maximum = 0

            async def job():
                nonlocal active, maximum
                async with gate.external():
                    active += 1
                    maximum = max(maximum, active)
                    await asyncio.sleep(0.01)
                    active -= 1

            await asyncio.gather(*(job() for _ in range(8)))
            self.assertEqual(maximum, 2)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

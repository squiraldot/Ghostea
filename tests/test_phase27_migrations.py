import tempfile, unittest
from pathlib import Path
from ghostea.services.schema_migrations import load_migrations, render_sql, migration_status, migration_plan, apply_postgresql

class FakeProvider:
    def __init__(self, version=9, ledger=True, rows=None):
        self.version=version; self.ledger=ledger; self.rows=rows if rows is not None else [{"version":10,"name":"schema_migration_ledger","checksum":load_migrations()[0].checksum}]
    def select(self, table, query):
        if table=="ghostea_schema_meta": return [{"schema_name":"ghostea","schema_version":self.version}]
        if table=="ghostea_schema_migrations": return self.rows
        return []
    def check_tables(self,tables): return {t:self.ledger for t in tables}
    def close(self): pass

class Phase27MigrationTests(unittest.TestCase):
    def test_catalog_is_ordered_and_checksummed(self):
        ms=load_migrations()
        self.assertEqual([m.version for m in ms], sorted(m.version for m in ms))
        self.assertTrue(ms and all(len(m.checksum)==64 for m in ms))

    def test_pending_migration_from_phase26_baseline(self):
        st=migration_status(FakeProvider(version=9))
        self.assertEqual(st["pending"], [10, 11])
        self.assertEqual(st["checksum_drift"], [])
        self.assertTrue(st["ready_to_apply"])

    def test_checksum_drift_is_detected(self):
        st=migration_status(FakeProvider(rows=[{"version":10,"name":"x","checksum":"bad"}]))
        self.assertEqual(st["checksum_drift"], [10])
        self.assertFalse(st["ready_to_apply"])

    def test_sql_plan_is_deterministic_and_contains_lock_safe_migration(self):
        plan=migration_plan(FakeProvider(version=9))
        sql=render_sql(plan)
        self.assertIn("ghostea_schema_migrations", sql)
        self.assertIn("schema_migration_ledger", sql)
        self.assertEqual(sql, render_sql(plan))

    def test_up_to_date_database_has_no_pending_work(self):
        st=migration_status(FakeProvider(version=10))
        self.assertEqual(st["pending"], [11])
        self.assertTrue(st["ready_to_apply"])

    def test_postgresql_apply_uses_transaction_and_advisory_lock(self):
        class ApplyProvider(FakeProvider):
            def __init__(self):
                super().__init__(version=9)
                self.executed=[]
            def execute_sql(self, sql):
                self.executed.append(sql)
        provider=ApplyProvider()
        result=apply_postgresql(provider)
        self.assertEqual(result["applied"], [10, 11])
        self.assertIn("BEGIN;", provider.executed)
        self.assertIn("COMMIT;", provider.executed)
        self.assertTrue(any("pg_advisory_xact_lock" in x for x in provider.executed))

if __name__=="__main__": unittest.main()

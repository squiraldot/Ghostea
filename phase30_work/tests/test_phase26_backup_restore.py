import json
import tempfile
import unittest
from pathlib import Path

from ghostea.services.backup_restore import create_backup, verify_backup, restore_backup, GHOSTEA_TABLES


class FakeProvider:
    def __init__(self, rows):
        self.rows = {k: list(v) for k, v in rows.items()}
        self.calls = []

    def select(self, table, query):
        self.calls.append(("select", table, dict(query)))
        offset = int(query.get("offset", 0))
        limit = int(query.get("limit", 1000))
        return self.rows.get(table, [])[offset:offset+limit]

    def upsert(self, table, row):
        self.calls.append(("upsert", table, dict(row)))
        self.rows.setdefault(table, []).append(dict(row))
        return [row]

    def delete(self, table, query):
        raise AssertionError("restore must not issue destructive deletes")


class FakeStorage:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.put_calls = []

    def get(self, key):
        return self.objects[key]

    def put(self, key, data, content_type=None):
        self.put_calls.append((key, bytes(data), content_type))
        self.objects[key] = bytes(data)
        return key


class Phase26BackupTests(unittest.TestCase):
    def test_backup_verify_and_restore_with_referenced_storage(self):
        rows = {table: [] for table in GHOSTEA_TABLES}
        rows["ghostea_resources"] = [{
            "resource_id": "abc123",
            "storage_key": "resources/abc123/file.bin",
            "storage_filename": "file.bin",
        }]
        provider = FakeProvider(rows)
        storage = FakeStorage({"resources/abc123/file.bin": b"hello"})
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snapshot"
            create_backup(provider, path, storage)
            manifest = verify_backup(path)
            self.assertEqual(manifest["database"]["counts"]["ghostea_resources"], 1)
            self.assertEqual(manifest["storage"]["copied"], 1)

            restored_db = FakeProvider({table: [] for table in GHOSTEA_TABLES})
            restored_storage = FakeStorage()
            result = restore_backup(restored_db, path, restored_storage)
            self.assertEqual(result["restored"]["ghostea_resources"], 1)
            self.assertEqual(restored_storage.objects["resources/abc123/file.bin"], b"hello")

    def test_tamper_is_detected(self):
        rows = {table: [] for table in GHOSTEA_TABLES}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snapshot"
            create_backup(FakeProvider(rows), path)
            data_path = path / "database.jsonl.gz"
            import gzip
            with gzip.open(data_path, "wb") as out:
                out.write(b'{"table":"ghostea_schema_meta","row":{}}\n')
            with self.assertRaises(ValueError):
                verify_backup(path)

    def test_replace_is_rejected(self):
        rows = {table: [] for table in GHOSTEA_TABLES}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snapshot"
            create_backup(FakeProvider(rows), path)
            with self.assertRaises(ValueError):
                restore_backup(FakeProvider(rows), path, replace=True)

    def test_unsafe_storage_path_is_rejected(self):
        rows = {table: [] for table in GHOSTEA_TABLES}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snapshot"
            create_backup(FakeProvider(rows), path)
            manifest = json.loads((path/"manifest.json").read_text())
            manifest["storage"] = {"objects": [{"key":"x", "file":"objects/../evil", "size":0, "sha256":""}]}
            (path/"manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                verify_backup(path)


if __name__ == "__main__":
    unittest.main()

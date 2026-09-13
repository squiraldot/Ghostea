import os
import tempfile
import unittest

from ghostea.storage.local import LocalStorage


class Phase18LocalStorageTests(unittest.TestCase):
    def test_put_get_exists_delete(self):
        with tempfile.TemporaryDirectory() as root:
            storage = LocalStorage(root=root, max_bytes=1024)
            self.assertFalse(storage.exists("resources/r1/a.bin"))
            result = storage.put("resources/r1/a.bin", b"hello", "application/octet-stream")
            self.assertEqual(result, "resources/r1/a.bin")
            self.assertTrue(storage.exists("resources/r1/a.bin"))
            self.assertEqual(storage.get("resources/r1/a.bin"), b"hello")
            self.assertEqual(storage.size("resources/r1/a.bin"), 5)
            self.assertTrue(storage.delete("resources/r1/a.bin"))
            self.assertFalse(storage.exists("resources/r1/a.bin"))

    def test_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            storage = LocalStorage(root=root)
            for key in ("../escape", "a/../escape", "/absolute", r"a\\b", "a//b", "a/./b"):
                with self.subTest(key=key):
                    with self.assertRaises(ValueError):
                        storage.put(key, b"x")

    def test_size_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as root:
            storage = LocalStorage(root=root, max_bytes=3)
            with self.assertRaises(ValueError):
                storage.put("x.bin", b"1234")
            self.assertFalse(storage.exists("x.bin"))

    def test_atomic_write_does_not_leave_temporary_file(self):
        with tempfile.TemporaryDirectory() as root:
            storage = LocalStorage(root=root)
            storage.put("nested/file.bin", b"data")
            names = os.listdir(os.path.join(root, "nested"))
            self.assertEqual(names, ["file.bin"])


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path
from home_inventory.__main__ import scan

class InventoryTests(unittest.TestCase):
    def test_quick_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            (root / "sample.txt").write_text("hello")
            db = Path(tmp) / "db.sqlite"
            scan(root, "quick", db)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0], 1)

    def test_empty_git_repository_and_nested_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            (root / "empty" / ".git").mkdir(parents=True)
            (root / "nested" / "repo" / ".git").mkdir(parents=True)
            db = Path(tmp) / "db.sqlite"
            scan(root, "quick", db)
            with sqlite3.connect(db) as conn:
                found = {row[0] for row in conn.execute("SELECT path FROM repositories")}
            self.assertEqual(found, {str(root / "empty"), str(root / "nested" / "repo")})


    @unittest.skipUnless(__import__("os").name == "posix", "requires POSIX filenames")
    def test_non_utf8_filename_and_permissions(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            filename = os.fsencode(str(root)) + b"/invalid_\\x97.txt"
            fd = os.open(filename, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
            os.chmod(filename, 0)
            db = Path(tmp) / "db.sqlite"
            scan(root, "quick", db)
            with sqlite3.connect(db) as conn:
                path, = conn.execute("SELECT path FROM files").fetchone()
                self.assertIsInstance(path, bytes)
                self.assertEqual(path, filename)
                mode, uid, gid = conn.execute(
                    "SELECT mode,uid,gid FROM file_access").fetchone()
                self.assertEqual(mode, 0)
                self.assertEqual(uid, os.getuid())
                self.assertEqual(gid, os.getgid())

    def test_existing_text_rows_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            path = root / "existing.txt"
            path.write_text("hello")
            db = Path(tmp) / "db.sqlite"
            scan(root, "quick", db)
            scan(root, "quick", db)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT typeof(path) FROM files").fetchone()[0], "text")

if __name__ == "__main__":
    unittest.main()

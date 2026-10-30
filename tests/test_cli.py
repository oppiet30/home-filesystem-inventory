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

if __name__ == "__main__":
    unittest.main()

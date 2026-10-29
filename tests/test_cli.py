import tempfile
import unittest
from pathlib import Path
from home_inventory.__main__ import scan

class InventoryTests(unittest.TestCase):
    def test_quick_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'
            root.mkdir()
            (root / 'sample.txt').write_text('hello')
            scan(root, 'quick', Path(tmp) / 'db.sqlite')

if __name__ == '__main__':
    unittest.main()

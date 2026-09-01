"""Матчер прайса: «айфон 13» не должен выиграть у Pro Max."""
import os
import tempfile
import unittest

import core.database as database
from services.ai.matcher import search_prices_in_db


class MatcherTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self._original_path = database.DB_PATH
        database.DB_PATH = self.db_path
        database.init_db()
        conn = database.get_connection()
        conn.executemany(
            "INSERT INTO prices (item, price) VALUES (?, ?)",
            [
                ("iPhone 13: замена экрана (оригинал)", 8900),
                ("iPhone 13 Pro Max: замена экрана (оригинал)", 14900),
                ("iPad Air: замена батареи (оригинал)", 6200),
            ],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        database.DB_PATH = self._original_path
        for path in (self.db_path, self.db_path + "-wal", self.db_path + "-shm"):
            if os.path.exists(path):
                os.remove(path)

    def test_normalizes_cyrillic_iphone_and_penalizes_unmentioned_max(self):
        matches = search_prices_in_db("айфон 13 стекло")
        self.assertTrue(matches)
        self.assertEqual(matches[0]["item"], "iPhone 13: замена экрана (оригинал)")
        self.assertEqual(matches[0]["price"], 8900)

    def test_keeps_max_when_client_said_max(self):
        matches = search_prices_in_db("iphone 13 pro max")
        items = [row["item"] for row in matches]
        self.assertIn("iPhone 13 Pro Max: замена экрана (оригинал)", items)


if __name__ == "__main__":
    unittest.main()

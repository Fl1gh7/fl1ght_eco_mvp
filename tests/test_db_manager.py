"""Слой данных: клиент, воронка заказа, лиды. Тесты пишут во временный SQLite, прод не трогают."""
import os
import tempfile
import unittest
from datetime import datetime

import core.database as database
from core import db_manager


class DbManagerTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self._original_path = database.DB_PATH
        database.DB_PATH = self.db_path
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._original_path
        for path in (self.db_path, self.db_path + "-wal", self.db_path + "-shm"):
            if os.path.exists(path):
                os.remove(path)

    def test_get_or_create_customer_is_idempotent(self):
        first = db_manager.get_or_create_customer("vk", "vk_1", name="Аня")
        second = db_manager.get_or_create_customer("vk", "vk_1", name="Аня")
        other = db_manager.get_or_create_customer("telegram_bot", "vk_1", name="Аня")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_funnel_does_not_wipe_fields_with_null(self):
        customer_id = db_manager.get_or_create_customer("website", "web_1")
        order_id = db_manager.create_new_order(customer_id)

        db_manager.update_order_from_ai(
            order_id,
            customer_id,
            {"action": "active", "device_info": "iPhone 13", "agreed_price": "4 500 руб"},
        )
        db_manager.update_order_from_ai(
            order_id,
            customer_id,
            {"action": "active", "device_info": None, "issue": "экран", "agreed_price": None},
        )
        db_manager.update_order_from_ai(
            order_id,
            customer_id,
            {
                "action": "success",
                "phone": "+7 999 111-22-33",
                "address": "Ходынский 2",
                "time_slot": "сегодня с 14:00 до 16:00",
            },
        )

        conn = database.get_connection()
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        conn.close()

        self.assertEqual(order["device_info"], "iPhone 13")
        self.assertEqual(order["issue"], "экран")
        self.assertEqual(order["agreed_price"], 4500)
        self.assertEqual(order["status"], "success")
        self.assertEqual(order["address"], "Ходынский 2")
        self.assertIsNone(db_manager.get_active_order_id(customer_id))
        self.assertEqual(customer["phone"], "+7 999 111-22-33")

    def test_save_lead_maps_target_to_lead(self):
        customer_id = db_manager.get_or_create_customer("avito", "avito_9")
        db_manager.save_lead(customer_id, "надо поменять стекло", 91, "target")

        conn = database.get_connection()
        lead = conn.execute("SELECT * FROM leads WHERE customer_id = ?", (customer_id,)).fetchone()
        conn.close()

        self.assertEqual(lead["status"], "lead")
        self.assertEqual(lead["ai_score"], 91)

    def test_update_order_status_and_delay(self):
        customer_id = db_manager.get_or_create_customer("console", "tester_1")
        order_id = db_manager.update_order_status(customer_id, "new")
        self.assertEqual(db_manager.get_active_order_id(customer_id), order_id)

        db_manager.update_order_from_ai(
            order_id,
            customer_id,
            {"action": "delayed", "delay_hours": 24},
        )
        self.assertIsNone(db_manager.get_active_order_id(customer_id))

        conn = database.get_connection()
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        conn.close()
        self.assertEqual(order["status"], "delayed")
        self.assertIsNotNone(order["next_contact_at"])
        datetime.strptime(order["next_contact_at"], "%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    unittest.main()

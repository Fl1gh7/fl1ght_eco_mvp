"""Доступ к клиентам, лидам и заказам. Схема — в core.database."""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional

import sqlite3

from core.database import get_connection

TERMINAL_ORDER_STATUSES = ("success", "delayed", "trash")

# Сито пишет target/trash; в CRM храню lead/trash.
_LEAD_STATUS_MAP = {
    "target": "lead",
    "lead": "lead",
    "trash": "trash",
    "new": "new",
}


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and value.strip().lower() in ("", "null", "none"):
        return False
    return True


def _parse_price(value: Any) -> Optional[int]:
    if not _is_filled(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def _parse_delay_hours(value: Any) -> int:
    if not _is_filled(value):
        return 0
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _normalize_lead_status(status: Optional[str]) -> str:
    if not status:
        return "new"
    return _LEAD_STATUS_MAP.get(str(status).strip().lower(), str(status).strip().lower())


def get_or_create_customer(
    platform: str,
    external_id: str,
    name: Optional[str] = None,
    username: Optional[str] = None,
) -> int:
    """Id клиента. Пара platform + external_id уникальна."""
    with _db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM customers WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        )
        row = cursor.fetchone()
        if row:
            if _is_filled(name):
                cursor.execute(
                    "UPDATE customers SET name = COALESCE(NULLIF(name, ''), ?) WHERE id = ?",
                    (name, row["id"]),
                )
            return int(row["id"])

        try:
            cursor.execute(
                """
                INSERT INTO customers (platform, external_id, name, username)
                VALUES (?, ?, ?, ?)
                """,
                (platform, external_id, name, username),
            )
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            cursor.execute(
                "SELECT id FROM customers WHERE platform = ? AND external_id = ?",
                (platform, external_id),
            )
            existing = cursor.fetchone()
            if not existing:
                raise
            return int(existing["id"])


def get_active_order_id(customer_id: int) -> Optional[int]:
    """Последний заказ, который ещё не success / delayed / trash."""
    placeholders = ", ".join("?" * len(TERMINAL_ORDER_STATUSES))
    with _db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT id FROM orders
            WHERE customer_id = ? AND status NOT IN ({placeholders})
            ORDER BY id DESC
            LIMIT 1
            """,
            (customer_id, *TERMINAL_ORDER_STATUSES),
        )
        row = cursor.fetchone()
        return int(row["id"]) if row else None


def create_new_order(customer_id: int) -> int:
    with _db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO orders (customer_id, status) VALUES (?, 'new')",
            (customer_id,),
        )
        return int(cursor.lastrowid)


def save_lead(customer_id: int, raw_text: str, ai_score: Any, status: str) -> int:
    score = 0
    try:
        score = int(float(ai_score))
    except (TypeError, ValueError):
        score = 0

    with _db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO leads (customer_id, raw_text, ai_score, status)
            VALUES (?, ?, ?, ?)
            """,
            (customer_id, raw_text, score, _normalize_lead_status(status)),
        )
        return int(cursor.lastrowid)


def update_order_from_ai(order_id: int, customer_id: int, payload: dict) -> None:
    """Пишет в заказ поля из JSON модели. Пустые и null уже сохранённое не затирают."""
    if not payload:
        return

    action = str(payload.get("action") or "active").strip().lower()
    updates: list[str] = []
    values: list[Any] = []

    for column in ("device_info", "issue", "address", "time_slot"):
        value = payload.get(column)
        if _is_filled(value):
            updates.append(f"{column} = ?")
            values.append(str(value).strip())

    price = _parse_price(payload.get("agreed_price"))
    if price is not None:
        updates.append("agreed_price = ?")
        values.append(price)

    if action:
        updates.append("status = ?")
        values.append(action)

    delay_hours = _parse_delay_hours(payload.get("delay_hours"))
    if action == "delayed" and delay_hours > 0:
        next_contact = datetime.now(timezone.utc) + timedelta(hours=delay_hours)
        updates.append("next_contact_at = ?")
        values.append(next_contact.strftime("%Y-%m-%d %H:%M:%S"))

    phone = payload.get("phone")
    filled_phone = str(phone).strip() if _is_filled(phone) else None

    with _db() as conn:
        cursor = conn.cursor()
        if updates:
            values.append(order_id)
            cursor.execute(
                f"UPDATE orders SET {', '.join(updates)} WHERE id = ?",
                values,
            )
        if filled_phone:
            cursor.execute(
                "UPDATE customers SET phone = ? WHERE id = ?",
                (filled_phone, customer_id),
            )


def update_order_status(customer_id: int, status: str) -> int:
    """Статус активного заказа или новый заказ — для консольного прогона воронки."""
    order_id = get_active_order_id(customer_id)
    if not order_id:
        order_id = create_new_order(customer_id)
    update_order_from_ai(order_id, customer_id, {"action": status})
    return order_id

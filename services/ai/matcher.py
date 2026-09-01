"""Подбор строк прайса: нормализация кириллицы и штраф Max/Mini, если клиент их не назвал."""

from __future__ import annotations

import re

from core.database import get_connection

NORMALIZATION = {
    "про": "pro",
    "макс": "max",
    "ультра": "ultra",
    "мини": "mini",
    "эйр": "air",
    "айфон": "iphone",
    "пад": "ipad",
    "вотч": "watch",
}

NOISE_WORDS = {
    "ребят",
    "подскажите",
    "пожалуйста",
    "сколько",
    "стоит",
    "теперь",
    "полоску",
    "выручайте",
    "обратиться",
    "цена",
    "денег",
    "есть",
    "вопрос",
    "кто",
    "подскажи",
    "здравствуйте",
    "добрый",
    "день",
    "привет",
    "экран",
    "замена",
}

IMPORTANT_MODIFIERS = ("max", "mini", "plus", "ultra")


def search_prices_in_db(user_text: str) -> list:
    """До 6 позиций прайса, ближайших к формулировке клиента."""
    text = re.sub(r"[^\w\s]", " ", user_text.lower())
    keywords = [
        NORMALIZATION.get(word, word)
        for word in text.split()
        if len(word) >= 2 and word not in NOISE_WORDS
    ]
    if not keywords:
        return []

    conn = get_connection()
    try:
        rows = conn.execute("SELECT item, price FROM prices").fetchall()
    finally:
        conn.close()

    scored_results = []
    for row in rows:
        item_lower = row["item"].lower()
        match_count = sum(1 for word in keywords if word in item_lower)
        if match_count == 0:
            continue
        penalty = sum(
            0.5
            for modifier in IMPORTANT_MODIFIERS
            if modifier in item_lower and modifier not in keywords
        )
        scored_results.append(
            {"item": row["item"], "price": row["price"], "score": match_count - penalty}
        )

    if not scored_results:
        return []

    scored_results.sort(key=lambda item: item["score"], reverse=True)
    top_score = scored_results[0]["score"]
    best_matches = [row for row in scored_results if top_score - row["score"] < 1]
    return [{"item": row["item"], "price": row["price"]} for row in best_matches[:6]]

"""Диалог только с Продавцом и прайсом, без Сита."""
import asyncio
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from services.ai.closer import ai_closer
from services.ai.matcher import search_prices_in_db


async def main():
    print("=" * 50)
    print("Продавец + прайс из SQLite (без Сита). «выход» — закончить диалог.")
    print("=" * 50 + "\n")

    chat_history = []

    while True:
        user_text = input("Клиент: ")
        if user_text.lower() in ["выход", "exit", "quit"]:
            break

        chat_history.append({"role": "user", "text": user_text})

        real_prices = search_prices_in_db(user_text)

        print("ИИ думает...")
        result = await ai_closer.generate_response(chat_history, real_prices)

        ai_reply = result.get("reply_text", "Ошибка генерации текста")
        action = result.get("action", "active")
        delay = result.get("delay_hours", 0)

        print(f"Продавец: {ai_reply}")
        print(f"[Система] Действие: {action.upper()} | Таймер: {delay} ч.\n")

        chat_history.append({"role": "assistant", "text": ai_reply})

        if action == "success":
            print("Сделка закрыта (получено согласие/контакт)!")
            break
        elif action == "delayed":
            print(f"Диалог поставлен на паузу. Напоминание через {delay} часов.")
            break


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nТест прерван пользователем.")

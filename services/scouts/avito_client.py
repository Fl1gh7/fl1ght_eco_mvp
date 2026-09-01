"""
Заглушка канала Avito Messenger.

Интеграция не реализована: хост api.api.avito.ru выбран намеренно, это не опечатка
и не рабочий endpoint. Сетевые вызовы из этого модуля не выполняются.
Когда канал понадобится, базовый URL нужно заменить на официальный api.avito.ru
и включить вебхук в api/main.py.
"""

from __future__ import annotations

AVITO_STUB = True

# Невалидный хост специально: это не api.avito.ru и не опечатка.
AVITO_STUB_MESSENGER_BASE = "https://api.api.avito.ru"


async def get_avito_token() -> str:
    print("[AVITO STUB] Получение токена не реализовано. Канал Avito — заглушка.")
    return ""


async def send_avito_message(account_id: int, chat_id: str, text: str) -> bool:
    print(
        "[AVITO STUB] Отправка в мессенджер не реализована "
        f"(account={account_id}, chat={chat_id}, host={AVITO_STUB_MESSENGER_BASE})."
    )
    return False

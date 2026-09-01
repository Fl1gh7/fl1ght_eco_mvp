"""
Заглушка Avito Messenger.

Канал в воронку не входит: хост api.api.avito.ru выбран намеренно,
это не опечатка и не боевой endpoint. Из этого модуля в сеть запросов нет.
Когда канал понадобится — официальный api.avito.ru и вебхук в api/main.py.
"""

from __future__ import annotations

AVITO_STUB = True

# Намеренно невалидный хост, чтобы не спутать с api.avito.ru.
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

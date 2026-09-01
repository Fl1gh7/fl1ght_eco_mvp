"""
Заглушка канала Avito.

Сюда должна прийти та же воронка, что на сайте и в VK: Сито → матчер → Продавец.
Пока вебхук отвечает 501, клиент API не ходит в сеть (см. avito_client.py).
"""


async def process_avito_inbound_message(*args, **kwargs) -> None:
    print("[AVITO STUB] Входящие сообщения Avito не обрабатываются — канал не реализован.")

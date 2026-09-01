"""
Заглушка канала Avito.

Сюда должна прийти та же воронка, что на сайте и в VK: Сито → матчер → Продавец.
Пока вебхук отвечает 501, клиент в сеть не ходит (см. avito_client.py).
"""


async def process_avito_inbound_message(*args, **kwargs) -> None:
    print("[AVITO STUB] Входящие Avito не обрабатываю — канал не реализован.")

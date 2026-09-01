"""Диалог продаж: YandexGPT возвращает JSON с action и полями заказа."""

import aiohttp
import logging
import json
import re
from core.config import settings

logger = logging.getLogger("services.ai.closer")

class AICloser:
    def __init__(self):
        self.api_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        self.model_uri = f"gpt://{settings.YANDEX_FOLDER_ID}/yandexgpt"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {settings.YANDEX_API_KEY}",
            "x-folder-id": settings.YANDEX_FOLDER_ID
        }

    async def generate_response(self, chat_history: list, found_prices: list) -> dict:
        prices_context = "\n".join([f"- {p['item']}: {p['price']} руб." for p in found_prices]) if found_prices else "Точная цена не найдена."

        system_prompt = (
            "Ты — профессиональный менеджер выездного сервисного центра Service Fl1ght. "
            "Мастер сам приезжает к клиенту домой или в офис, клиенту никуда ехать не нужно.\n\n"
            "ПРАВИЛА ВОРОНКИ ПРОДАЖ:\n"
            "1. Консультируй клиента, называй цену из прайса и предлагай выезд мастера (action: 'active').\n"
            "2. УСЛОВИЯ УСПЕШНОГО ЗАКРЫТИЯ СДЕЛКИ: Ты НЕ ИМЕЕШЬ ПРАВА ставить статус 'success', пока клиент четко не подтвердит ВСЕ 6 пунктов:\n"
            "   - Модель устройства.\n"
            "   - Вид поломки.\n"
            "   - Согласованная цена (клиент должен явно подтвердить сумму или выбрать между копией/оригиналом).\n"
            "   - Точный адрес выезда (улица, дом).\n"
            "   - Удобное время приезда мастера СТРОГО в 2-часовом интервале (например, 'сегодня с 14:00 до 16:00' или 'завтра с 18 до 20'). Если клиент называет точное время (например, 'в 19:00'), предложи ему интервал 'с 18:00 до 20:00' или 'с 19:00 до 21:00'.\n"
            "   - Номер телефона для связи.\n"
            "3. Если хотя бы одного из 6 пунктов не хватает, ты ОБЯЗАН оставить action: 'active' и вежливо уточнить недостающие данные.\n"
            "4. Как только все 6 пунктов собраны — поблагодари, подтверди заказ и только тогда закрывай сделку (action: 'success').\n"
            "5. Если клиент сомневается, говорит 'дорого' или 'напишу позже' — вежливо попрощайся и поставь на паузу (action: 'delayed').\n\n"
            "ОТВЕЧАЙ СТРОГО В ФОРМАТЕ JSON. Заполняй поля по мере получения данных. Если данных пока нет, пиши null.\n"
            "{\n"
            '  "reply_text": "твой ответ клиенту",\n'
            '  "action": "active", "success" или "delayed",\n'
            '  "delay_hours": 0,\n'
            '  "device_info": "модель устройства или null",\n'
            '  "issue": "описание поломки или null",\n'
            '  "agreed_price": "только число (итоговая цена) или null",\n'
            '  "address": "адрес выезда или null",\n'
            '  "time_slot": "время визита (2-часовой интервал) или null",\n'
            '  "phone": "номер телефона клиента или null"\n'
            "}\n\n"
            f"ДАННЫЕ ИЗ ПРАЙСА:\n{prices_context}"
        )

        messages = [{"role": "system", "text": system_prompt}]
        messages.extend(chat_history)

        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {"stream": False, "temperature": 0.3, "maxTokens": "1000"},
            "messages": messages
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers, timeout=15) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        raw_reply = result['result']['alternatives'][0]['message']['text']

                        json_match = re.search(r'\{.*\}', raw_reply, re.DOTALL)
                        if json_match:
                            return json.loads(json_match.group())
                        else:
                            return {"reply_text": raw_reply, "action": "active"}
                    else:
                        return {"reply_text": f"Ошибка ИИ: {resp.status}", "action": "error"}
        except Exception as e:
            return {"reply_text": "Сбой сервера.", "action": "error"}

ai_closer = AICloser()

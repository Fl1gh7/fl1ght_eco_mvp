"""Классификатор лида: YandexGPT, JSON со score и target/trash."""

import aiohttp
import logging
import json
import re
from core.config import settings

logger = logging.getLogger("services.ai.sieve")

class AISieve:
    def __init__(self):
        self.api_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        self.model_uri = f"gpt://{settings.YANDEX_FOLDER_ID}/yandexgpt"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {settings.YANDEX_API_KEY}",
            "x-folder-id": settings.YANDEX_FOLDER_ID
        }

    async def analyze_lead(self, raw_text: str) -> dict:
        system_prompt = (
            "Ты — строгий аналитик входящих сообщений (Сито) для сервисного центра по ремонту техники Apple.\n"
            "Твоя задача: оценить, является ли сообщение запросом на ремонт от реального клиента.\n\n"
            "КРИТЕРИИ ОЦЕНКИ (от 0 до 100):\n"
            "- 90-100: Четкий запрос на ремонт, вопрос о цене, наличии запчастей или сроках.\n"
            "- 50-89: Вопрос около темы, продажа б/у техники, странный, но потенциально живой запрос.\n"
            "- 0-49: Откровенный спам, реклама (настройка директа, продвижение), предложения от поставщиков, боты, бессмысленный набор букв.\n\n"
            "ОТВЕЧАЙ СТРОГО В ФОРМАТЕ JSON:\n"
            "{\n"
            '  "score": число от 0 до 100,\n'
            '  "status": "target" (если score >= 50) или "trash" (если score < 50),\n'
            '  "reason": "Очень краткое пояснение твоего решения (3-5 слов)"\n'
            "}"
        )

        messages = [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": f"СООБЩЕНИЕ КЛИЕНТА: {raw_text}"}
        ]

        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": "500"},
            "messages": messages
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers, timeout=10) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        raw_reply = result['result']['alternatives'][0]['message']['text']
                        
                        json_match = re.search(r'\{.*\}', raw_reply, re.DOTALL)
                        if json_match:
                            return json.loads(json_match.group())
                        else:
                            return {"score": 0, "status": "trash", "reason": "Ошибка парсинга JSON"}
                    else:
                        logger.error(f"Ошибка API: {resp.status}")
                        return {"score": 0, "status": "trash", "reason": "Ошибка API Yandex"}
        except Exception as e:
            logger.error(f"Сбой сервера Сита: {e}")
            return {"score": 0, "status": "trash", "reason": "Сбой соединения"}

ai_sieve = AISieve()
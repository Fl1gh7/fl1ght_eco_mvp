import asyncio
import os
import aiohttp
import random
from core.celery_app import celery_app
from services.ai.sieve import ai_sieve
from core import db_manager
from core.database import get_connection

VK_USER_TOKEN = os.getenv("VK_USER_TOKEN")
VK_GROUP_ID = os.getenv("VK_GROUP_ID")

async def send_vk_comment(owner_id: int, post_id: int, message: str):
    """Комментарий от имени сообщества (from_group)."""
    if not VK_USER_TOKEN or not VK_GROUP_ID:
        print("[VK COMMENT] Пропуск: в .env нет токена или ID паблика.")
        return

    url = "https://api.vk.com/method/wall.createComment"
    payload = {
        "owner_id": owner_id,
        "post_id": post_id,
        "message": message,
        "from_group": VK_GROUP_ID,
        "access_token": VK_USER_TOKEN,
        "v": "5.199"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, data=payload, timeout=10) as resp:
                res = await resp.json()
                if "error" in res:
                    print(f"[VK COMMENT] Ошибка API: {res['error'].get('error_msg')}")
                else:
                    print(f"[VK COMMENT] Успешно оставлен ответ под постом {owner_id}_{post_id}")
        except Exception as e:
            print(f"[VK COMMENT] Ошибка сети: {e}")

async def _async_analyze(text: str):
    return await ai_sieve.analyze_lead(text)

@celery_app.task(name="services.scouts.analyze_scout_message")
def analyze_scout_message(platform: str, chat_name: str, owner_id: int, post_id: int, text: str):
    """Сито → если лид, комментарий от группы → строка в scout_logs."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        sieve_result = asyncio.run(_async_analyze(text))
    else:
        sieve_result = loop.run_until_complete(_async_analyze(text))

    raw_status = sieve_result.get('status', 'trash')
    status = 'lead' if raw_status == 'target' else 'trash'

    raw_score = sieve_result.get('score', 0)
    score = max(0, min(10, int(raw_score / 10)))
    
    action_taken = "Пропущено (Мусор)"

    if status == 'lead':
        external_id = f"scout_{platform}_{owner_id}"
        customer_id = db_manager.get_or_create_customer(
            platform=platform,
            external_id=external_id,
            name=f"Скаут: id{owner_id}"
        )

        full_lead_text = f"📍 [Чат: {chat_name}] | Пользователь: @id{owner_id}\nТекст: {text}"
        db_manager.save_lead(customer_id, full_lead_text, raw_score, "new")

        link_to_pm = f"https://vk.com/im?sel=-{VK_GROUP_ID}"
        replies = [
            f"Привет! Мы заметили твой пост. Занимаемся качественным выездным ремонтом Apple in Москве. Рассчитать стоимость ремонта под твой бюджет можно прямо у нас в диалоге: {link_to_pm}",
            f"Здравствуйте! Увидели вашу запись. У нас мастера выезжают на дом или в офис по всей Москве. Узнать цену и сроки можно в личных сообщениях группы: {link_to_pm}",
            f"Приветствуем! Можем оперативно помочь с ремонтом. Пишите нам в личные сообщения, сориентируем по стоимости запчастей и работы: {link_to_pm}",
            f"Добрый день. Если вопрос с ремонтом еще актуален, обращайтесь! Бесплатно проконсультируем и назовем цену в ЛС: {link_to_pm}",
            f"Привет! Наш сервисный центр специализируется на технике Apple. Работаем на выезде. Чтобы узнать точную стоимость починки, просто напиши нам: {link_to_pm}"
        ]
        
        reply_text = random.choice(replies)
        action_taken = "Оставлен комментарий"
        
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(send_vk_comment(owner_id, post_id, reply_text))
        else:
            loop.run_until_complete(send_vk_comment(owner_id, post_id, reply_text))

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scout_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT,
                chat_name TEXT,
                post_url TEXT,
                text TEXT,
                score INTEGER,
                status TEXT,
                action_taken TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        post_url = f"https://vk.com/wall{owner_id}_{post_id}" if platform == "vk" else ""
        
        cursor.execute('''
            INSERT INTO scout_logs (platform, chat_name, post_url, text, score, status, action_taken)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (platform, chat_name, post_url, text, score, status, action_taken))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[БД АДМИНКИ] Ошибка сохранения лога: {e}")

    if status == 'lead':
        return f"[ЛОГ СКАУТА] Найдена горячая заявка от id{owner_id} (Score: {score}/10). Передано в CRM."
    return f"[ЛОГ СКАУТА] Обработан мусорный пост от id{owner_id}. Отправлено в архив админки."

import os
import sys
import asyncio
import random
import aiohttp
from pyrogram import Client, filters
from dotenv import load_dotenv
import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from services.ai.sieve import ai_sieve
from core.database import get_connection

API_ID = os.getenv("TELETHON_API_ID")
API_HASH = os.getenv("TELETHON_API_HASH")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not API_ID or not API_HASH:
    print("[ОШИБКА] TELETHON_API_ID и TELETHON_API_HASH должны быть в .env")
    sys.exit(1)

app = Client(
    "scout2",
    api_id=int(API_ID),
    api_hash=API_HASH,
    workdir=PROJECT_ROOT
)

# Ключевые слова — дешёвый префильтр, Сито не вызывается на каждый пост.
KEYWORDS = ["ремонт", "мастер", "починить", "экран", "дисплей", "айфон", "iphone", "стекло", "аккумулятор", "батарея", "сервис"]
STOP_WORDS = ["продам", "продаю", "продажа", "обмен", "меняю", "отдам"]

def log_to_crm(chat_name: str, post_url: str, text: str, score: int, status: str, action_taken: str):
    """Строка в scout_logs — её видит админка скаутов."""
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
        cursor.execute('''
            INSERT INTO scout_logs (platform, chat_name, post_url, text, score, status, action_taken)
            VALUES ('telegram', ?, ?, ?, ?, ?, ?)
        ''', (chat_name, post_url, text, score, status, action_taken))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ [БД CRM] Ошибка логирования Telegram: {e}")

async def get_bot_link() -> str:
    """Username боевого бота через getMe — его и даю в публичных ответах."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    bot_username = data.get("result", {}).get("username")
                    if bot_username:
                        return f"https://t.me/{bot_username}"
    except Exception:
        pass
    return "https://t.me/your_bot_error_link"

# ==========================================
# Сообщения в группах
# ==========================================
@app.on_message(filters.text & filters.group)
async def handle_group_message(client, message):
    text = message.text.strip()
    if len(text) < 10 or len(text) > 500:
        return

    lower_text = text.lower()
    if any(w in lower_text for w in STOP_WORDS):
        return
    if not any(w in lower_text for w in KEYWORDS):
        return

    chat_name = message.chat.title or "Группа ТГ"
    print(f"📡 [TG РАДАР] Найдено совпадение в группе '{chat_name}'. Отправляем в ИИ-Сито...")

    sieve_result = await ai_sieve.analyze_lead(text)
    is_target = sieve_result.get('status') == 'target'
    score = max(0, min(10, int(sieve_result.get('score', 0) / 10)))
    crm_status = 'lead' if is_target else 'trash'

    chat_id_clean = str(message.chat.id).replace("-100", "")
    post_url = f"https://t.me/{message.chat.username}/{message.id}" if message.chat.username else f"https://t.me/c/{chat_id_clean}/{message.id}"

    if is_target:
        bot_link = await get_bot_link()
        
        replies = [
            f"Привет! Мы как раз занимаемся качественным выездным ремонтом Apple в нашем районе. Чтобы не засорять общую группу, переходи в нашего официального бота {bot_link} — он сразу посчитает цену ремонта по прайсу и забронирует мастера! 🙌",
            f"Здравствуйте! Занимаемся ремонтом iPhone/iPad с бесплатным выездом к вам домой или в офис. Узнать точную стоимость и не спамить в чате жильцов можно в нашем сервисом боте: {bot_link} На связи!",
            f"Приветствую! Можем оперативно приехать и починить устройство. Напишите, пожалуйста, нашему ИИ-помощнику {bot_link}, чтобы мгновенно рассчитать цену и не занимать ветку чата.",
            f"Добрый день! Если ремонт еще актуален, обращайтесь. Чтобы получить расчет стоимости онлайн и вызвать мастера, перейдите в диалог с нашим ботом: {bot_link}"
        ]
        reply_text = random.choice(replies)
        
        try:
            await message.reply_text(reply_text)
            action_taken = "Отвечено публично, отправлена ссылка на бота"
            print(f"🎯 [TG СКАУТ] Лид подтвержден! Оставлен публичный ответ в группе.")
        except Exception as e:
            action_taken = f"Ошибка отправки ответа в группу: {e}"
            print(f"❌ [TG СКАУТ] Не удалось оставить ответ в группе: {e}")
    else:
        action_taken = "Пропущено (Мусор по мнению ИИ)"

    log_to_crm(f"Группа: {chat_name}", post_url, text, score, crm_status, action_taken)

# ==========================================
# Личка аккаунта-скаута: только ссылка на боевого бота, без воронки здесь
# ==========================================
@app.on_message(filters.text & filters.private)
async def handle_private_message(client, message):
    if message.from_user.is_self or message.from_user.is_bot:
        return

    user_id = message.from_user.id
    user_fullname = message.from_user.first_name or f"Пользователь {user_id}"
    print(f"💬 [TG СКАУТ] {user_fullname} написал в ЛС скауту. Перенаправляем в официального бота...")

    bot_link = await get_bot_link()

    redirect_replies = [
        f"Здравствуйте, {user_fullname}! Я — дежурный робот-радар ServiceFl1ght. У меня нет квалификации, доступа к прайс-листу и расписанию мастеров.\n\n"
        f"Пожалуйста, перейдите к нашему главному ИИ-консультанту: {bot_link} 🙌 Он ответит моментально, назовет цену и оформит выезд!",
        
        f"Приветствую! К сожалению, я технический аккаунт и не смогу проконсультировать вас в этом чате.\n\n"
        f"Запустите диалог с нашим официальным ботом: {bot_link} — он сразу рассчитает стоимость починки под ваш бюджет и запишет на ремонт.",
        
        f"Добрый день! Я не владею актуальной базой цен. Пожалуйста, обратитесь напрямую в наш чат-сервис: {bot_link}. Наш ИИ-приемщик сориентирует вас за пару секунд!"
    ]
    
    await message.reply_text(random.choice(redirect_replies))

if __name__ == "__main__":
    print("[СТАРТ] Юзербот-скаут запускается...")
    app.run()

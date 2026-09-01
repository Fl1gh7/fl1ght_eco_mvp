from fastapi import FastAPI, HTTPException, Depends, status, Request, Response, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import os
import sys
import secrets
import asyncio
import aiohttp
import json
import random
from dotenv import load_dotenv

# Пакеты `core` и `services` импортируются от корня репозитория.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from services.ai.sieve import ai_sieve
from services.ai.closer import ai_closer
from services.ai.matcher import search_prices_in_db
from core import db_manager
from core.database import get_connection
from core.webhook_auth import verify_shared_secret

app = FastAPI(title="ServiceFl1ght API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # виджет может жить на другом хосте; узкий CORS — в бэклоге
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Контекст диалога в RAM процесса: рестарт и второй uvicorn его не разделят.
sessions_history = {}

# ==========================================
# CRM (HTTP Basic)
# ==========================================
security = HTTPBasic()
CRM_ADMIN_USER = os.getenv("CRM_ADMIN_USER") or ""
CRM_ADMIN_PASS = os.getenv("CRM_ADMIN_PASS") or ""

if not CRM_ADMIN_USER or not CRM_ADMIN_PASS:
    print("CRM_ADMIN_USER / CRM_ADMIN_PASS не заданы в .env — эндпоинты /crm недоступны.")

def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not CRM_ADMIN_USER or not CRM_ADMIN_PASS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CRM_ADMIN_USER / CRM_ADMIN_PASS не заданы в .env",
        )
    correct_username = secrets.compare_digest(credentials.username, CRM_ADMIN_USER)
    correct_password = secrets.compare_digest(credentials.password, CRM_ADMIN_PASS)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# ==========================================
# Алерты о закрытых заказах в Telegram
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram_alert(order_id: int, data: dict, phone: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram токены не найдены в .env!")
        return

    text = (
        f"🚨 <b>НОВЫЙ ЗАКАЗ #{order_id}</b>\n\n"
        f"📱 <b>Устройство:</b> {data.get('device_info', 'Не указано')}\n"
        f"🛠 <b>Поломка:</b> {data.get('issue', 'Не указана')}\n"
        f"💰 <b>Цена:</b> {data.get('agreed_price', 'Считаем...')} ₽\n"
        f"📍 <b>Адрес:</b> {data.get('address', 'Не указан')}\n"
        f"🕒 <b>Время:</b> {data.get('time_slot', 'Не указано')}\n"
        f"📞 <b>Телефон:</b> {phone}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status != 200:
                    print(f"❌ [ОШИБКА TELEGRAM API] Бот не смог отправить алерт: {await resp.text()}")
                else:
                    print(f"✅ [TG ALERT] Уведомление по заказу #{order_id} успешно улетело в канал.")
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")

# ==========================================
# API админки: заказы, логи скаутов, паблики
# ==========================================
@app.get("/api/crm/orders")
def get_crm_orders(username: str = Depends(authenticate_admin)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT
            o.id,
            c.phone,
            o.device_info,
            o.issue,
            o.agreed_price,
            o.status,
            o.address,
            o.time_slot,
            o.created_at
        FROM orders o
        JOIN customers c ON o.customer_id = c.id
        ORDER BY o.created_at DESC
    ''')
    orders = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"orders": orders}

@app.get("/api/crm/scouts")
def get_crm_scouts(username: str = Depends(authenticate_admin)):
    """Последние 250 срабатываний скаутов — таблица в админке."""
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
    conn.commit()
    cursor.execute('SELECT * FROM scout_logs ORDER BY created_at DESC LIMIT 250')
    logs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"scouts": logs}

@app.get("/api/crm/groups")
def get_crm_groups(username: str = Depends(authenticate_admin)):
    """Список пабликов VK из services/scouts/monitored_groups.json."""
    file_path = os.path.join(PROJECT_ROOT, "services/scouts/monitored_groups.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

# ==========================================
# Кнопки «ищейка» в админке
# ==========================================
@app.post("/api/crm/run-tg-finder")
async def run_tg_finder_endpoint(background_tasks: BackgroundTasks, username: str = Depends(authenticate_admin)):
    """Поиск чатов ЖК. На время прогона останавливается scout_tg: одна сессия Pyrogram на диск."""
    python_exe = os.path.join(PROJECT_ROOT, "venv", "bin", "python")
    script_path = os.path.join(PROJECT_ROOT, "services", "scouts", "tg_group_finder.py")

    async def run_tg_script():
        try:
            os.system("systemctl stop scout_tg.service")
            await asyncio.sleep(2)

            process = await asyncio.create_subprocess_exec(
                python_exe, script_path,
                env={**os.environ, "PYTHONUNBUFFERED": "1"}
            )
            await process.wait()
        except Exception as e:
            print(f"[API TG FINDER ERROR] {e}")
        finally:
            os.system("systemctl start scout_tg.service")

    background_tasks.add_task(run_tg_script)
    return {"status": "success", "message": "Ищейка Telegram запущена! Служба радара временно приостановлена на время вступлений во избежание флуд-банов и автоматически включится после завершения."}

@app.post("/api/crm/run-vk-finder")
async def run_vk_finder_endpoint(background_tasks: BackgroundTasks, username: str = Depends(authenticate_admin)):
    """Поиск пабликов VK. Перезаписывает monitored_groups.json целиком."""
    python_exe = os.path.join(PROJECT_ROOT, "venv", "bin", "python")
    script_path = os.path.join(PROJECT_ROOT, "services", "scouts", "group_finder.py")

    async def run_vk_script():
        try:
            process = await asyncio.create_subprocess_exec(
                python_exe, script_path,
                env={**os.environ, "PYTHONUNBUFFERED": "1"}
            )
            await process.wait()
        except Exception as e:
            print(f"[API VK FINDER ERROR] {e}")

    background_tasks.add_task(run_vk_script)
    return {"status": "success", "message": "Ищейка пабликов ВКонтакте успешно запущена в фоновом режиме."}

# ==========================================
# Входящие из VK (Callback API)
# ==========================================
VK_GROUP_TOKEN = os.getenv("VK_GROUP_TOKEN")
VK_CONFIRMATION_CODE = os.getenv("VK_CONFIRMATION_CODE", "not_set")
VK_CALLBACK_SECRET = os.getenv("VK_CALLBACK_SECRET") or ""
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET") or ""

if not VK_CALLBACK_SECRET:
    print("VK_CALLBACK_SECRET не задан — входящие Callback VK будут отклонены.")
if not TELEGRAM_WEBHOOK_SECRET:
    print("TELEGRAM_WEBHOOK_SECRET не задан — /api/tg-webhook недоступен.")

async def send_vk_message(user_id: int, text: str):
    url = "https://api.vk.com/method/messages.send"
    params = {
        "user_id": user_id,
        "message": text,
        "random_id": random.randint(1, 2147483647),
        "access_token": VK_GROUP_TOKEN,
        "v": "5.199"
    }
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, data=params, timeout=10)
        except Exception as e:
            print(f"Ошибка отправки сообщения ВК: {e}")

async def process_vk_message(user_id: int, text: str):
    external_id = f"vk_{user_id}"

    customer_id = db_manager.get_or_create_customer(
        platform="vk",
        external_id=external_id,
        name=f"Клиент ВК {user_id}"
    )

    if external_id not in sessions_history:
        sessions_history[external_id] = []
    chat_history = sessions_history[external_id]

    active_order_id = db_manager.get_active_order_id(customer_id)
    if not active_order_id:
        active_order_id = db_manager.create_new_order(customer_id)
        chat_history.clear()

    if not chat_history:
        sieve_result = await ai_sieve.analyze_lead(text)
        db_manager.save_lead(customer_id, text, sieve_result['score'], sieve_result['status'])

        if sieve_result['status'] == 'trash':
            db_manager.update_order_from_ai(active_order_id, customer_id, {"action": "trash"})
            if external_id in sessions_history:
                del sessions_history[external_id]
            return

    chat_history.append({"role": "user", "text": text})

    user_messages = [msg["text"] for msg in chat_history if msg["role"] == "user"]
    combined_search_text = " ".join(user_messages)
    real_prices = search_prices_in_db(combined_search_text)

    closer_result = await ai_closer.generate_response(chat_history, real_prices)

    ai_reply = closer_result.get('reply_text', 'Извините, техническая заминка.')
    action = closer_result.get('action', 'active')

    db_manager.update_order_from_ai(active_order_id, customer_id, closer_result)
    chat_history.append({"role": "assistant", "text": ai_reply})

    await send_vk_message(user_id, ai_reply)

    if action in ['success', 'delayed']:
        if action == 'success':
            phone = closer_result.get("phone", "Не указан")
            await send_telegram_alert(active_order_id, closer_result, phone)
        if external_id in sessions_history:
            del sessions_history[external_id]

@app.post("/api/vk-webhook")
async def vk_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    event_type = data.get("type")

    # confirmation без секрета — чтобы один раз подтвердить Callback в кабинете VK.
    # message_new без VK_CALLBACK_SECRET отклоняется.
    if event_type != "confirmation":
        verify_shared_secret(
            data.get("secret"),
            VK_CALLBACK_SECRET,
            missing_detail="VK_CALLBACK_SECRET не задан в .env",
            invalid_detail="Неверный секрет Callback API ВКонтакте",
        )
    elif VK_CALLBACK_SECRET:
        verify_shared_secret(
            data.get("secret"),
            VK_CALLBACK_SECRET,
            missing_detail="VK_CALLBACK_SECRET не задан в .env",
            invalid_detail="Неверный секрет Callback API ВКонтакте",
        )

    if event_type == "confirmation":
        return Response(content=VK_CONFIRMATION_CODE, media_type="text/plain")

    if event_type == "message_new":
        message_obj = data.get("object", {}).get("message", {})
        user_id = message_obj.get("from_id")
        text = message_obj.get("text", "").strip()

        if text and user_id:
            background_tasks.add_task(process_vk_message, user_id, text)

    return Response(content="ok", media_type="text/plain")


# ==========================================
# Avito — заглушка, в воронку не подключено
# ==========================================
@app.post("/api/avito-webhook")
async def avito_webhook():
    """Avito в воронку не входит. Хост api.api.avito.ru в клиенте — намеренная заглушка."""
    return JSONResponse(
        status_code=501,
        content={
            "status": "stub",
            "message": "Avito Messenger is not implemented. The api.api.avito.ru host is an intentional placeholder.",
        },
    )

# ==========================================
# Официальный Telegram-бот
# ==========================================
async def process_tg_bot_inbound(chat_id: int, user_id: int, fullname: str, text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    external_id = f"tg_bot_{user_id}"

    customer_id = db_manager.get_or_create_customer(
        platform="telegram_bot",
        external_id=external_id,
        name=fullname
    )

    if external_id not in sessions_history:
        sessions_history[external_id] = []
    chat_history = sessions_history[external_id]

    active_order_id = db_manager.get_active_order_id(customer_id)
    if not active_order_id:
        active_order_id = db_manager.create_new_order(customer_id)
        chat_history.clear()

    chat_history.append({"role": "user", "text": text})

    user_messages = [msg["text"] for msg in chat_history if msg["role"] == "user"]
    combined_search_text = " ".join(user_messages)
    real_prices = search_prices_in_db(combined_search_text)

    closer_result = await ai_closer.generate_response(chat_history, real_prices)

    ai_reply = closer_result.get('reply_text', 'Секунду, сверяюсь со спецификацией ремонта.')
    action = closer_result.get('action', 'active')

    db_manager.update_order_from_ai(active_order_id, customer_id, closer_result)
    chat_history.append({"role": "assistant", "text": ai_reply})

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": ai_reply, "parse_mode": "HTML"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status != 200:
                    print(f"❌ [TG BOT ERROR] Ошибка API ТГ: {await resp.text()}")
    except Exception as e:
        print(f"❌ [TG BOT ERROR] Ошибка сети при отправке сообщения: {e}")

    if action in ['success', 'delayed']:
        if action == 'success':
            phone = closer_result.get("phone", "Не указан")
            await send_telegram_alert(active_order_id, closer_result, phone)
        if external_id in sessions_history:
            del sessions_history[external_id]

@app.post("/api/tg-webhook")
async def tg_webhook(request: Request, background_tasks: BackgroundTasks):
    verify_shared_secret(
        request.headers.get("X-Telegram-Bot-Api-Secret-Token"),
        TELEGRAM_WEBHOOK_SECRET,
        missing_detail="TELEGRAM_WEBHOOK_SECRET не задан в .env",
        invalid_detail="Неверный секрет вебхука Telegram",
    )
    data = await request.json()
    message = data.get("message", {})
    text = message.get("text", "").strip()
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if text and chat_id and chat.get("type") == "private":
        user = message.get("from", {})
        user_id = user.get("id")
        first_name = user.get("first_name", "")
        last_name = user.get("last_name", "")
        fullname = f"{first_name} {last_name}".strip() or f"User {user_id}"

        background_tasks.add_task(process_tg_bot_inbound, chat_id, user_id, fullname, text)

    return Response(content="ok", media_type="text/plain")

# ==========================================
# Чат с лендинга
# ==========================================
class ChatMessage(BaseModel):
    session_id: str
    text: str

@app.post("/api/chat")
async def chat_endpoint(data: ChatMessage):
    user_text = data.text.strip()
    session_id = data.session_id

    if not user_text:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    customer_id = db_manager.get_or_create_customer(
        platform="website",
        external_id=session_id,
        name="Клиент с сайта"
    )

    if session_id not in sessions_history:
        sessions_history[session_id] = []

    chat_history = sessions_history[session_id]
    active_order_id = db_manager.get_active_order_id(customer_id)

    if not active_order_id:
        active_order_id = db_manager.create_new_order(customer_id)
        chat_history.clear()

    if not chat_history:
        sieve_result = await ai_sieve.analyze_lead(user_text)
        db_manager.save_lead(customer_id, user_text, sieve_result['score'], sieve_result['status'])

        if sieve_result['status'] == 'trash':
            db_manager.update_order_from_ai(active_order_id, customer_id, {"action": "trash"})
            if session_id in sessions_history:
                del sessions_history[session_id]
            return {
                "reply_text": "Извините, мы не смогли распознать ваш запрос как заявку на ремонт. Если у вас конкретный вопрос по технике Apple, пожалуйста, сформулируйте его точнее.",
                "action": "trash"
            }

    chat_history.append({"role": "user", "text": user_text})

    user_messages = [msg["text"] for msg in chat_history if msg["role"] == "user"]
    combined_search_text = " ".join(user_messages)
    real_prices = search_prices_in_db(combined_search_text)

    closer_result = await ai_closer.generate_response(chat_history, real_prices)

    ai_reply = closer_result.get('reply_text', 'Ошибка генерации ответа.')
    action = closer_result.get('action', 'active')

    db_manager.update_order_from_ai(active_order_id, customer_id, closer_result)
    chat_history.append({"role": "assistant", "text": ai_reply})

    if action in ['success', 'delayed']:
        if action == 'success':
            phone = closer_result.get("phone", "Не указан")
            await send_telegram_alert(active_order_id, closer_result, phone)
        if session_id in sessions_history:
            del sessions_history[session_id]

    return {
        "reply_text": ai_reply,
        "action": action
    }

# ==========================================
# Страница /crm
# ==========================================
@app.get("/crm", response_class=HTMLResponse)
def crm_dashboard(username: str = Depends(authenticate_admin)):
    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Fl1ght Admin — Управление ИИ-Скаутами</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-900 text-gray-100 font-sans min-h-screen">
        <div class="container mx-auto px-4 py-8">

            <div class="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-gray-800 pb-6 mb-6 gap-4">
                <div>
                    <h1 class="text-3xl font-extrabold text-white tracking-tight">🕵️‍♂️ Fl1ght Scout Admin</h1>
                    <p class="text-gray-400 mt-1">Мониторинг внутренней работы ИИ-Сита, радаров и перехвата лидов</p>
                </div>
                <div class="flex flex-wrap gap-2 items-center">
                    <button onclick="triggerScript('/api/crm/run-tg-finder')" class="bg-blue-600 hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-lg transition text-xs shadow-md">
                        🚀 Ищейка TG (Чат ЖК)
                    </button>
                    <button onclick="triggerScript('/api/crm/run-vk-finder')" class="bg-purple-600 hover:bg-purple-700 text-white font-semibold px-4 py-2 rounded-lg transition text-xs shadow-md">
                        📢 Ищейка VK (Паблики)
                    </button>
                    <div class="bg-gray-800 px-4 py-2 rounded-lg border border-gray-700 text-xs">
                        <span class="text-green-400 font-semibold">● Радары active</span>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center mb-6">
                <div class="bg-gray-800 p-4 rounded-xl border border-gray-700 shadow-sm">
                    <div class="text-xs text-gray-400 uppercase tracking-wider font-semibold">Всего проверено</div>
                    <div id="stat-total" class="text-3xl font-bold text-white mt-1">0</div>
                </div>
                <div class="bg-gray-800 p-4 rounded-xl border border-gray-700 shadow-sm">
                    <div class="text-xs text-green-400 uppercase tracking-wider font-semibold">🎯 Горячие Лиды</div>
                    <div id="stat-leads" class="text-3xl font-bold text-green-400 mt-1">0</div>
                </div>
                <div class="bg-gray-800 p-4 rounded-xl border border-gray-700 shadow-sm">
                    <div class="text-xs text-gray-500 uppercase tracking-wider font-semibold">🗑️ Отсеянный спам</div>
                    <div id="stat-trash" class="text-3xl font-bold text-gray-400 mt-1">0</div>
                </div>
                <div class="bg-gray-800 p-4 rounded-xl border border-gray-700 shadow-sm">
                    <div class="text-xs text-blue-400 uppercase tracking-wider font-semibold">Конверсия радара</div>
                    <div id="stat-conv" class="text-3xl font-bold text-blue-400 mt-1">0%</div>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-4 gap-6">

                <div class="lg:col-span-3 space-y-4">

                    <div class="bg-gray-800 p-4 rounded-xl border border-gray-700 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                        <div class="flex flex-wrap gap-4 w-full sm:w-auto">
                            <div class="flex flex-col">
                                <label class="text-xs text-gray-400 mb-1 font-medium">Решение Сита:</label>
                                <select id="filter-status" onchange="filterScoutLogs()" class="bg-gray-900 border border-gray-700 text-white rounded-lg p-2 text-sm focus:outline-none focus:border-blue-500 cursor-pointer">
                                    <option value="all">Все сообщения</option>
                                    <option value="lead">🎯 Целевые Лиды</option>
                                    <option value="trash">🗑️ Отсеянный Мусор</option>
                                </select>
                            </div>
                            <div class="flex flex-col">
                                <label class="text-xs text-gray-400 mb-1 font-medium">Фильтр по Скаутам:</label>
                                <select id="filter-platform" onchange="filterScoutLogs()" class="bg-gray-900 border border-gray-700 text-white rounded-lg p-2 text-sm focus:outline-none focus:border-blue-500 cursor-pointer">
                                    <option value="all">Все платформы</option>
                                    <option value="telegram">Telegram Радар</option>
                                    <option value="vk">ВКонтакте Радар</option>
                                    <option value="avito">Авито (заглушка)</option>
                                </select>
                            </div>
                        </div>
                        <button onclick="loadScouts()" class="w-full sm:w-auto bg-gray-700 hover:bg-gray-600 border border-gray-600 text-white font-semibold px-4 py-2 rounded-lg transition text-sm flex items-center justify-center gap-2 self-end sm:self-center">
                            🔄 Обновить логи
                        </button>
                    </div>

                    <div class="bg-gray-800 rounded-xl shadow-xl overflow-hidden border border-gray-700">
                        <div class="overflow-x-auto">
                            <table class="w-full text-left border-collapse">
                                <thead>
                                    <tr class="bg-gray-850 text-gray-400 text-xs uppercase border-b border-gray-700 tracking-wider">
                                        <th class="p-4 w-1/4">Скаут / Источник</th>
                                        <th class="p-4 w-5/12">Текст сообщения</th>
                                        <th class="p-4 text-center w-1/12">Score</th>
                                        <th class="p-4 w-1/6">Решение ИИ</th>
                                        <th class="p-4 w-1/8 text-right">Время</th>
                                    </tr>
                                </thead>
                                <tbody id="scouts-table-body" class="divide-y divide-gray-700 text-sm">
                                    <tr><td colspan="5" class="p-8 text-center text-gray-500">Синхронизация логов...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <div class="lg:col-span-1 space-y-4">
                    <div class="bg-gray-800 p-5 rounded-xl border border-gray-700 shadow-md">
                        <h3 class="text-base font-bold text-white mb-1 flex items-center gap-2">
                            📡 Мониторинг пабликов ВК
                        </h3>
                        <p class="text-xs text-gray-400 mb-4 leading-relaxed">Список сообществ, загруженных из изолированного конфигурационного файла скаута.</p>
                        <div id="groups-list-container" class="space-y-2 max-h-[580px] overflow-y-auto pr-1">
                            <div class="text-xs text-gray-500 text-center py-4">Загрузка списка пабликов...</div>
                        </div>
                    </div>
                </div>

            </div>
        </div>

        <script>
            let allScoutLogs = [];

            async function triggerScript(endpoint) {
                if (!confirm("Вы уверены, что хотите запустить этот фоновый процесс поиска? Это может занять некоторое время.")) return;
                try {
                    const response = await fetch(endpoint, { method: 'POST' });
                    if (!response.ok) throw new Error('Ошибка сервера');
                    const data = await response.json();
                    alert(data.message);
                    loadScouts();
                    loadGroupsWidget();
                } catch (e) {
                    alert("Ошибка запуска Ищейки: " + e.message);
                }
            }

            async function loadScouts() {
                try {
                    const response = await fetch('/api/crm/scouts');
                    if (!response.ok) throw new Error('Ошибка сети');
                    const data = await response.json();
                    allScoutLogs = data.scouts;

                    filterScoutLogs();
                } catch (e) {
                    document.getElementById('scouts-table-body').innerHTML = `<tr><td colspan="5" class="p-8 text-center text-red-400 font-mono">❌ Ошибка: ${e.message}</td></tr>`;
                }
            }

            async function loadGroupsWidget() {
                const container = document.getElementById('groups-list-container');
                try {
                    const response = await fetch('/api/crm/groups');
                    if (!response.ok) throw new Error('Ошибка');
                    const groups = await response.json();
                    if (Object.keys(groups).length === 0) {
                        container.innerHTML = `<div class="text-xs text-gray-500 text-center py-4">Файл групп пуст.<br>Запустите Ищейку.</div>`;
                        return;
                    }

                    container.innerHTML = '';
                    Object.values(groups).forEach(g => {
                        container.innerHTML += `
                            <div class="bg-gray-900/60 p-2.5 rounded-lg border border-gray-750 flex justify-between items-center text-xs">
                                <div class="truncate mr-2">
                                    <div class="font-semibold text-gray-200 truncate">${g.name}</div>
                                    <a href="https://vk.com/${g.domain}" target="_blank" class="text-[10px] text-blue-400 hover:underline">vk.com/${g.domain}</a>
                                </div>
                                <span class="bg-green-950 text-green-400 border border-green-900 px-1.5 py-0.5 rounded text-[10px] font-bold">LIVE</span>
                            </div>
                        `;
                    });
                } catch (e) {
                    container.innerHTML = `<div class="text-xs text-red-400 text-center py-4">Не удалось загрузить виджет</div>`;
                }
            }

            function updateStats(filteredLogs) {
                const total = filteredLogs.length;
                const leads = filteredLogs.filter(l => l.status === 'lead').length;
                const trash = total - leads;
                const conv = total > 0 ? Math.round((leads / total) * 100) : 0;

                document.getElementById('stat-total').innerText = total;
                document.getElementById('stat-leads').innerText = leads;
                document.getElementById('stat-trash').innerText = trash;
                document.getElementById('stat-conv').innerText = conv + '%';
            }

            function filterScoutLogs() {
                const tbody = document.getElementById('scouts-table-body');
                const sFilter = document.getElementById('filter-status').value;
                const pFilter = document.getElementById('filter-platform').value;

                let filtered = allScoutLogs;

                // статус лида (lead / trash)
                if (sFilter !== 'all') filtered = filtered.filter(l => l.status === sFilter);

                // платформа скаута
                if (pFilter !== 'all') filtered = filtered.filter(l => l.platform === pFilter);

                // статистика считается по уже отфильтрованным строкам
                updateStats(filtered);

                if (filtered.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="5" class="p-8 text-center text-gray-500">Записей с такими фильтрами не найдено.</td></tr>`;
                    return;
                }

                tbody.innerHTML = '';
                filtered.forEach(log => {
                    let verdictBadge = log.status === 'lead'
                        ? '<span class="text-green-400 bg-green-950/60 border border-green-800 px-2 py-0.5 rounded text-xs font-semibold tracking-wide">🎯 ЛИД</span>'
                        : '<span class="text-gray-400 bg-gray-900 border border-gray-700 px-2 py-0.5 rounded text-xs">🗑&nbsp;МУСОР</span>';

                    let platformBadge = '';
                    if (log.platform === 'telegram') {
                        platformBadge = '<span class="text-blue-400 bg-blue-950/40 border border-blue-900 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase mr-1.5">TG</span>';
                    } else if (log.platform === 'vk') {
                        platformBadge = '<span class="text-purple-400 bg-purple-950/40 border border-purple-900 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase mr-1.5">VK</span>';
                    } else if (log.platform === 'avito') {
                        platformBadge = '<span class="text-green-400 bg-green-950/40 border border-green-900 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase mr-1.5">AVITO</span>';
                    }

                    const date = new Date(log.created_at).toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});

                    let textCell = log.post_url
                        ? `<a href="${log.post_url}" target="_blank" class="text-blue-400 hover:underline block max-w-lg truncate font-medium">${log.text}</a>`
                        : `<span class="block max-w-lg truncate text-gray-300">${log.text}</span>`;

                    tbody.innerHTML += `
                        <tr class="hover:bg-gray-750/50 transition duration-150 border-b border-gray-800/60">
                            <td class="p-4 font-bold text-gray-400 text-xs flex items-center">${platformBadge} <span class="truncate max-w-[160px]">${log.chat_name.replace('Комменты: ', '').replace('Стена: ', '')}</span></td>
                            <td class="p-4 text-xs font-mono">${textCell}</td>
                            <td class="p-4 text-center font-bold ${log.score >= 7 ? 'text-green-400' : 'text-gray-400'}">${log.score}/10</td>
                            <td class="p-4">${verdictBadge}</td>
                            <td class="p-4 text-gray-400 text-xs font-mono text-right">${date}</td>
                        </tr>
                    `;
                });
            }

            window.onload = function() {
                loadScouts();
                loadGroupsWidget();
            };
        </script>
    </body>
    </html>
    """
    return html_content

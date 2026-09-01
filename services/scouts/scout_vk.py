import os
import sys
import json
import time
import aiohttp
import asyncio
import redis
import random
from celery import shared_task
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from services.scouts.tasks import analyze_scout_message

VK_USER_TOKEN = os.getenv("VK_USER_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)
GROUPS_FILE = os.path.join(PROJECT_ROOT, "services/scouts/monitored_groups.json")

# ==========================================
# Окно актуальности
# ==========================================
MAX_POST_AGE_DAYS = 5  # старше окна не комментирую — мёртвые треды
MAX_POST_AGE_SECONDS = MAX_POST_AGE_DAYS * 24 * 60 * 60

async def scan_group_comments(session: aiohttp.ClientSession, group_domain: str, keywords: list):
    """Стена и комментарии только у записей не старше MAX_POST_AGE_DAYS."""
    current_time = int(time.time())

    print(f"🔎 [РАДАР] Проверяю паблик: vk.com/{group_domain}")

    wall_url = "https://api.vk.com/method/wall.get"
    wall_params = {"domain": group_domain.strip(), "count": 50, "v": "5.199", "access_token": VK_USER_TOKEN}

    try:
        async with session.get(wall_url, params=wall_params, timeout=10) as resp:
            wall_data = await resp.json()

            if "error" in wall_data:
                print(f"⚠️ [VK API ERROR] Паблик {group_domain}: {wall_data['error'].get('error_msg', wall_data)}")
                return

            posts = wall_data.get("response", {}).get("items", [])

            # барахолка и реклама — в Сито не отправляю
            stop_words = [
                "продам", "продаю", "продажа", "обмен", "меняю",
                "магазин", "гарантия", "рассрочка", "в наличии",
                "опт", "заказ", "покупка", "куплю"
            ]

            for post in posts:
                owner_id = post["owner_id"]
                post_id = post["id"]
                post_date = post.get("date", 0)

                if (current_time - post_date) > MAX_POST_AGE_SECONDS:
                    continue

                post_text = post.get("text", "").strip()
                combined_post_id = f"wall_{owner_id}_{post_id}"

                if post_text and 10 <= len(post_text) <= 500:
                    if not redis_client.exists(f"vk_post:{combined_post_id}"):
                        lower_post_text = post_text.lower()

                        has_stop = any(bad_word in lower_post_text for bad_word in stop_words)
                        has_key = any(k in lower_post_text for k in keywords)

                        if not has_stop and has_key:
                            print(f"🎯 [НАХОДКА] Пост на стене vk.com/wall{owner_id}_{post_id} содержит ключи. Отправляем в ИИ.")
                            redis_client.setex(f"vk_post:{combined_post_id}", 172800, "1")
                            analyze_scout_message.delay(
                                platform="vk",
                                chat_name=f"Стена: {group_domain}",
                                owner_id=owner_id,
                                post_id=post_id,
                                text=f"[ПОСТ] {post_text}"
                            )

                if post.get("comments", {}).get("count", 0) == 0:
                    continue

                comments_url = "https://api.vk.com/method/wall.getComments"
                comments_params = {
                    "owner_id": owner_id,
                    "post_id": post_id,
                    "count": 40,
                    "sort": "desc",
                    "v": "5.199",
                    "access_token": VK_USER_TOKEN
                }

                await asyncio.sleep(0.35)  # пауза под лимит VK (~3 req/s на wall.get + getComments)

                async with session.get(comments_url, params=comments_params, timeout=10) as c_resp:
                    c_data = await c_resp.json()

                    if "error" in c_data:
                        print(f"⚠️ [VK API ERROR - КОММЕНТАРИИ] Паблик {group_domain}: {c_data['error'].get('error_msg', c_data)}")
                        continue

                    comments = c_data.get("response", {}).get("items", [])

                    for comment in comments:
                        comment_id = comment["id"]
                        combined_id = f"comment_{owner_id}_{comment_id}"
                        text = comment.get("text", "").strip()

                        if not text or len(text) < 5 or len(text) > 250:
                            continue

                        comment_date = comment.get("date", 0)
                        if (current_time - comment_date) > MAX_POST_AGE_SECONDS:
                            continue

                        if redis_client.exists(f"vk_post:{combined_id}"):
                            continue

                        lower_text = text.lower()

                        if any(bad_word in lower_text for bad_word in stop_words):
                            continue

                        if not any(k in lower_text for k in keywords):
                            continue

                        print(f"🎯 [НАХОДКА] Комментарий под постом vk.com/wall{owner_id}_{post_id} содержит ключи. Отправляем в ИИ.")
                        redis_client.setex(f"vk_post:{combined_id}", 172800, "1")

                        analyze_scout_message.delay(
                            platform="vk",
                            chat_name=f"Комменты: {group_domain}",
                            owner_id=owner_id,
                            post_id=post_id,
                            text=f"[КОММЕНТАРИЙ] {text}"
                        )
    except Exception as e:
        print(f"[ERROR SCAN] Ошибка паблика {group_domain}: {e}")

async def main_scout_flow():
    if not VK_USER_TOKEN:
        print("[VK SCOUT] Ошибка: Не задан VK_USER_TOKEN!")
        return

    keywords_raw = os.getenv("SCOUT_KEYWORDS", "ремонт,мастер,починить,экран,дисплей,айфон,iphone")
    keywords = [k.strip().lower() for k in keywords_raw.split(",") if k.strip()]

    groups = []
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                groups = [g["domain"] for g in data.values() if g.get("is_active", True)]
        except Exception as e:
            print(f"❌ [VK RADAR] Ошибка чтения JSON пабликов: {e}")

    if not groups:
        print("⚠️ [VK RADAR] JSON файл групп пуст. Используем фолбэк.")
        groups = ["overhear_moscow"]

    print(f"📡 [VK RADAR] Запуск обхода {len(groups)} пабликов. Фильтр актуальности: до {MAX_POST_AGE_DAYS} дней.")

    async with aiohttp.ClientSession() as session:
        for idx, group in enumerate(groups):
            await scan_group_comments(session, group, keywords)

            if idx < len(groups) - 1:
                pause = random.uniform(3.0, 7.0)
                print(f"⏳ [АНТИБАН] Ждем {pause:.1f} сек. перед следующим пабликом...")
                await asyncio.sleep(pause)

@shared_task(name="services.scouts.scout_vk.run_vk_scout")
def run_vk_scout():
    asyncio.run(main_scout_flow())
    return "OK"

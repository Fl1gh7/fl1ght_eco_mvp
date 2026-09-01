import os
import sys
import json
import time
import requests
from celery import shared_task
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

VK_USER_TOKEN = os.getenv("VK_USER_TOKEN")
GROUPS_FILE = os.path.join(PROJECT_ROOT, "services/scouts/monitored_groups.json")

def search_and_save_groups():
    if not VK_USER_TOKEN:
        print("❌ [FINDER] VK_USER_TOKEN в .env пуст")
        return

    districts = [
        "хорошевский", "сао", "сокол", "аэропорт", "динамо", "ховрино", 
        "головинский", "коптево", "войковский", "дегунино", "бескудниково", 
        "отрадное", "бибирево", "алтуфьево", "строгино", "митино"
    ]

    jks = [
        "Амурский Парк", "Тринити", "Селигер Сити", "Савеловский Сити", 
        "Царская Площадь", "Прайм Парк", "Хорошевский", "Лица", "Династия", 
        "Искра-Парк", "ВТБ Арена Парк", "Черняховского 19", "Фестиваль Парк",
        "D1", "Discovery", "Водный", "Маяковский", "Невский"
    ]
    
    search_queries = []
    for d in districts:
        search_queries.append(f"подслушано {d}")
        search_queries.append(f"соседи {d}")
        
    for j in jks:
        search_queries.append(f"жк {j}")
        search_queries.append(f"{j} соседи")

    # Список пабликов пишу с нуля: барахолки прошлого прогона не оставляю.
    existing_groups = {}

    print(f"🕵️‍♂️ [FINDER] Запуск целевого сканирования ЖК и Подслушано...")
    print(f"В очереди {len(search_queries)} строгих географических запросов.")
    url = "https://api.vk.com/method/groups.search"

    for query in search_queries:
        print(f"⏳ Ищу паблики по запросу: {query}...")
        params = {
            "q": query,
            "count": 15,
            "type": "group",
            "v": "5.199",
            "access_token": VK_USER_TOKEN
        }
        try:
            resp = requests.get(url, params=params, timeout=(5, 5)).json()
            
            if "error" in resp:
                print(f"⚠️ [FINDER] Ошибка ВК API: {resp['error'].get('error_msg')}")
                continue
                
            items = resp.get("response", {}).get("items", [])
            
            for item in items:
                if item.get("is_closed") == 0:
                    domain = item.get("screen_name")
                    if domain and domain not in existing_groups:
                        existing_groups[domain] = {
                            "name": item.get("name"),
                            "domain": domain,
                            "is_active": True
                        }
            time.sleep(2)
        except Exception as e:
            print(f"❌ [FINDER] Ошибка сети на запросе '{query}': {e}")

    with open(GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_groups, f, ensure_ascii=False, indent=4)
    
    print(f"\n✅ [FINDER] Успех! Сформирована новая чистая база.")
    print(f"Сохранено ровно {len(existing_groups)} целевых пабликов (ЖК и Подслушано) в {GROUPS_FILE}")


@shared_task(name="services.scouts.group_finder.run_finder")
def run_finder():
    search_and_save_groups()
    return "OK"


if __name__ == "__main__":
    search_and_save_groups()

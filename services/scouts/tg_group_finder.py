import os
import sys
import asyncio
import random
from pyrogram import Client
from pyrogram.raw import functions
from pyrogram.errors import FloodWait, UserAlreadyParticipant, InviteRequestSent
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

API_ID = os.getenv("TELETHON_API_ID")
API_HASH = os.getenv("TELETHON_API_HASH")

app = Client(
    "scout2",
    api_id=int(API_ID),
    api_hash=API_HASH,
    workdir=PROJECT_ROOT
)

# ЖК Москвы — узкие запросы, у contacts.Search лимит 10 результатов.
TARGET_JKS = [
    "Саларьево Парк", "Люблинский Парк", "Бунинские луга",
    "Символ", "Зиларт", "Сердце Столицы", "Метрополия",
    "Селигер Сити", "Скандинавия", "Прокшино", "Испанские кварталы",
    "Летний Сад", "Остров", "Город на реке Тушино", "Царская площадь",
    "Прайм Парк", "Хорошевский", "Династия", "Водный", "Маяковский"
]

PREFIXES = ["ЖК", "Соседи", "Чат"]
SUFFIXES = ["соседи", "чат", "собственники", "жильцы"]

def generate_search_queries():
    """Узкие запросы: у contacts.Search не больше 10 чатов на q."""
    queries = []
    for jk in TARGET_JKS:
        queries.append(f"ЖК {jk} соседи")
        queries.append(f"ЖК {jk} чат")
        queries.append(f"{jk} собственники")
    return queries

async def search_and_join():
    search_queries = generate_search_queries()
    print(f"🚀 [TG FINDER] Сгенерировано {len(search_queries)} точечных запросов по ЖК Москвы.")

    # отсекаем каналы застройщиков без «соседи/чат/жильцы» в названии
    valid_title_markers = ["соседи", "чат", "жильцы", "собственники", "корпус", "дом"]

    async with app:
        for query in search_queries:
            print(f"\n🔍 Ищу по запросу: '{query}'")
            try:
                results = await app.invoke(
                    functions.contacts.Search(
                        q=query,
                        limit=10
                    )
                )

                if not results.chats:
                    print("  Ничего не найдено.")
                    continue

                for chat in results.chats:
                    if hasattr(chat, "megagroup") and chat.megagroup:
                        title_lower = chat.title.lower()

                        if not any(marker in title_lower for marker in valid_title_markers):
                            print(f"  ⏭️ Пропуск (не похоже на чат жильцов): {chat.title}")
                            continue

                        chat_identifier = chat.username if chat.username else chat.id

                        try:
                            print(f"⏳ Пытаюсь вступить в: {chat.title} (@{chat.username})")
                            await app.join_chat(chat_identifier)
                            print(f"  ✅ Успешно вступили!")

                            pause = random.uniform(60.0, 600.0)  # пауза 1–10 мин, иначе flood
                            print(f"  💤 Имитируем чтение чата... Ждем {pause / 60:.1f} минут.")
                            await asyncio.sleep(pause)

                        except UserAlreadyParticipant:
                            print(f"  ℹ️ Уже состоим в этом чате.")
                        except InviteRequestSent:
                            print(f"  📨 Отправлена заявка на вступление (закрытый чат).")
                            pause_closed = random.uniform(60.0, 180.0)
                            print(f"  💤 Ждем {pause_closed / 60:.1f} минут перед следующим...")
                            await asyncio.sleep(pause_closed)
                        except FloodWait as e:
                            print(f"  🚨 ЛИМИТ ТЕЛЕГРАМА! Ждем {e.value} секунд...")
                            await asyncio.sleep(e.value + 5)
                        except Exception as e:
                            print(f"  ❌ Ошибка вступления: {e}")

            except FloodWait as e:
                print(f"🚨 Флуд-контроль на поиске! Пауза {e.value} сек.")
                await asyncio.sleep(e.value)
            except Exception as e:
                print(f"❌ Ошибка поиска по '{query}': {e}")

    print("\n🏁 [TG FINDER] Работа завершена!")

if __name__ == "__main__":
    try:
        asyncio.run(search_and_join())
    except KeyboardInterrupt:
        print("\n🛑 Скрипт остановлен.")

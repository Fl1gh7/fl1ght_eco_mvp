# ServiceFl1ght

**AI sales agent for a field Apple-repair service** — qualifies inbound demand, quotes from a real price list, collects a complete job ticket, and notifies a technician. MVP for a Moscow on-site repair business.

Автономный менеджер выездного сервиса: отсеивает спам, ведёт диалог как живой консультант, собирает заказ (устройство, поломка, цена, адрес, слот, телефон) и пишет мастеру в Telegram.

**Для QA:** ключи в `.env`, сценарии — в [TESTING.md](TESTING.md).

**Прод на VPS (Debian, лучше 2 GB RAM):** systemd + nginx + Redis — [deploy/DEPLOY.md](deploy/DEPLOY.md). Один сервер, без Docker и Kubernetes.

---

## Для рекрутера — за 30 секунд

| | |
|---|---|
| **Роль проекта** | Solo MVP: продукт + бэкенд + интеграции + промпты |
| **Домен** | Операционный SaaS / AI-агент в продажах услуг |
| **Стек** | Python 3.11, FastAPI, Celery, Redis, SQLite, YandexGPT, aiohttp |
| **Интеграции** | VK API, Telegram Bot API, Pyrogram (user session); Avito — заглушка |
| **Паттерны** | Webhooks, background jobs, structured LLM output, lead scoring, CRM |
| **Объём** | ~2.3k строк прикладного кода, не сгенерированный CRUD-скелет |

**Что умеет кандидат, если судить по этому репозиторию:** спроектировать конвейер LLM под бизнес-правила, а не «чат с GPT»; подключить несколько каналов к одному ядру; не блокировать API тяжёлым обходом соцсетей (очередь); учесть лимиты и антибан VK.

---

## Задача, которую решает продукт

Сервисный центр чинит iPhone/iPad с выездом. Менеджер не успевает отвечать в VK, Telegram и на сайте одновременно. Холодный спрос живёт в пабликах и чатах ЖК: «у кого поменять стекло?». Avito в архитектуре заложен как следующий канал, но **не реализован**.

ServiceFl1ght:

1. **Находит** свежие сообщения с ключевыми словами (ремонт, дисплей, iPhone…).
2. **Отсеивает** рекламу и барахолку моделью-классификатором («Сито»).
3. **Цитирует** позиции из Excel-прайса, а не из галлюцинаций модели.
4. **Дожимает** диалог до шести обязательных полей и шлёт алерт в Telegram.

Это не чат-виджет «для галочки». Это воронка с явным state machine, который модель **не имеет права** закрыть, пока не собраны все поля.

---

## Архитектура

```
  Сайт / VK / Telegram Bot                  VK-паблики / чаты TG
           │                                        │
           ▼                                        ▼
     FastAPI webhooks                    Celery scout + Pyrogram
     (секрет VK / Telegram)                         │
           │                                        │
           └──────────────┬─────────────────────────┘
                          ▼
                    ИИ-Сито (YandexGPT)
                    score 0–100, target | trash
                          │
                          ▼
                    Матчер прайса (SQLite)
                    services/ai/matcher.py
                          │
                          ▼
                    ИИ-Продавец (YandexGPT)
                    JSON: reply, action, 6 полей заказа
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
           SQLite      CRM UI     Telegram alert
         customers                 (успешный заказ)
         leads
         orders

  Avito: заглушка (501 + api.api.avito.ru). В воронку не входит.
```

**Почему два агента, а не один промпт.** Классификатор работает на низкой температуре и дешёвом контексте. Продавец получает только целевые лиды и реальные цены. Так проще контролировать стоимость токенов и жёсткость воронки.

### Воронка продавца (`action`)

| Статус | Когда |
|---|---|
| `active` | Идёт консультация, не хватает хотя бы одного из 6 полей |
| `success` | Клиент подтвердил модель, поломку, цену, адрес, 2-часовой слот и телефон |
| `delayed` | «Дорого» / «напишу позже» — пауза без фейкового заказа |
| `trash` | Сито отбраковало первое сообщение |

---

## Стек и навыки

| Слой | Технологии | Зачем в резюме |
|---|---|---|
| HTTP API | FastAPI, Pydantic, CORS, HTTP Basic | Асинхронный бэкенд, вебхуки |
| ИИ | YandexGPT Completion API, JSON-контракт, system prompts | Prompt engineering, structured output |
| Поиск по прайсу | SQLite + эвристический скоринг | «Бедный RAG» без эмбеддингов — осознанный trade-off для 300+ позиций |
| Очереди | Celery, Redis, Celery Beat | Периодический обход, дедуп ключей |
| Соцсети | VK Callback + user token, Telegram Bot API, Pyrogram | Несколько официальных API, не один SDK |
| Данные | SQLite: customers, leads, orders, prices | Простая доменная модель CRM |
| Операции | Telegram-алерты, Excel → SQLite, JSON-список пабликов | Понимание, как этим будут пользоваться в смене |
| UI | HTML/JS, Tailwind (админка скаутов), виджет чата | Достаточно, чтобы показать поток заказа |

Python 3.11. Проект рассчитан на Linux-сервер (`systemd` для юзербота-скаута).

---

## Что внутри репозитория

```
ServiceFl1ght/
├── api/main.py                 # FastAPI: вебхуки, чат, CRM, алерты
├── core/
│   ├── config.py               # ключи YandexGPT из .env
│   ├── database.py             # схема SQLite
│   ├── db_manager.py           # слой доступа к заказам/клиентам
│   ├── webhook_auth.py         # секреты Callback VK и Telegram
│   └── celery_app.py           # брокер Redis, Beat-расписание
├── services/
│   ├── ai/sieve.py              # классификатор лида
│   ├── ai/closer.py             # менеджер по продажам
│   ├── ai/matcher.py            # прайс: нормализация + штрафы Max/Mini
│   └── scouts/
│       ├── scout_vk.py         # обход стен и комментариев
│       ├── scout_tg.py         # слушатель групп (user session)
│       ├── scout_avito.py      # заглушка канала Avito
│       ├── group_finder.py     # поиск пабликов ЖК / «Подслушано»
│       ├── tg_group_finder.py  # поиск чатов ЖК
│       ├── avito_client.py     # заглушка: хост api.api.avito.ru нарочно
│       ├── tasks.py            # анализ + автокомментарий VK
│       └── monitored_groups.json
├── frontend/
│   ├── index.html               # лендинг + виджет чата
│   └── crm.html                 # карточки заказов
├── tests/test_db_manager.py    # слой данных: клиент, воронка, лиды
├── tests/test_matcher.py       # матчер прайса
├── tests/test_webhook_auth.py  # секреты вебхуков
├── import_excel.py             # прайс iphone.xlsx → таблица prices
├── test_full_logic.py          # ручной прогон воронки в консоли
└── seller_chat/test_closer.py  # изолированный тест продавца
```

---

## Как запустить локально

Нужны Python 3.11+, Redis, ключ [Yandex Cloud Foundation Models](https://yandex.cloud/foundation-models).

```bash
python -m venv venv
# Linux/macOS
source venv/bin/activate
# Windows
# venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env   # заполнить ключи, пароль CRM задать самому
python core/database.py
python import_excel.py
python -m unittest tests.test_db_manager tests.test_matcher tests.test_webhook_auth
```

API:

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Воркер и планировщик (обход VK):

```bash
celery -A core.celery_app worker --loglevel=info
celery -A core.celery_app beat --loglevel=info
```

Юзербот-скаут Telegram (отдельный процесс, нужен `TELETHON_API_ID` / `HASH`):

```bash
python services/scouts/scout_tg.py
```

Проверка воронки без мессенджеров:

```bash
python test_full_logic.py
```

| URL | Что |
|---|---|
| `http://localhost:8000/api/chat` | Чат с сайта |
| `http://localhost:8000/crm` | Админка скаутов (Basic Auth) |
| `POST /api/vk-webhook` | Callback VK (`secret` в теле) |
| `POST /api/tg-webhook` | Telegram Bot (заголовок `X-Telegram-Bot-Api-Secret-Token`) |
| `POST /api/avito-webhook` | Заглушка, всегда **501** |

Статику `frontend/` удобно отдать через nginx или смонтировать в FastAPI (`StaticFiles`) — в MVP HTML админки скаутов встроен в `/crm`.

---

## Переменные окружения

Скопируйте `.env.example`. **Не коммитьте `.env`.**

| Переменная | Назначение |
|---|---|
| `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` | YandexGPT |
| `REDIS_URL` | Брокер Celery и дедуп скаута |
| `CRM_ADMIN_USER`, `CRM_ADMIN_PASS` | Basic Auth админки |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Бот продаж + алерты о заказах |
| `TELEGRAM_WEBHOOK_SECRET` | `secret_token` при setWebhook |
| `VK_GROUP_TOKEN`, `VK_CONFIRMATION_CODE` | Callback сообщества |
| `VK_CALLBACK_SECRET` | Поле secret в настройках Callback API VK |
| `VK_USER_TOKEN`, `VK_GROUP_ID` | Обход стен и комментарии от имени группы |
| `TELETHON_API_ID`, `TELETHON_API_HASH` | Юзер-сессия скаута TG |
| `SCOUT_KEYWORDS` | Ключи радара VK (через запятую) |

После смены `TELEGRAM_WEBHOOK_SECRET` вебхук бота нужно выставить заново: в `setWebhook` передать тот же `secret_token`. В кабинете VK Callback укажите тот же `secret`, что в `VK_CALLBACK_SECRET`. Без этих двух переменных входящие с мессенджеров сервер не примет. Чат с сайта (`/api/chat`) работает как раньше.

---

## Принятые технические решения

- **Structured output, не свободный текст.** Модель обязана вернуть JSON. Статус сделки — контракт для CRM, а не «настроение» ответа.
- **Прайс из БД, не из промпта «придумай цену».** Галлюцинации на деньгах недопустимы. Матчер сужает контекст до 6 строк.
- **Секреты вебхуков.** VK Callback и Telegram Bot не принимают события без shared secret. Сайтовый `/api/chat` секрета не требует.
- **Avito — заглушка.** Хост `api.api.avito.ru` оставлен специально, чтобы не выглядело как рабочий API. Вебхук отвечает 501, клиент в сеть не ходит.
- **Дедуп в Redis.** Один пост/комментарий не уходит в ИИ дважды (TTL 48 часов).
- **Фильтр свежести.** Скаут VK игнорирует записи старше 5 дней — не комментируем мёртвые треды.
- **Очередь, не цикл в API.** Обход сотен пабликов не должен держать HTTP-воркер.
- **Паузы и стоп-слова.** Явная работа с rate limit VK и отсев «продам / обмен».

---

## Статус MVP и честный бэклог

Это рабочий каркас продукта, не production-hardening.

Сейчас в бэклоге (то, что я называю на собеседовании сам):

- PostgreSQL вместо SQLite, история диалога в БД (сейчас контекст в памяти процесса)
- Реализовать Avito Messenger (сейчас заглушка: 501 и `api.api.avito.ru`)
- Автотесты ответа продавца (матчер и слой данных уже покрыты: `python -m unittest`)
- Docker Compose: api + redis + worker + beat
- Вынести HTML из `api/main.py`, один UI для заказов и скаутов
- Pydantic-валидация ответа LLM с retry
- CORS на домен лендинга, экранирование HTML в админке скаутов

Скаут-модули работают с публичными площадками. В проде их нужно держать в рамках правил VK / Telegram и антиспам-политики; целевой канал продаж — официальный бот и сообщения сообщества, не массовый холодный аутрич.

---

## Как это показывать на собеседовании

1. Воронка: почему 6 полей и почему `success` запрещён раньше.
2. Почему два вызова LLM, а не один.
3. Как матчер штрафует iPhone 15 Pro Max, если клиент сказал «пятнашка».
4. Зачем Redis между скаутом и ИИ.
5. Что сломается при двух воркерах uvicorn (честный ответ: in-memory история).

Демо без ключей соцсетей: `test_full_logic.py` + виджет `/api/chat`.

---

## Автор

Пет-проект / MVP для портфолио. Бэкенд, интеграции и продуктовая логика — в одном репозитории.

# ServiceFl1ght

**AI sales agent for on-site Apple repair** — MVP: inbound demand, a real price list, a six-field job ticket, a ping to the technician.

Автономный менеджер выездного сервиса в Москве: отсеивает спам, ведёт диалог как консультант, собирает заказ и пишет мастеру в Telegram.

Живой контур: [fl1ght.ru](https://fl1ght.ru) (чат), [admin.fl1ght.ru](https://admin.fl1ght.ru) (скауты), [crm.fl1ght.ru](https://crm.fl1ght.ru) (заказы). Прод: [deploy/DEPLOY.md](deploy/DEPLOY.md). Локальный прогон воронки: [TESTING.md](TESTING.md).

---

## Зачем этот репозиторий

Соло-MVP: продукт, бэкенд, интеграции и промпты в одном месте. Не CRUD-скелет.

| | |
|---|---|
| **Роль** | Операционный AI-агент в продажах услуг |
| **Стек** | Python 3.11, FastAPI, Celery, Redis, SQLite, YandexGPT, aiohttp |
| **Каналы** | сайт, VK Callback, Telegram Bot API, Pyrogram; Avito — заглушка |
| **Паттерны** | вебхуки, очередь, structured LLM output, скоринг лида, простой CRM |

Воронка завязана на правила бизнеса, а не на «чат с GPT». Несколько каналов сходятся в одно ядро. Обход пабликов идёт в Celery, не в HTTP-воркере.

---

## Задача

Сервис чинит iPhone и iPad с выездом. Менеджер не успевает одновременно отвечать в VK, Telegram и на сайте. Холодный спрос сидит в пабликах и чатах ЖК. Avito в схеме есть как следующий канал и **в воронку не входит**.

ServiceFl1ght:

1. Ищет свежие сообщения с ключевыми словами (ремонт, дисплей, iPhone…).
2. Отсеивает рекламу и барахолку классификатором («Сито»).
3. Цитирует Excel-прайс, а не цену из головы модели.
4. Дожимает диалог до шести полей и шлёт алерт в Telegram.

Воронка — явный state machine: модель **не имеет права** закрыть сделку, пока не собраны все поля.

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

Сито и Продавец — два вызова: классификатор на низкой температуре и коротком контексте, продавец видит только целевые лиды и строки прайса. Так дешевле по токенам и жёстче по правилам.

### Статусы воронки (`action`)

| Статус | Когда |
|---|---|
| `active` | Консультация, не хватает хотя бы одного из 6 полей |
| `success` | Клиент подтвердил модель, поломку, цену, адрес, 2-часовой слот и телефон |
| `delayed` | «Дорого» / «напишу позже» — пауза, без фейкового заказа |
| `trash` | Сито отбраковало первое сообщение |

---

## Стек

| Слой | Технологии | Зачем |
|---|---|---|
| HTTP | FastAPI, Pydantic, CORS, HTTP Basic | Вебхуки и админка |
| ИИ | YandexGPT, JSON-контракт, system prompt | Structured output, а не свободный текст |
| Прайс | SQLite + эвристический скоринг | «Бедный RAG» без эмбеддингов — прайс ~300 позиций |
| Очередь | Celery, Redis, Beat | Обход пабликов и дедуп |
| Соцсети | VK Callback + user token, Bot API, Pyrogram | Несколько официальных API |
| Данные | SQLite: customers, leads, orders, prices | Доменная модель CRM без лишнего слоя |
| UI | HTML/JS, Tailwind в админке скаутов, виджет чата | Поток заказа без отдельного SPA |

Python 3.11. Прод — один Debian: systemd, nginx, Redis. Docker и Kubernetes на этой машине не используются: оркестрировать нечего, RAM ушла бы вхолостую.

---

## Структура репозитория

```
ServiceFl1ght/
├── api/main.py                 # вебхуки, чат, CRM, алерты
├── core/
│   ├── config.py               # ключи YandexGPT
│   ├── database.py             # схема SQLite
│   ├── db_manager.py           # заказы и клиенты
│   ├── webhook_auth.py         # shared secret VK / Telegram
│   └── celery_app.py           # Redis, расписание Beat
├── services/
│   ├── ai/sieve.py              # классификатор лида
│   ├── ai/closer.py             # менеджер по продажам
│   ├── ai/matcher.py            # прайс: нормализация, штраф Max/Mini
│   └── scouts/
│       ├── scout_vk.py         # стены и комментарии
│       ├── scout_tg.py         # слушатель групп (user session)
│       ├── scout_avito.py      # заглушка Avito
│       ├── group_finder.py     # поиск пабликов ЖК
│       ├── tg_group_finder.py  # поиск чатов ЖК
│       ├── avito_client.py     # намеренный хост api.api.avito.ru
│       ├── tasks.py            # анализ + комментарий от группы
│       └── monitored_groups.json
├── frontend/
│   ├── index.html               # лендинг и чат
│   └── crm.html                 # карточки заказов
├── tests/                      # слой данных, матчер, секреты вебхуков
├── import_excel.py             # iphone.xlsx → таблица prices
├── test_full_logic.py          # консольный прогон всей воронки
└── seller_chat/test_closer.py  # только Продавец, без Сита
```

---

## Локальный запуск

Нужны Python 3.11+, Redis и ключ [Yandex Cloud Foundation Models](https://yandex.cloud/foundation-models). Секреты — в `.env` (файл в git не входит).

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # ключи и пароль CRM
python core/database.py
python import_excel.py
python -m unittest tests.test_db_manager tests.test_matcher tests.test_webhook_auth
```

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
celery -A core.celery_app worker --beat --concurrency=1 --loglevel=info
python services/scouts/scout_tg.py    # отдельный процесс, нужна сессия Pyrogram
python test_full_logic.py             # воронка без мессенджеров
```

| URL | Назначение |
|---|---|
| `POST /api/chat` | Чат с лендинга |
| `GET /crm` | Админка скаутов (HTTP Basic) |
| `POST /api/vk-webhook` | Callback VK, поле `secret` |
| `POST /api/tg-webhook` | Telegram Bot, заголовок `X-Telegram-Bot-Api-Secret-Token` |
| `POST /api/avito-webhook` | Заглушка, всегда **501** |

HTML админки скаутов встроен в `/crm`. Карточки заказов — `frontend/crm.html`, в проде `crm.fl1ght.ru`.

---

## Переменные окружения

Шаблон — `.env.example`. `.env` в репозиторий не входит.

| Переменная | Зачем |
|---|---|
| `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` | YandexGPT |
| `REDIS_URL` | Брокер Celery и дедуп скаута |
| `CRM_ADMIN_USER`, `CRM_ADMIN_PASS` | Basic Auth админки |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Бот продаж и алерты о заказах |
| `TELEGRAM_WEBHOOK_SECRET` | `secret_token` в setWebhook |
| `VK_GROUP_TOKEN`, `VK_CONFIRMATION_CODE` | Callback сообщества |
| `VK_CALLBACK_SECRET` | Поле secret в Callback API |
| `VK_USER_TOKEN`, `VK_GROUP_ID` | Обход стен, комментарии от группы |
| `TELETHON_API_ID`, `TELETHON_API_HASH` | Юзер-сессия скаута Telegram |
| `SCOUT_KEYWORDS` | Ключи радара VK |

Без `TELEGRAM_WEBHOOK_SECRET` и `VK_CALLBACK_SECRET` входящие из мессенджеров API не принимает. Чат сайта (`/api/chat`) от этого не зависит. После смены секрета вебхук Telegram нужно выставить заново с тем же `secret_token`.

---

## Технические решения

- **JSON, не свободный текст.** Статус сделки — контракт для CRM.
- **Цена из БД.** Матчер отдаёт в промпт до 6 строк прайса, модель не выдумывает сумму.
- **Shared secret на вебхуках.** Сайтовый чат секрета не требует.
- **Avito — заглушка.** Хост `api.api.avito.ru` оставлен специально, чтобы не выглядело как боевой API.
- **Дедуп в Redis** (TTL 48 часов) и окно свежести VK 5 дней — без комментариев под старыми тредами.
- **Очередь, не цикл в API.** Обход пабликов не держит uvicorn.
- **Один процесс Celery (worker + beat)** на маленьком VPS: отдельный beat только отъедал бы память.
- **История диалога в RAM процесса.** Один uvicorn-worker. Два воркера разъедут сессии.

Скауты ходят в публичные площадки. Целевой канал продаж — официальный бот и ЛС сообщества, не массовый холодный аутрич.

---

## Бэклог

Рабочий каркас, не production-hardening:

- PostgreSQL и история диалога в БД
- живой Avito Messenger
- автотесты ответа Продавца (матчер и слой данных уже покрыты unittest)
- один UI вместо HTML внутри `api/main.py` и `frontend/crm.html`
- Pydantic на ответ LLM с retry
- CORS только на домен лендинга, экранирование HTML в админке скаутов

---

## О чём имеет смысл спросить

1. Почему шесть полей и почему `success` запрещён раньше.
2. Зачем два вызова LLM, а не один промпт.
3. Как матчер штрафует iPhone 15 Pro Max, если клиент сказал «пятнашка».
4. Зачем Redis между скаутом и ИИ.
5. Что сломается при двух воркерах uvicorn.

Демо без ключей соцсетей: `test_full_logic.py` и виджет на [fl1ght.ru](https://fl1ght.ru).

# Прод на VPS ServiceFl1ght (Debian, 1 CPU / 1 GB / 10 GB)

Сервер `root@217.26.27.121` слишком маленький для Docker, PostgreSQL и нескольких воркеров uvicorn. Оставляем то, что уже есть в коде: SQLite, Redis, один процесс API, один Celery (worker+beat), юзербот TG.

Сейчас занято ~0.6 GB RAM и ~4.8 GB диска — перед установкой нужен снимок и чистка старого стека.

---

## Как жить с проектом

| Где | Что |
|---|---|
| Ноутбук | Код, git, README, тесты без сервера (`unittest`, при желании `test_full_logic.py`) |
| GitHub | Репозиторий **без** `.env`, `database.db`, `*.session` |
| VPS | Единственный прод: `/opt/servicefl1ght`, systemd, nginx, Redis |

`.env` и файл сессии Pyrogram (`scout2.session`) копируете на сервер руками, в git не кладёте.

---

## Что запускать (и что нет)

| Процесс | systemd | Зачем | RAM примерно |
|---|---|---|---|
| nginx | `nginx` | HTTPS, статика, прокси на API | мало |
| redis-server | `redis-server` | очередь скаута VK, дедуп | лимит 64 MB |
| API | `servicefl1ght-api` | FastAPI, чат, вебхуки, `/crm` | ~150 MB |
| Celery | `servicefl1ght-worker` | обход VK + недельный finder. Beat в том же процессе | ~150 MB |
| Юзербот | `scout_tg` | слушатель групп. Имя юнита **не менять** — его стопает кнопка в админке | ~150 MB |

Не ставить: Docker, Kubernetes, Postgres, второй uvicorn-worker, отдельный `celery beat`. На одной маленькой машине они только отъедают RAM. Если в панели добавить ещё 1 GB (итого 2 GB) — стека nginx + Redis + API + Celery + юзербот хватает с запасом, кластер не нужен.

Swap 2 GB обязателен. Без него при скауте VK сервер может зависнуть.

**Swap** — это файл на диске, который Linux использует как запасную «медленную RAM». Если процессы (API + Celery + юзербот) на секунду не влезают в гигабайт памяти, система пишет лишнее на диск и не убивает процессы (OOM). На SSD это медленнее живой RAM, но для редких пиков достаточно. На Timeweb это не отдельная услуга: файл создаётся командами из раздела 2. Дополнительный гигабайт RAM в панели — живая память, она лучше swap; swap всё равно оставляем.

---

## 1. Снимок и доступ

В панели Timeweb: **Снапшот**, затем с ноутбука:

```bash
ssh root@217.26.27.121
```

Дальше все команды на сервере.

## 2. Swap, лимиты логов, пакеты

```bash
# swap 2G
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# чтобы journal не съел диск
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=80M\n' > /etc/systemd/journald.conf.d/size.conf
systemctl restart systemd-journald

apt update
apt install -y nginx redis-server python3 python3-venv python3-pip git certbot python3-certbot-nginx ufw
```

Redis — только localhost и потолок памяти:

```bash
printf '\nmaxmemory 64mb\nmaxmemory-policy allkeys-lru\n' >> /etc/redis/redis.conf
sed -i 's/^bind .*/bind 127.0.0.1/' /etc/redis/redis.conf
systemctl enable --now redis-server
```

Посмотреть, что жрёт диск (старый проект, логи, docker):

```bash
du -h --max-depth=2 /root /opt /var /home 2>/dev/null | sort -h | tail -30
```

Лишнее удаляете **после снапшота**. Docker, если был: `docker system prune -af`.

## 3. Пользователь и код

```bash
adduser --disabled-password --gecos '' flight
mkdir -p /opt/servicefl1ght
chown flight:flight /opt/servicefl1ght

# подставьте URL своего репозитория
sudo -u flight git clone git@github.com:YOU/ServiceFl1ght.git /opt/servicefl1ght
# или залейте архив / scp, если репо ещё нет

sudo -u flight python3 -m venv /opt/servicefl1ght/venv
sudo -u flight /opt/servicefl1ght/venv/bin/pip install -r /opt/servicefl1ght/requirements.txt
```

Секреты и данные (с ноутбука):

```bash
scp .env root@217.26.27.121:/opt/servicefl1ght/.env
scp iphone.xlsx root@217.26.27.121:/opt/servicefl1ght/iphone.xlsx
# если юзербот уже логинился локально:
scp scout2.session root@217.26.27.121:/opt/servicefl1ght/scout2.session
```

На сервере:

```bash
chown flight:flight /opt/servicefl1ght/.env
chmod 600 /opt/servicefl1ght/.env
cd /opt/servicefl1ght
sudo -u flight ./venv/bin/python core/database.py
sudo -u flight ./venv/bin/python import_excel.py
```

В `.env` на сервере: `REDIS_URL=redis://127.0.0.1:6379/0`. API слушает только `127.0.0.1:8000`, наружу его не открываем.

## 4. systemd

```bash
cp /opt/servicefl1ght/deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now servicefl1ght-api servicefl1ght-worker scout_tg
```

Проверка:

```bash
systemctl status servicefl1ght-api servicefl1ght-worker scout_tg redis-server
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/crm
```

`/crm` без пароля даст `401` — так и должно.

Юниты ограничены по RAM (`MemoryMax`). Если сервис падает с OOM — смотрите `journalctl -u ИМЯ -n 80`.

## 5. nginx и HTTPS

Домены Beget (A-запись на текущий IP сервера):

| Хост | Что отдаёт |
|---|---|
| `fl1ght.ru`, `www`, `service.fl1ght.ru` | лендинг и чат |
| `admin.fl1ght.ru` | админка скаутов (`/crm`) |
| `crm.fl1ght.ru` | карточки заказов |

`autoconfig` / `autodiscover` не вешаем на этот nginx — это почта.

```bash
cp /opt/servicefl1ght/deploy/nginx/servicefl1ght.conf /etc/nginx/sites-available/servicefl1ght
ln -sf /etc/nginx/sites-available/servicefl1ght /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

certbot --nginx --non-interactive --agree-tos --register-unsafely-without-email \
  -d fl1ght.ru -d www.fl1ght.ru \
  -d service.fl1ght.ru -d www.service.fl1ght.ru \
  -d admin.fl1ght.ru \
  -d crm.fl1ght.ru -d www.crm.fl1ght.ru
```

`www.admin.fl1ght.ru` в сертификат не включайте, пока его A-запись не смотрит на этот же VPS.

После первого `certbot` живой файл `/etc/nginx/sites-available/servicefl1ght` уже с HTTPS. Шаблон из git поверх него не копируйте — сотрёте сертификаты.

Вебхуки VK и Telegram: `https://admin.fl1ght.ru/api/vk-webhook` и `https://admin.fl1ght.ru/api/tg-webhook`. После смены секретов заново выставьте `setWebhook`.

## 6. Как обновлять код

На ноутбуке: коммит, push. На сервере:

```bash
cd /opt/servicefl1ght
sudo -u flight git pull
sudo -u flight ./venv/bin/pip install -r requirements.txt
systemctl restart servicefl1ght-api servicefl1ght-worker
# scout_tg рестартуйте только если меняли скаут, сессия Pyrogram должна остаться на диске
```

Базу и `.env` `git pull` не затирает.

## 7. Что не жать на этом железе

- «Ищейка TG» в `/crm` — на часы занимает RAM и стопает радар.
- «Ищейка VK» — перезаписывает список пабликов; лучше редкий ночной Beat (уже в celery).
- Несколько вкладок теста воронки сразу — каждый вызов YandexGPT.

Проверка после выкладки: [TESTING.md](../TESTING.md). Скаут VK: `sudo -u flight /opt/servicefl1ght/venv/bin/python /opt/servicefl1ght/run_scout_now.py` (worker должен быть `active`).

## Если что-то не встаёт

| Симптом | Что смотреть |
|---|---|
| OOM, юниты restart loop | `free -h`, swap включён? не запущен ли старый бот/docker |
| Диск 100% | `journalctl`, `*.session-journal`, старые логи в `/root` |
| API есть, скаут VK нет | `redis-cli ping`, `systemctl status servicefl1ght-worker` |
| Юзербот просит логин | нет `scout2.session` в `/opt/servicefl1ght` |
| 502 от nginx | `systemctl status servicefl1ght-api`, порт 8000 только localhost |

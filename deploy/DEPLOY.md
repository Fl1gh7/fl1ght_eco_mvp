# Как я выкладываю ServiceFl1ght

Один Debian VPS: SQLite, Redis, один uvicorn, один Celery (worker + beat), юзербот Telegram. Без Docker, Kubernetes и Postgres — на гигабайте RAM они только отъедают память, а оркестрировать здесь нечего. Второй гигабайт в панели спокойнее, но стек живёт и на одном, если включён swap.

Код — в git, прод — `/opt/servicefl1ght`, пользователь `flight`. `.env`, `database.db` и `*.session` в репозиторий не кладу.

---

## Процессы

| Процесс | systemd | Зачем | RAM примерно |
|---|---|---|---|
| nginx | `nginx` | HTTPS, статика, прокси на API | мало |
| redis-server | `redis-server` | очередь скаута VK, дедуп | лимит 64 MB |
| API | `servicefl1ght-api` | FastAPI, чат, вебхуки, `/crm` | ~150 MB |
| Celery | `servicefl1ght-worker` | обход VK + недельный finder. Beat в том же процессе | ~150 MB |
| Юзербот | `scout_tg` | слушатель групп. Имя юнита такое, потому что его стопает кнопка в админке | ~150 MB |

Swap 2 GB — запас на пик, когда API, Celery и скаут на секунду не влезают в RAM. Это файл на диске (`/swapfile`), не отдельная услуга хостера. Живая память лучше, swap всё равно оставляю.

История чата в RAM: один `--workers 1`. Два uvicorn разъедут сессии.

---

## Домены

| Хост | Что отдаю |
|---|---|
| `fl1ght.ru`, `www`, `service.fl1ght.ru` | лендинг и чат |
| `admin.fl1ght.ru` | админка скаутов (`/crm`) |
| `crm.fl1ght.ru` | карточки заказов |

`autoconfig` / `autodiscover` на этот nginx не вешаю — почта. Вебхуки: `https://admin.fl1ght.ru/api/vk-webhook` и `https://admin.fl1ght.ru/api/tg-webhook`.

Шаблон виртуальных хостов — `deploy/nginx/servicefl1ght.conf`. После certbot живой файл на сервере уже с 443; шаблон из git поверх него копировать нельзя — сотрутся сертификаты.

---

## Воспроизвести стек

Пакеты, swap, Redis только на localhost:

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=80M\n' > /etc/systemd/journald.conf.d/size.conf
systemctl restart systemd-journald

apt update
apt install -y nginx redis-server python3 python3-venv python3-pip git certbot python3-certbot-nginx ufw
printf '\nmaxmemory 64mb\nmaxmemory-policy allkeys-lru\n' >> /etc/redis/redis.conf
sed -i 's/^bind .*/bind 127.0.0.1/' /etc/redis/redis.conf
systemctl enable --now redis-server
```

Код и зависимости:

```bash
adduser --disabled-password --gecos '' flight
mkdir -p /opt/servicefl1ght
chown flight:flight /opt/servicefl1ght
sudo -u flight git clone https://github.com/Fl1gh7/fl1ght_eco_mvp.git /opt/servicefl1ght
sudo -u flight python3 -m venv /opt/servicefl1ght/venv
sudo -u flight /opt/servicefl1ght/venv/bin/pip install -r /opt/servicefl1ght/requirements.txt
```

Секреты и сессию Pyrogram копирую на сервер отдельно, `chmod 600` на `.env`. Затем схема и прайс:

```bash
cd /opt/servicefl1ght
sudo -u flight ./venv/bin/python core/database.py
sudo -u flight ./venv/bin/python import_excel.py
```

В `.env`: `REDIS_URL=redis://127.0.0.1:6379/0`. Uvicorn слушает только `127.0.0.1:8000`.

```bash
cp /opt/servicefl1ght/deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now servicefl1ght-api servicefl1ght-worker
# scout_tg — только если на диске есть scout2.session
```

`GET /crm` без пароля даёт 401 — так и задумано. Юниты ограничены `MemoryMax`.

nginx (до первого certbot):

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

---

## Обновление кода

```bash
cd /opt/servicefl1ght
sudo -u flight git pull
sudo -u flight ./venv/bin/pip install -r requirements.txt
systemctl restart servicefl1ght-api servicefl1ght-worker
```

Базу и `.env` `git pull` не затирает. `scout_tg` рестартую, только если менял скаут; файл сессии должен остаться на диске.

На этом железе не жму «Ищейку TG/VK» без нужды и не открываю пачку вкладок теста воронки — каждый вызов YandexGPT.

Проверка воронки: [TESTING.md](../TESTING.md). Ручной пинок скаута VK: `sudo -u flight /opt/servicefl1ght/venv/bin/python /opt/servicefl1ght/run_scout_now.py`.

| Симптом | Куда смотреть |
|---|---|
| OOM, restart loop | `free -h`, swap, нет ли лишнего процесса |
| Диск 100% | journald, `*.session-journal` |
| API есть, скаут VK нет | `redis-cli ping`, `servicefl1ght-worker` |
| Юзербот просит логин | нет `scout2.session` |
| 502 | `servicefl1ght-api`, порт 8000 только localhost |

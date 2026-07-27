# Deploy — @vikalashmeBot (время бота = Europe/Moscow, как на телефоне)

Если с ПК не открывается `api.telegram.org` — крути бота в облаке.  
Локально нужен SOCKS (`PROXY_URL`). На сервере `PROXY_URL` **не ставь**.

---

## Перед деплоем (чеклист)

- [ ] Один процесс polling (не два Fly machine / не два VPS)
- [ ] Postgres в проде (SQLite только локально)
- [ ] Secrets заданы, `.env` **не** копируется в образ (есть `.dockerignore`)
- [ ] Бот добавлен админом канала `@vikalashme` (если включите проверку подписки)
- [ ] `python scripts/smoke_logic.py` — зелёный
- [ ] Локально: `python scripts/audit_clock_db.py` — время = телефон (Moscow), БД чистая

### Обязательные secrets

```
BOT_TOKEN
CHANNEL_ID=@vikalashme
CHANNEL_LINK=https://t.me/vikalashme
MASTER_USERNAME=vikalashmee
MASTER_PHONE=+7 927 757-77-59
MASTER_NAME=Вика
ADMIN_TELEGRAM_IDS=683067083,588662872
PAYMENT_LINK=...
PREPAYMENT_AMOUNT=500 ₽
SLOT_HOLD_MINUTES=15
DATABASE_URL=postgresql://...   # прод
LOG_LEVEL=INFO
# PROXY_URL — НЕ задавать на Fly/VPS
```

---

## Вариант A — Fly.io (рекомендуется)

```powershell
cd c:\webprojects\sssmlkyy
fly launch --no-deploy
fly postgres create
fly postgres attach <имя-postgres-app>
fly secrets set BOT_TOKEN=... CHANNEL_ID=@vikalashme CHANNEL_LINK=https://t.me/vikalashme MASTER_USERNAME=vikalashmee MASTER_PHONE="+7 927 757-77-59" MASTER_NAME=Вика ADMIN_TELEGRAM_IDS=683067083,588662872 PAYMENT_LINK=... PREPAYMENT_AMOUNT="500 ₽" SLOT_HOLD_MINUTES=15 LOG_LEVEL=INFO
fly deploy
fly scale count 1
fly logs
```

`DATABASE_URL` вида `postgres://` бот сам перепишет в `postgresql+asyncpg://`.

---

## Вариант B — VPS (EU) + systemd

```bash
sudo apt update && sudo apt install -y python3.13-venv
cd /home/ubuntu/sssmlkyy
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполни; PROXY_URL пустой
python scripts/check_connection.py
python main.py
```

```ini
# /etc/systemd/system/vikalashme-bot.service
[Unit]
Description=Vika Lash Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/sssmlkyy
ExecStart=/home/ubuntu/sssmlkyy/venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable vikalashme-bot
sudo systemctl start vikalashme-bot
sudo systemctl status vikalashme-bot
```

Для прода на VPS тоже лучше Postgres, не SQLite-файл без бэкапа.

---

## Вариант C — Docker

```bash
docker build -t vikalashme-bot .
docker run -d --name vikalashme-bot --env-file .env --restart unless-stopped vikalashme-bot
```

На Fly/VPS в `.env` / secrets не должно быть `PROXY_URL=socks5://127.0.0.1:...`.

---

## Локально (Happ SOCKS)

```env
PROXY_URL=socks5://127.0.0.1:10808
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db
```

```powershell
python scripts\check_connection.py
python main.py
```

---

## Диагностика

| Результат check_connection | Действие |
|----------------------------|----------|
| Шаг 2 ошибка | Прокси/VPN не доходит до Python → облако |
| Шаг 2 OK, шаг 3 ошибка | Неверный `BOT_TOKEN` |
| Conflict | Уже крутится другая копия → `stop.bat` / scale 1 |
| Все OK | `python main.py` |

---

## Известные прод-ограничения

1. **FSM в MemoryStorage** — рестарт бота сбрасывает незавершённую запись (hold в БД живёт до `SLOT_HOLD_MINUTES`). Для жёсткого прода можно позже вынести FSM в Redis.
2. **Проверка подписки** сейчас не блокирует запись (код сервиса есть, гейт выключен).
3. Часовой пояс бота: **Europe/Moscow (UTC+3)** — как на телефоне мастера.

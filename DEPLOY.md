# Deploy — @vikalashmeBot (время бота = Europe/Moscow, как на телефоне)

Прод: **[Bothost](https://bothost.ru/)** (GitHub → автодеплой).  
Бот **не использует** `PROXY_URL`.

## Bothost — обязательно

По [доке Bothost](https://bothost.ru/docs/database-storage):

1. SQLite **только** в volume: `/app/data/bot.db`
2. Env в панели:
   ```
   DATABASE_URL=sqlite+aiosqlite:////app/data/bot.db
   ```
3. **Бесплатный тариф:** данные **стираются при рестарте** — для живых записей нужен Basic/Pro (persistent volume).
4. Восстановление бэкапа: останови бота → файловый менеджер → залей `bot.db` в `/app/data/` → env как выше → старт.

Локальный бэкап для заливки: `data/backups/bot.db` (копия consistent dump).

---

## Перед деплоем (чеклист)

- [ ] Один процесс polling (не локалка + Bothost одновременно на одном токене)
- [ ] `DATABASE_URL` → `/app/data/bot.db` (не относительный путь в Git-дереве)
- [ ] Платный тариф / volume, если нужны живые записи
- [ ] Secrets в панели Bothost, `.env` **не** в образе
- [ ] Бот админ канала `@vikalashme` (если включите подписку)
- [ ] `python scripts/smoke_logic.py` — зелёный

### Обязательные secrets

```
BOT_TOKEN
CHANNEL_ID=@vikalashme
CHANNEL_LINK=https://t.me/vikalashme
MASTER_USERNAME=vikalashmee
MASTER_PHONE=+7 927 757-77-59
MASTER_NAME=Вика
ADMIN_TELEGRAM_IDS=683067083,588662872,8467391228
PAYMENT_LINK=...
PREPAYMENT_AMOUNT=500 ₽
SLOT_HOLD_MINUTES=15
DATABASE_URL=postgresql://...   # прод
LOG_LEVEL=INFO
```

---

## Вариант A — Fly.io (рекомендуется)

```powershell
cd c:\webprojects\sssmlkyy
fly launch --no-deploy
fly postgres create
fly postgres attach <имя-postgres-app>
fly secrets set BOT_TOKEN=... CHANNEL_ID=@vikalashme CHANNEL_LINK=https://t.me/vikalashme MASTER_USERNAME=vikalashmee MASTER_PHONE="+7 927 757-77-59" MASTER_NAME=Вика ADMIN_TELEGRAM_IDS=683067083,588662872,8467391228 PAYMENT_LINK=... PREPAYMENT_AMOUNT="500 ₽" SLOT_HOLD_MINUTES=15 LOG_LEVEL=INFO
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
cp .env.example .env   # заполни BOT_TOKEN и остальное
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

---

## Локально

```env
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db
```

```powershell
python scripts\check_connection.py
python main.py
```

Если Telegram с ПК не открывается — системный VPN (Happ), либо сразу облако.

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

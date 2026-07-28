# Beauty Bot — Telegram-бот записи к мастеру

Запись с предоплатой, график, портфолио, FAQ, админка мастера.

## Стек

- Python 3.13+
- aiogram 3
- SQLAlchemy (async) + SQLite / Postgres
- APScheduler

## Быстрый старт

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
# Заполни .env
python main.py
```

Проверка логики: `python scripts/smoke_logic.py`

## Настройка `.env`

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен от @BotFather |
| `CHANNEL_LINK` | Ссылка на канал (кнопка в меню) |
| `MASTER_USERNAME` | Username мастера без @ |
| `MASTER_PHONE` | Телефон мастера |
| `MASTER_NAME` | Имя в текстах |
| `ADMIN_TELEGRAM_IDS` | Telegram ID админов (первый = мастер) |
| `PAYMENT_LINK` | Ссылка на предоплату |
| `DATABASE_URL` | SQLite или Postgres |

Подробности деплоя — в `DEPLOY.md` (Bothost).

## Структура

```
main.py
config/             # settings, constants
domain/             # dates, enums, parsing, slots
db/                 # models, engine
infrastructure/     # bot, DI, scheduler
services/           # schedule, booking, notify, backup, health
presentation/       # texts, keyboards, UI
handlers/           # routers
middlewares/        # logging, throttle, DI, errors
```

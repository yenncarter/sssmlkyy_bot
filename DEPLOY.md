# Deploy — Bothost

Прод: **[Bothost](https://bothost.ru/)** (Git → автодеплой).  
Бот **не использует** прокси. Локальные `.bat` / Fly.io в репозитории не нужны.

## Volume (обязательно)

По [доке Bothost](https://bothost.ru/docs/database-storage):

1. SQLite только в volume: `/app/data/bot.db`
2. В панели:
   ```
   DATABASE_URL=sqlite+aiosqlite:////app/data/bot.db
   ```
3. **Бесплатный тариф:** данные стираются при рестарте — для живых записей нужен Basic/Pro с persistent volume.
4. Восстановление: останови бота → залей `bot.db` в `/app/data/` → старт.

Ночные бэкапы бот сам шлёт мастеру в Telegram. Локальный снимок: `python scripts/backup_and_dump_sqlite.py`.

## Чеклист перед деплоем

- [ ] Один процесс polling (не локалка + Bothost на одном токене)
- [ ] Volume `/app/data` подключён
- [ ] Secrets в панели Bothost (`.env` не в образе)
- [ ] `python scripts/smoke_logic.py` — зелёный

### Обязательные переменные

```
BOT_TOKEN=
CHANNEL_LINK=https://t.me/your_channel
MASTER_USERNAME=
MASTER_PHONE=
MASTER_NAME=
ADMIN_TELEGRAM_IDS=   # первый = мастер
PAYMENT_LINK=
PREPAYMENT_AMOUNT=500 ₽
SLOT_HOLD_MINUTES=15
DATABASE_URL=sqlite+aiosqlite:////app/data/bot.db
LOG_LEVEL=INFO
```

`CHANNEL_ID` больше не нужен (проверка подписки удалена). Старую переменную в панели можно убрать.

## CI

На каждый push GitHub Actions гоняет `ruff`, `mypy` и `scripts/smoke_logic.py`. Сломанный код не должен уезжать на прод молча — смотри вкладку Actions.

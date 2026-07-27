# Beauty Bot — Telegram-витрина мастера по маникюру

Лёгкий Telegram-бот: прайс, портфолио, информация о мастере, контакты.  
Контакт для записи — **только после подписки на канал**.

## Стек

- Python 3.13+
- aiogram 3.29
- python-dotenv

## Быстрый старт

```bash
cd sssmlkyy
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
# Заполните .env
python main.py
```

## Настройка `.env`

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен от @BotFather |
| `CHANNEL_ID` | ID канала для проверки подписки |
| `CHANNEL_LINK` | Ссылка на канал |
| `MASTER_USERNAME` | Username мастера без @ |
| `MASTER_PHONE` | Телефон мастера |
| `MASTER_NAME` | Имя мастера в текстах |

## Портфолио

Добавьте фото работ в папку:

```
images/portfolio/
├── 01.jpg
├── 02.jpg
└── ...
```

Подробнее — в `images/portfolio/README.md`.

## Функционал

| Раздел | Описание |
|--------|----------|
| **Запись** | Контакт мастера — только после подписки |
| **Работы** | Фото, листание |
| **Прайс** | Полный прайс-лист |
| **О мастере** | Описание и подход |
| **Контакты** | Адрес, режим работы |

## Структура

```
main.py
config/             # settings, constants
domain/             # enums, exceptions, dates (готово к записи/оплате)
infrastructure/     # bot factory, DI container, process lock
services/           # subscription, portfolio, session, media cache
presentation/       # texts, keyboards, UI helpers
handlers/           # thin routers
middlewares/        # logging, throttle, DI, errors
```

## Важно

- Бота нужно добавить **администратором в канал**, иначе проверка подписки не работает.
- Кнопка «Написать» ведёт в личку мастера — это единственная внешняя ссылка для записи.

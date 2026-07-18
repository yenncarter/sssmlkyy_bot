# Как запустить бота, если с ПК не подключается к Telegram

Если видишь ошибку `Cannot connect to api.telegram.org` — **код бота исправен**,  
но **твой компьютер не может достучаться до API Telegram** (блокировки, провайдер, Windows).

VPN в режиме TUN часто проксирует только приложение Telegram, **но не Python**.

---

## Вариант A — облачный сервер (рекомендуется)

Бот крутится 24/7 на сервере за рубежом, где API Telegram доступен.  
С твоего ПК бот **не нужен** — только настройка один раз.

### Fly.io (простой старт)

1. Регистрация: https://fly.io  
2. Установи [flyctl](https://fly.io/docs/hands-on/install-flyctl/)  
3. В папке проекта:

```powershell
cd c:\webprojects\beauty_bot
fly launch --no-deploy
fly secrets set BOT_TOKEN=твой_токен CHANNEL_ID=@beautysznch CHANNEL_LINK=https://t.me/beautysznch MASTER_USERNAME=username MASTER_PHONE=+79... MASTER_NAME=Анна
fly deploy
```

4. Логи: `fly logs`

Бот работает на сервере Fly (Амsterdam/Frankfurt) — **локальная сеть не нужна**.

### VPS (Hetzner / Timeweb Cloud / Oracle Free)

1. Арендуй VPS (Ubuntu) **в EU** (Германия, Финляндия).  
2. Скопируй проект на сервер (git clone или scp).  
3. На сервере:

```bash
sudo apt update && sudo apt install -y python3.13-venv
cd beauty_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполни nano .env
python scripts/check_connection.py
python main.py
```

4. Для автозапуска — systemd (см. ниже).

#### systemd (VPS)

```ini
# /etc/systemd/system/beauty-bot.service
[Unit]
Description=Beauty Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/beauty_bot
ExecStart=/home/ubuntu/beauty_bot/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable beauty-bot
sudo systemctl start beauty-bot
sudo systemctl status beauty-bot
```

---

## Вариант B — локальный SOCKS5/HTTP прокси для Python

Если VPN даёт **локальный прокси** (Clash, v2rayN, Hiddify):

1. Открой настройки VPN → **HTTP port** и **SOCKS port**  
   Часто: HTTP `7890`, SOCKS `7891`

2. В `.env` попробуй **оба** варианта:

```env
# HTTP-прокси
PROXY_URL=http://127.0.0.1:7890

# или SOCKS5
PROXY_URL=socks5://127.0.0.1:7891
```

3. Установи зависимости:

```powershell
pip install -r requirements.txt
```

4. Проверка:

```powershell
python scripts\check_connection.py
```

Если `[3/3] getMe — OK` → запускай `python main.py`.

---

## Вариант C — Docker на любом сервере

```bash
docker build -t beauty-bot .
docker run -d --name beauty-bot --env-file .env --restart unless-stopped beauty-bot
```

---

## Диагностика

```powershell
python scripts\check_connection.py
```

| Результат | Что делать |
|-----------|------------|
| Шаг 2 ошибка | Прокси/VPN не доходит до Python → **облако (вариант A)** |
| Шаг 2 OK, шаг 3 ошибка | Неверный `BOT_TOKEN` |
| Все OK | `python main.py` |

---

## Почему VPN «не помогает»

| Режим | Telegram app | Python бот |
|-------|--------------|------------|
| TUN (весь трафик) | ✅ | Должен ✅, но Windows иногда ломает SSL |
| Прокси только для браузера | ✅ | ❌ |
| Локальный SOCKS без PROXY_URL в .env | ✅ | ❌ |

**Вывод:** для стабильной работы мастера лучше **облачный сервер** — один раз настроил и забыл.

FROM python:3.13-slim

# Unbuffered stdout: the hosting panel tails the container log live.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO

# Bothost bind-mounts Git sources over /app at runtime. Keep the app and
# site-packages install path outside that mount so deps are not hidden.
# Persistent data still lives on the volume at /app/data.
WORKDIR /usr/src/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import sqlalchemy, aiogram, aiosqlite, greenlet, tzdata"

COPY . .

RUN mkdir -p /app/data /app/logs \
    && useradd --create-home --uid 1000 bot \
    && chown -R bot:bot /usr/src/app /app/data /app/logs

# No secrets in the image: BOT_TOKEN and friends come from the hosting panel.
USER bot

CMD ["python", "main.py"]

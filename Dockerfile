FROM python:3.13-slim

# Unbuffered stdout: the hosting panel tails the container log live.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /app/data must be the persistent volume — SQLite lives there.
RUN mkdir -p /app/data /app/logs \
    && useradd --create-home --uid 1000 bot \
    && chown -R bot:bot /app

# No secrets in the image: BOT_TOKEN and friends come from the hosting panel.
USER bot

CMD ["python", "main.py"]

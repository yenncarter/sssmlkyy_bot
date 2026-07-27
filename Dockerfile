FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/logs

# Do not bake secrets. Pass env via Fly secrets / --env-file.
# Prefer Postgres in production (DATABASE_URL).
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

CMD ["python", "main.py"]

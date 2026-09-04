# Dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Системные зависимости (tzdata для корректной работы zoneinfo/Europe/Minsk)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения + миграции (нужны для alembic upgrade head на старте)
COPY ./app ./app
COPY ./alembic ./alembic
COPY alembic.ini .

# entrypoint: миграции → запуск uvicorn
COPY ./scripts/start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 8000

CMD ["./start.sh"]

# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей (если нужны, для asyncpg они обычно не требуются, но на всякий случай)
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

# Запуск через uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
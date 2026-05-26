FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    DATABASE_PATH=/data/db.sqlite \
    STORAGE_DIR=/data/storage \
    SAMPLES_DIR=/data/samples/inbox \
    TEST_CORPUS_DIR=/data/samples/test-corpus

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
VOLUME ["/data"]

CMD ["python", "-u", "server/app.py"]

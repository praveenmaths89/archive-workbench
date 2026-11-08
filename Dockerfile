FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-por \
        tesseract-ocr-kan \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /tmp/archive-workbench \
    && chown appuser /tmp/archive-workbench
USER appuser

ENV PUBLIC_MODE=1 \
    PORT=7860 \
    COOKIE_SECURE=1 \
    DATA_DIR=/tmp/archive-workbench \
    OCR_ENGINE=tesseract \
    PYTHONUNBUFFERED=1

EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]

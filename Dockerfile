FROM python:3.12-slim-bookworm

# Render's free instance has 512 MB. The full app needs the Python imaging
# stack; Tesseract is not installed because hosted OCR is Claude.
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /tmp/archive-workbench \
    && chown appuser /tmp/archive-workbench
USER appuser

# The Anthropic key is not baked into the image. Set it as a Render secret.
ENV HOSTED_MODE=1 \
    WORKERS=1 \
    COOKIE_SECURE=1 \
    DATA_DIR=/tmp/archive-workbench \
    PYTHONUNBUFFERED=1 \
    PORT=10000

EXPOSE 10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]

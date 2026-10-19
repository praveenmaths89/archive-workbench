FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    tesseract-ocr-kan \
    tesseract-ocr-mar \
    libglib2.0-0 \
    libgomp1 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt /srv/requirements.txt

ENV PYTHONPATH=/srv \
    HF_HOME=/opt/hf \
    HF_HUB_CACHE=/opt/hf \
    TRANSFORMERS_CACHE=/opt/hf \
    DATA_DIR=/data

# CPU torch. The default PyPI wheel pulls CUDA and makes the image several gigabytes larger.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /srv/requirements.txt \
    && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"

# RapidOCR pulls the GUI OpenCV wheel, which needs libGL. Reinstall the headless wheel
# after uninstalling both, because they share the cv2 package directory.
RUN pip uninstall -y opencv-python opencv-python-headless \
    && pip install --no-cache-dir "opencv-python-headless>=4.10"

COPY . /srv
EXPOSE 8000
CMD ["uvicorn", "archive_workbench.main:app", "--host", "0.0.0.0", "--port", "8000"]

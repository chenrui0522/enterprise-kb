# Docling parsing service for the optional "docling" docker-compose profile.
#
#   docker build -f docker/docling/Dockerfile -t docling-api .
#   docker compose --profile docling up -d docling-api
#
# Docling downloads its layout/table models from Hugging Face on first use;
# DOCLING_ARTIFACTS_PATH points the cache at a named volume so restarts stay
# fast (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DOCLING_ARTIFACTS_PATH=/opt/docling-cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# CPU image by default. For GPU, add the CUDA torch index URL and an nvidia
# runtime (see README "Docling 解析服务").
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.6,<3" \
    && pip install "docling>=2.5,<3" "fastapi>=0.115" "uvicorn[standard]>=0.30" "python-multipart>=0.0.9"

WORKDIR /srv
COPY docker/docling/app.py /srv/app.py

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
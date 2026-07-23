# Build context is the repository root, because that is what Railway uploads.
# Paths below are therefore repo-relative.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer is cached unless requirements change, so a
# code-only deploy skips the whole install.
COPY orchestration/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY orchestration/ ./

EXPOSE 8000
CMD ["sh", "-c", "uvicorn cowrie.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

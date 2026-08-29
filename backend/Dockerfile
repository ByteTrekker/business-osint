FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[etl,dev]"

COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s \
    CMD curl -fsS http://localhost:8000/api/v1/healthz || exit 1

CMD ["uvicorn", "business_osint.main:app", "--host", "0.0.0.0", "--port", "8000"]

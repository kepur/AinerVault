FROM python:3.12-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 curl ffmpeg && rm -rf /var/lib/apt/lists/*

COPY apps/ainer-core/pyproject.toml /srv/pyproject.toml
RUN pip install --no-cache-dir \
      "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.9" "pydantic-settings>=2.4" \
      "sqlalchemy>=2.0" "alembic>=1.13" "psycopg2-binary>=2.9" "httpx>=0.27" \
      "redis>=5.0" "python-multipart>=0.0.12" "pyahocorasick>=2.1"

COPY apps/ainer-core/app /srv/app
COPY apps/ainer-core/migrations /srv/migrations
COPY apps/ainer-core/alembic.ini /srv/alembic.ini

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://localhost:8100/health || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8100"]

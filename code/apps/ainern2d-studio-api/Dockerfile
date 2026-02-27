FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace

# Install shared + app dependencies once during image build.
COPY shared /workspace/shared
COPY apps/pyproject.toml /workspace/apps/pyproject.toml
COPY apps/alembic.ini /workspace/apps/alembic.ini
COPY apps/alembic /workspace/apps/alembic
COPY apps/ainern2d-studio-api /workspace/apps/ainern2d-studio-api
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e /workspace/shared \
    && pip install --no-cache-dir -e /workspace/apps

WORKDIR /workspace/apps/ainern2d-studio-api
ENV PYTHONPATH=/workspace/shared:/workspace/apps/ainern2d-studio-api

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

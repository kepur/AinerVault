FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY shared /workspace/shared
COPY apps/pyproject.toml /workspace/apps/pyproject.toml
COPY apps/ainern2d-composer /workspace/apps/ainern2d-composer
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e /workspace/shared \
    && pip install --no-cache-dir -e /workspace/apps

WORKDIR /workspace/apps/ainern2d-composer
ENV PYTHONPATH=/workspace/shared:/workspace/apps/ainern2d-composer

EXPOSE 8020

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]

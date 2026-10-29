# La versión de Python coincide con .python-version; uv.lock fija las dependencias.
FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    PATH=/app/.venv/bin:$PATH \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# ANTs y PyTorch necesitan el runtime OpenMP de GNU.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --only-group runtime --no-install-project --no-build

COPY backend/cerberus_api ./backend/cerberus_api

RUN useradd --create-home --uid 1000 cerberus \
    && mkdir -p /app/Data /app/storage /app/models \
    && chown -R cerberus:cerberus /app/Data /app/storage /app/models

USER cerberus
EXPOSE 8000
CMD ["uvicorn", "cerberus_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

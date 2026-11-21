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
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Variante de torch (HW1): `cpu` (por defecto, imagen de siempre), `cu126` (GPU NVIDIA, ver compose.gpu.yaml) o
# `cu130` (HW2: Blackwell/RTX 50xx, driver ≥ 580; tools/launch/ la elige según la compute capability).
# Las ruedas `nvidia-*` traen CUDA y cuDNN; del host solo hace falta el driver y NVIDIA Container Toolkit.
ARG TORCH_VARIANT=cpu
RUN case "$TORCH_VARIANT" in cpu|cu126|cu130) ;; *) echo "TORCH_VARIANT inválido: $TORCH_VARIANT (cpu|cu126|cu130)" >&2; exit 1;; esac

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --only-group runtime --only-group "torch-${TORCH_VARIANT}" --no-install-project --no-build

COPY backend/cerberus_api ./backend/cerberus_api
COPY tools/auth ./tools/auth
COPY docker/keycloak/realm.json ./docker/keycloak/realm.json

RUN useradd --create-home --uid 1000 cerberus \
    && mkdir -p /app/Data /app/storage /app/models \
    && chown -R cerberus:cerberus /app/Data /app/storage /app/models

USER cerberus
EXPOSE 8000
ENTRYPOINT ["python", "-m", "cerberus_api.container_setup", "exec"]
CMD ["uvicorn", "cerberus_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

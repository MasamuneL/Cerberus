# La versión de Python coincide con .python-version; uv.lock fija las dependencias.
FROM python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39

COPY --from=ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 /uv /usr/local/bin/uv

ARG CERBERUS_VERSION=dev
ARG CERBERUS_REVISION=dev
LABEL org.opencontainers.image.title="Cerberus backend" \
    org.opencontainers.image.source="https://github.com/MasamuneL/Cerberus" \
    org.opencontainers.image.version=$CERBERUS_VERSION \
    org.opencontainers.image.revision=$CERBERUS_REVISION

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

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --only-group runtime --no-install-project --no-build

COPY backend/cerberus_api ./backend/cerberus_api
COPY tools/auth ./tools/auth
COPY tools/release ./tools/release
COPY docker/keycloak/realm.json ./docker/keycloak/realm.json

RUN useradd --create-home --uid 1000 cerberus \
    && mkdir -p /app/Data /app/storage /app/models \
    && chown -R cerberus:cerberus /app/Data /app/storage /app/models

USER cerberus
EXPOSE 8000
ENTRYPOINT ["python", "-m", "cerberus_api.container_setup", "exec"]
CMD ["uvicorn", "cerberus_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

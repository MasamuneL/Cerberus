# El contexto de build es la raíz del repositorio. Nginx es nativo (arm64 o amd64); no requiere Rosetta.
FROM node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
ARG CERBERUS_VERSION=dev
ARG CERBERUS_REVISION=dev
ENV VITE_CERBERUS_VERSION=$CERBERUS_VERSION \
    VITE_CERBERUS_REVISION=$CERBERUS_REVISION
RUN npm run build

FROM nginx:1.28.3-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236

ARG CERBERUS_VERSION=dev
ARG CERBERUS_REVISION=dev
LABEL org.opencontainers.image.title="Cerberus frontend" \
    org.opencontainers.image.source="https://github.com/MasamuneL/Cerberus" \
    org.opencontainers.image.version=$CERBERUS_VERSION \
    org.opencontainers.image.revision=$CERBERUS_REVISION

# Arranque mínimo sin los scripts de entrada de la imagen (escriben en /etc/nginx): solo genera en /tmp el
# límite de cuerpo a partir de CERBERUS_MAX_UPLOAD_MB, con 64 MiB de margen para el multipart.
COPY --chmod=0555 <<'EOF' /usr/local/bin/cerberus-nginx
#!/bin/sh
set -eu
mb="${CERBERUS_MAX_UPLOAD_MB:-2048}"
case "$mb" in
    ''|*[!0-9]*) echo "CERBERUS_MAX_UPLOAD_MB debe ser un entero en MB: '$mb'" >&2; exit 1 ;;
esac
printf 'client_max_body_size %sm;\n' "$((mb + 64))" > /tmp/cerberus-upload.conf
exec nginx -g 'daemon off;' "$@"
EOF

# Un checkout de Windows puede introducir CRLF en el heredoc y convertir el intérprete en /bin/sh\r.
RUN sed -i 's/\r$//' /usr/local/bin/cerberus-nginx

COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html

ENV CERBERUS_MAX_UPLOAD_MB=2048
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

# Compatible con read_only + tmpfs /tmp: PID, temporales y el include del límite viven en /tmp.
ENTRYPOINT ["/usr/local/bin/cerberus-nginx"]

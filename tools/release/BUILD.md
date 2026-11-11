# Construcción y candidatos D3

El workflow de PR ejecuta los checks y construye backend/frontend Linux amd64 con caché BuildKit;
no autentica en el registro ni publica imágenes. El backend usa ANTs: no se declara soporte arm64 nativo.
Los Dockerfiles fijan las imágenes base por digest; uv.lock y package-lock.json fijan dependencias.
El ZIP es determinista para los mismos blobs, configuración y manifest. La construcción de imágenes
todavía usa los repositorios apt actuales: reproducibilidad aquí significa identidad por digest del
artefacto probado, no una promesa de reconstrucción bit a bit de las imágenes.

`candidate.yml` solo se ejecuta manualmente, con `authorize_publication=true`. Debe configurarse
el entorno GitHub `candidate-publication` con los revisores apropiados antes de usarlo. Su token
solo tiene `contents:read` y `packages:write`; no crea tags Git ni releases estables. Las etiquetas
`candidate-<SHA40>` identifican el commit de ambos componentes. El manifest conserva los digests
devueltos por BuildKit; una promoción posterior debe reutilizarlos sin reconstruir las imágenes.
D3h y su evidencia sobre esos mismos digests son requisito para una release estable.

En GHCR, cada paquete debe permitir lectura pública. Que el repositorio sea público no garantiza
que los paquetes lo sean. Revisar la configuración de visibilidad del paquete y los permisos de
Actions: [documentación de GitHub](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
El candidato prueba un pull de cada digest con DOCKER_CONFIG temporal vacío y verifica arquitectura,
versión y commit OCI antes de producir el ZIP. Si GHCR deniega lectura anónima, la ejecución falla;
no cambia automáticamente la visibilidad. Los permisos y credenciales globales no se modifican.

Empaquetar un checkout limpio con imágenes ya construidas:

```sh
uv run python tools/release/build.py --version candidate-<SHA40> --revision <SHA40> \
  --backend ghcr.io/masamunel/cerberus-backend@sha256:<DIGEST64> \
  --frontend ghcr.io/masamunel/cerberus-frontend@sha256:<DIGEST64> \
  --output /tmp/cerberus-candidate.zip
```

El comando solo lee blobs versionados de la lista permitida y genera Compose desde el contrato común.
Los ficheros locales sin commit, enlaces simbólicos, Data/, modelos, resultados, archivos de entorno
y credenciales no forman parte del paquete. SHA256SUMS valida su contenido y la salida del comando
contiene el hash del ZIP. Los recursos de tema incluyen la licencia SIL OFL de IBM Plex.

Las acciones se fijaron a los SHA de sus tags oficiales, consultados mediante `git ls-remote` el
2026-11-11: actions/checkout v6, setup-node v6, upload-artifact v4; docker/setup-buildx-action v3,
build-push-action v6; astral-sh/setup-uv v7 (commit resuelto del tag anotado).
Fuentes: repositorios oficiales de [GitHub Actions](https://github.com/actions),
[Docker](https://github.com/docker) y [Astral](https://github.com/astral-sh/setup-uv).

Pendiente de evidencia externa: primera publicación autorizada, descarga anónima desde equipo limpio,
QA D3h, tamaño transferido, disco máximo, RAM y tiempos fríos/calientes hasta login y visor. No se
han publicado imágenes ni ejecutado estos workflows durante la implementación. Registrar condiciones
de medición (sistema, CPU, RAM, Docker, red y cachés); los tiempos del build de CI no equivalen a los
tiempos de instalación de un usuario. Ninguna plataforma de escritorio se declara validada por este CI.

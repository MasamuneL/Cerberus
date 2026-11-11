# Verificación de UX/UI (§14)

Requiere Chrome instalado, la API y el servidor Vite de desarrollo en ejecución, y los estudios reales
001/t0 y 005/t0 con segmentación y mapa de áreas. El catálogo de referencia tiene ocho estudios.

```bash
cd tools/e2e
npm ci
CERBERUS_UI=http://localhost:5180 npm run verify
```

La URL predeterminada es `http://localhost:5173`. `CERBERUS_TIMEOUT` permite cambiar el límite de espera de
carga de volúmenes (180000 ms por defecto). No ejecutes varias instancias simultáneamente: SwiftShader usa
bastante CPU y memoria durante la carga de Niivue.

La verificación cubre 1440×900 y 1280×800, pestañas y filas con teclado, capas y lectura del cursor,
volumetría, segmentación, evolución, funciones en riesgo y límites 5/10 mm, paleta fría, aviso de
anonimización y axe con reglas WCAG 2.1 AA. Los escenarios de jobs usan `page.route`: ningún POST llega a
la API real. Las mutaciones no previstas se bloquean y hacen fallar la ejecución. No requiere Redis ni
worker para los jobs simulados; no ejecuta MONAI, ANTs ni subidas.

Las capturas y `shots/report.json` quedan ignorados por Git. Cualquier aserción fallida produce código de
salida 1; el navegador se cierra mediante `finally`. Los 404 solo son esperados para endpoints de
resultados ausentes; otros fallos HTTP, errores JavaScript y errores de consola hacen fallar la prueba.

Revisa las PNG manualmente, especialmente la imagen coronal, los ajustes abiertos y los dos tamaños de
ventana. No hay línea base visual previa: las capturas no prueban por sí solas ausencia de regresiones.
El script no lee píxeles con `drawImage(canvas)`: WebGL usa `preserveDrawingBuffer=false`. Comprueba carga
real y estado de volúmenes y conserva las capturas del compositor para revisión humana. Axe complementa
las pruebas de teclado; sus hallazgos incompletos quedan en el reporte y requieren revisión humana.

La regresión del fondo del atlas también puede repetirse aisladamente con
`CERBERUS_UI=http://localhost:5180 node verify-background.mjs`. Este comando verifica las entradas
transparentes del LUT, el fondo cero, etiquetas visibles y el nombre del área enfocada. Guarda capturas
de los modos «Todas» y «Solo afectadas», además de `shots/background-report.json`. La suite principal
incluye las mismas comprobaciones del LUT y verifica la opacidad final tras cambiarla durante una
descarga interceptada. Las interacciones extendidas del visor y los jobs se ejecutan en 1440×900;
ambos tamaños cubren pestañas, tablas, datos reales, estudio distinto, aviso de subida y axe.

## Smoke de Docker y frontend de producción

Con Docker Compose levantado y la muestra `Data/001` descargada mediante Git LFS:

El Compose predeterminado incluye login. Para este smoke, proporciona un archivo `storageState` de
Playwright obtenido mediante login real de un analista, usando `CERBERUS_QA_STORAGE_STATE=/ruta/estado.json`.
Se aplica también al contexto de caché. El archivo contiene cookies de sesión: mantenlo fuera del repositorio
con permisos 0600 y elimina la sesión/archivo al terminar. El runner no desactiva autenticación ni permisos.

```bash
cd tools/e2e
npm ci
CERBERUS_UI=http://localhost:8080 node verify-docker.mjs
```

El puerto predeterminado es `8080`; `CERBERUS_TIMEOUT` conserva el límite de 180000 ms para Niivue.
Se usa Chrome headless con SwiftShader. Ejecuta un solo navegador de QA a la vez.

Este runner funciona con los archivos compilados servidos por Nginx: no importa módulos de `/src` ni
consulta el objeto privado de Niivue. Comprueba HTML compilado, fallback SPA, proxy `/api`, salud,
catálogo dinámico, volumetría de 001/t0 (33.14 ± 0.01 cm³), cabeceras y descargas NIfTI completas,
canvas visible, carga terminada y lectura del cursor con intensidades y estado del GTV. También prueba
pestañas por teclado, atajos, opacidad, ocultar/mostrar el GTV y el formulario de subida sin enviarlo.
También comprueba el indicador de recursos (§16: texto con «hilos» o «GPU» en Segmentación y Áreas) y
que al volver a 001/t0 los NIfTI se revaliden con 304. Ambas quedan «pendiente» en `report.pending`, sin
fallar, mientras `/api/system` responda 404 o los NIfTI no lleven ETag con `Cache-Control: no-cache`; con
esas cabeceras, ninguna respuesta 304 hace fallar el smoke.
Solo requiere la muestra 001/t0: no exige ocho estudios ni resultados previos de MONAI o ANTs.

Guarda `shots/docker/report.json` y capturas a 1440×900 y 1280×800, ignorados por Git. Las aserciones
fallidas producen exit 1 y el navegador se cierra en `finally`. Cualquier mutación solicitada se bloquea
y hace fallar el smoke; los únicos 404 permitidos corresponden a resultados ausentes según el catálogo.
Revisa las capturas manualmente: el smoke no certifica accesibilidad ni sustituye `verify.mjs`.

Las cancelaciones NIfTI por recarga de capas quedan registradas en `report.cancelledNifti`.
Solo se aceptan si una descarga posterior del mismo volumen termina correctamente; una cancelación
sin reemplazo completo o cualquier otro fallo HTTP o de descarga hace fallar el smoke.

### Solo la imagen del frontend contra la API de desarrollo

Nginx resuelve `api` en cada petición con el DNS de Docker (`127.0.0.11`), así sobrevive a que Compose
recree la API. Por eso `--add-host` no basta: hace falta una red de usuario y un relé con alias `api` hacia
la API del host (`uvicorn` en `:8000`):

```bash
docker build -f docker/frontend.Dockerfile -t cerberus-frontend:local .
docker network create cerberus-fe-test
printf 'pid /tmp/nginx.pid;\nevents {}\nstream { server { listen 8000; proxy_pass host.docker.internal:8000; } }\n' > /tmp/relay.conf
docker run -d --name cerberus-fe-relay --network cerberus-fe-test --network-alias api \
  -v /tmp/relay.conf:/etc/nginx/nginx.conf:ro nginx:1.28.3-alpine nginx -g 'daemon off;'
docker run -d --name cerberus-fe-test --network cerberus-fe-test --read-only --tmpfs /tmp --cap-drop ALL \
  -p 127.0.0.1:8081:8080 cerberus-frontend:local
(cd tools/e2e && CERBERUS_UI=http://localhost:8081 node verify-docker.mjs)
docker rm -f cerberus-fe-test cerberus-fe-relay && docker network rm cerberus-fe-test
```

`docker exec <contenedor> nginx -T` muestra `client_max_body_size`: se genera al arrancar como
`CERBERUS_MAX_UPLOAD_MB` + 64 MiB (2112m por defecto) para el margen del multipart; la API aplica el
límite exacto.

### Estados de autenticación (A4)

Desde `tools/e2e`, `npm run test:auth` ejecuta regresiones sin navegador del visor, cancelación, cliente HTTP,
CSRF y referencias opacas de continuidad. `npm run verify:auth-ui` prueba estados con HTTP controlado contra
Vite (`CERBERUS_UI=http://localhost:5173`): anónimo/roles, 401 de JSON/NIfTI, aborto, logout/reintentos,
expiración y coordinación entre pestañas. Solo un Chrome/SwiftShader de QA a la vez.

Estas pruebas de UI no validan Keycloak ni sustituyen el QA real con cuentas temporales. Los reportes y
capturas se guardan bajo `shots/auth-ui/` y `shots/auth-session-ui/`, ignorados por Git. La entrega requiere
además `verify.mjs`, smoke Docker y el flujo real con el proveedor, revisando capturas y fechas actuales.


## Vista 3D y superficie GTV (F12)

`npm run test:viewer` ejecuta sin navegador las regresiones geométricas y de ciclo de vida del visor:
focos GTV pequeños aislados/junto a componentes mayores, affine, malla cerrada, restauración 2D y
cancelación de la máscara cerebral al recargar secuencia, capas o estudio.

Con API y Vite activos, `CERBERUS_UI=http://localhost:5186 npm run verify:3d` usa Chrome con los volúmenes
reales de 001/t0. Comprueba superficie, modulación cerebral, controles/corte/cámara, visibilidad GTV,
cambio de secuencia, vuelta a 2D y axe del panel nuevo a 1440×900 y 1280×800. Guarda capturas y reporte
en `shots/viewer-3d/`; revisarlas manualmente. Ejecutar después de `verify.mjs`, nunca en paralelo con
otro Chrome/SwiftShader. No hace subidas ni ejecuta trabajos/modelos. Requiere API local en modo off,
igual que la suite Vite principal; las regresiones auth se ejecutan por separado.

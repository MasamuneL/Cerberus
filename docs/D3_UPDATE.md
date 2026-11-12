# Actualizar, conservar y recuperar Cerberus

Esta guía corresponde al paquete de distribución con `release.json`, imágenes por digest y
`state_format: 1`. No actualiza instalaciones anteriores sin ese contrato. Una carpeta del repositorio
con imágenes `:local` no es un paquete de distribución. Conserva la instalación en una carpeta permanente.

## Actualizar a una versión explícita

Descarga el ZIP de la versión elegida desde la release del proyecto y verifica su SHA-256 publicado.
Extrae el candidato en **otra carpeta vacía**, nunca encima de la instalación. Desde la instalación actual:

```bash
# macOS o Linux: la ruta debe designar la carpeta extraída, no el ZIP.
bash tools/setup/update.sh '/ruta/al/candidato'
```

```powershell
# Windows PowerShell 5.1 o PowerShell 7.
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup\update.ps1 -Candidate 'C:\Cerberus-candidato'
```

El backend **actual** comprueba primero los checksums, los digests y la compatibilidad del paquete;
consulta Redis y pospone si hay trabajos en cola o en ejecución. Descarga las imágenes sin detener la
instalación y verifica sus etiquetas OCI de versión, revisión y plataforma Linux amd64. No ejecuta
scripts ni código del candidato durante esas comprobaciones. Un SHA-256 comprueba integridad; la
procedencia se establece descargando el paquete y su checksum desde la release confiable.

Después detiene frontend, API y worker, vuelve a comprobar Redis para detectar trabajos que entraron
mientras descargaba y detiene Keycloak. Genera `pg_dump -Fc`, fuerza `Redis SAVE` y detiene PostgreSQL y
Redis antes de copiar sus archivos. Si no hay espacio suficiente para el backup, no cambia el paquete.
Solo entonces conserva el paquete anterior, instala los archivos públicos del candidato e inicia con
imágenes ya descargadas, sin build ni descarga implícita. Antes de cualquier cambio rechaza contextos Docker remotos y contenedores del mismo proyecto
que pertenezcan a otra carpeta, incluidos los detenidos. `DOCKER_CONTEXT` prevalece sobre `DOCKER_HOST`.
La operación usa `.cerberus-setup.lock`,
compartido con el lanzador de inicio; no ejecutes Compose directamente mientras esté trabajando.

Se conservan `.env`, `.env.auth` si existe, Data, storage, modelos, cuentas, contraseñas, roles,
usuarios deshabilitados y acciones requeridas. El actualizador no cambia automáticamente contraseñas.
No acepta cambios en configuración o imagen de PostgreSQL, Keycloak o Redis, nombre del proyecto,
definiciones de volúmenes ni montajes persistentes. Un cambio de formato de estado requiere una
migración y restauración validadas por separado; volver de imagen no revierte una migración de datos.

## Backup privado

Para generar un backup sin cambiar la versión:

```bash
bash tools/setup/update.sh --backup
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup\update.ps1 -Backup
```

Cada ejecución crea `.cerberus-backups/<fecha UTC>-<pid>/` con:

- `database.dump`: exportación lógica consistente de PostgreSQL.
- `state.tar`: Data, resultados y demás storage persistente, modelos, paquete/configuración y los seis
  volúmenes fríos: `redis-data`, `auth-db-data`, `keycloak-data`, `auth-db-secret`,
  `keycloak-admin-secret` y `oidc-client-secret`.
- `backup.json`: revisión, formato, digests del archivo y dump y nombres de volúmenes.
- `helper-image.txt`: digest del backend actual que sabe verificar y recuperar ese backup.

**Contiene datos propios, sesiones y secretos: es privado y nunca se adjunta al diagnóstico ni a Git.**
La carpeta queda con permisos 0700 y los archivos privados con 0600 en sistemas POSIX; Windows limita
la ACL al usuario actual. El tar conserva propietarios y permisos internos necesarios para PostgreSQL.
No incluye `storage/tmp/`, carpetas `logs/` ni archivos `.log`; no sigue enlaces ni copia dispositivos.
Guarda copia del backup en almacenamiento privado y conserva disponible la imagen helper por digest.
Sin esa imagen local, la restauración se detiene; no intenta descargar ni ejecutar otra versión.

El backup completo puede ocupar tanto espacio como los datos y los modelos; no hay borrado automático.
Un backup incompleto tras un fallo no sirve para restaurar: exige los cuatro archivos y hashes válidos.
No borres el backup anterior hasta validar el nuevo con una restauración aislada.

## Fallos y retorno explícito

Un fallo de descarga o verificación inicial conserva la instalación en ejecución. Si falla antes de
activar el candidato, el script intenta iniciar el paquete anterior con sus imágenes locales. Si falla
la activación o el arranque posterior, detiene frontend, API y worker, conserva datos y backup, y deja
la recuperación explícita al operador. No alterna imágenes automáticamente contra datos desconocidos.
Los errores públicos no imprimen secretos, dumps ni configuración privada.

Para volver a un paquete compatible retenido en `.cerberus-versions/<SHA completo>/`:

```bash
bash tools/setup/update.sh --rollback <SHA-de-40-caracteres>
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup\update.ps1 -Rollback '<SHA-de-40-caracteres>'
```

El retorno repite todas las guardas y crea otro backup. Requiere PostgreSQL/Keycloak/Redis disponibles
para comprobar cola y exportar el estado. Si no pueden iniciar, o el estado exige una migración,
recupera el backup en un proyecto nuevo; no cambies imágenes de la base de datos para forzarlo.
Al cancelar, PowerShell libera su lock y no informa éxito; el motor `pwsh -File` puede devolver código
0 con Ctrl+C. Comprueba el mensaje y el estado de los servicios, no solo ese código.
Si una interrupción deja `.cerberus-setup.lock`, comprueba que no siga ejecutándose ningún lanzador o
actualizador antes de retirar manualmente ese directorio. No quites el lock de una operación activa.

## Restauración aislada, sin sobrescribir

Usa una carpeta destino vacía y un proyecto nuevo cuyo nombre empiece por `cerberus-restore-` o
`cerberus-qa-`. No se acepta ningún volumen preexistente con los nombres de ese proyecto.

```bash
bash tools/setup/update.sh --restore \
  '/ruta/instalacion/.cerberus-backups/<backup>' \
  '/ruta/Cerberus-restaurado' cerberus-restore-prueba
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup\update.ps1 `
  -Restore 'C:\Cerberus\.cerberus-backups\<backup>' `
  -Destination 'C:\Cerberus-restaurado' -Project cerberus-restore-prueba
```

La imagen helper verifica el backup antes de copiar, crea seis volúmenes nuevos y restaura únicamente
destinos vacíos. Mantiene el paquete y credenciales respaldados; reescribe solo el nombre del proyecto
y las rutas Data/storage/models para que apunten a la nueva carpeta. Conserva `.env.auth` cuando existe.
**No inicia servicios automáticamente.** Si la copia falla a medias, conserva el backup; repite con
otra carpeta vacía y otro proyecto nuevo, sin reutilizar destinos parcialmente restaurados.

Antes de iniciar la copia recuperada, asigna puertos libres en su `.env`:

```dotenv
CERBERUS_HTTP_PORT=18080
CERBERUS_KEYCLOAK_HTTP_PORT=18081
```

Si `.env` tiene `CERBERUS_APP_ORIGIN` explícito, ajústalo a `http://localhost:18080`.
Ejecuta el lanzador desde la nueva carpeta. Verifica salud, login con la contraseña modificada,
rol reader, usuario deshabilitado, acciones requeridas, resultados y modelos. Un restore físico de
PostgreSQL requiere la **misma imagen por digest** que lo creó; `database.dump` queda disponible para
un procedimiento lógico separado con `pg_restore` si se planifica una migración. Este script no hace
upgrades ni importa el dump contra otra versión de PostgreSQL.

Detener sin borrar: `docker compose stop`. Reiniciar conservando datos: usar `start.sh`, `start.command`
o `start.ps1`. Ningún procedimiento de esta guía necesita `down -v`, prune, reset ni regenerar secretos.

## Evidencia y límites de validación

Las pruebas rápidas cubren integridad de paquetes y backups, preservación/restauración en disco,
rechazo de mezclas e identidad incompatible, copia fallida y flujo completo Bash/PowerShell con Docker
simulado. No necesitan red ni tocan la instalación habitual. PowerShell se ejecuta cuando se indica
`CERBERUS_TEST_PWSH` o está instalado `pwsh`.

La aprobación final D3h requiere ejercicios Docker reales aislados: actualización, fallo posterior y
restauración con cuentas modificadas/reader/deshabilitadas/acciones requeridas; también Windows 5.1,
ACL NTFS y Docker Desktop nativos. Las pruebas simuladas no sustituyen esa validación ni prometen
compatibilidad ya comprobada en todos los sistemas. La publicación GHCR y la release requieren la
aprobación explícita del usuario.

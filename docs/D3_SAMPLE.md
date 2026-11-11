# Muestra pública de la distribución D3

## Procedencia y permiso

Revisión: 2026-11-11. La fuente primaria es la [colección CFB-GBM de TCIA](https://www.cancerimagingarchive.net/collection/cfb-gbm/), DOI [10.7937/v9pn-2f72](https://doi.org/10.7937/v9pn-2f72). Su tabla de acceso asigna **CC BY 4.0** a los NIfTI públicos y exige citar el dataset. La [licencia](https://creativecommons.org/licenses/by/4.0/) permite redistribuir con atribución, enlace a la licencia e indicación de cambios, sin sugerir respaldo de los autores. La [política de TCIA](https://www.cancerimagingarchive.net/data-usage-policies-and-restrictions/) exige conservar la cita completa y el DOI; también impide intentar identificar o contactar participantes. Consulte además las condiciones de [Data Analysis Centers](https://wiki.cancerimagingarchive.net/pages/viewpage.action?pageId=22515655) aplicables a herramientas y espejos de TCIA. Al usar o redistribuir estos datos debe conservar la cita, DOI, licencia y enlace a la política TCIA, y exigir lo mismo a usuarios posteriores. Esta muestra es para exploración y docencia, sin validación clínica.

**Decisión:** se puede preparar un artefacto de los NIfTI públicos de `001/t0`, conservando esos avisos en el manifest y en esta guía, ambos incluidos en la release. No se distribuyen DICOM, información clínica, otros pacientes ni resultados privados. La selección contiene T1Gd, FLAIR, máscara cerebral y GTV; esta última excluye edema. Los cuatro archivos conservan exactamente sus bytes, nombres y compresión originales; se omiten las demás modalidades. No constituye una nueva versión científica del dataset.

TCIA actualmente cita la colección como versión 4; no se ha demostrado la versión upstream de cada archivo heredado del repositorio. Por ello el manifest no la inventa: fija una versión propia del subconjunto y sus huellas, contrastadas con los objetos LFS previamente registrados. La selección local no demuestra por sí sola equivalencia de numeración con todas las revisiones de TCIA.

Cita bibliográfica de la colección (versión 4 de la ficha consultada):

Moreau, N., Leclercq, A., Desmonts, A., Poirier, Y., Dubru, A., Guillemette, L., Lecoeur, P., Lemasson, K., Jaudet, C., Brunaud, C., Valable, S., Geffrelot, J., Stefan, D., Leleu, T., Raboutet, C., Le Henaff, L., Batalla, A., Lacroix, J., Rouzier, R., & Corroyer-Dulmont, A. (2025). *Pre and post treatment MRI and radiotherapy plans of patients with glioblastoma: the CFB-GBM cohort (CFB-GBM)* (Version 4) [dataset]. The Cancer Imaging Archive. https://doi.org/10.7937/v9pn-2f72

## Artefacto y contrato

`tools/release/sample-manifest.json` declara `format=1`, `version`, `archive={url,size,sha256}`, `files=[{path,size,sha256}]` y `source` con procedencia, atribución y licencia. El lector exige exactamente los cuatro NIfTI conocidos de `001/t0`. `archive.size` cuenta bytes del TAR USTAR **sin compresión adicional**; cada NIfTI ya está comprimido. El TAR excluye directorios auxiliares, enlaces, PAX, archivos privados y metadatos del equipo. La release de aplicación debe incluir este manifest y esta guía para conservar la atribución.

Versión: `cfb-gbm-001-t0-v1`. Artefacto: `cerberus-sample-cfb-gbm-001-t0-v1.tar`, **144,302,080 bytes**, SHA-256 `1d814107ba6858d4eabbb70d43ff09387349efc701cb1d29d9f8d2ddcdf4012f`. Los NIfTI suman 144,291,911 bytes; preparar la muestra requiere aproximadamente 306 MB libres incluyendo descarga, extracción y margen. El tamaño se comprueba en el filesystem de `Data`, no en el host del usuario.

**Publicación pendiente:** la URL versionada de GitHub Releases en el manifest es el destino previsto, no evidencia de disponibilidad. Este cambio no publica archivos. No debe promoverse una release instalable hasta subir exactamente ese artefacto, conservar la atribución y comprobar descarga anónima y SHA-256 desde un entorno limpio. El workflow de distribución tiene que proporcionar los NIfTI reales mediante LFS en el entorno de construcción o una fuente oficial autorizada; el usuario final no necesita Git ni Git LFS. Si los archivos fijados ya no pueden recuperarse, se bloquea esa publicación; cambiar de subconjunto exige una versión y huellas nuevas con revisión de procedencia.

Reconstrucción por un mantenedor con los cuatro archivos públicos ya disponibles:

```bash
uv run python tools/release/sample-build.py \
  --data /ruta/publica/Data \
  --output /ruta/nueva/cerberus-sample-cfb-gbm-001-t0-v1.tar
```

El script compara las fuentes con el manifest antes de incluirlas; falla ante punteros LFS o bytes distintos. No incluye archivos adicionales aunque existan en `Data`. El TAR ordena las entradas y fija UID, GID, permisos y fechas; dos construcciones con los mismos bytes producen la misma huella. El destino debe ser nuevo. `--url` permite fijar un alojamiento HTTPS de release diferente antes de empaquetar la aplicación; no realiza conexiones ni publicación. No se incluyen los 144 MB en cada imagen backend/frontend.

## Inicializador

Dentro del contenedor backend Linux:

```bash
python -m cerberus_api.sample \
  --manifest /app/tools/release/sample-manifest.json \
  --data /app/Data
```

Compose ejecuta este servicio después de preparar propiedad/permisos de las raíces y antes de iniciar API/worker y escanear el catálogo. Usa el mismo usuario de la aplicación. `CERBERUS_SAMPLE_MODE=auto` es el valor predeterminado; `CERBERUS_SAMPLE_MODE=none` omite explícitamente la muestra y permite usar datos propios. Este modo no lee el manifest ni crea directorios ni consulta la red.

Si ya existen los cuatro archivos válidos, el inicializador comprueba tamaños, SHA-256 y cabeceras NIfTI; termina sin consultar red ni modificar esos archivos. Una muestra incompleta se completa conservando los archivos correctos. Un archivo existente distinto, corrupto o LFS bloquea el inicio con un mensaje accionable: el usuario puede conservarlo y elegir `none`, o revisar su copia fuera de Cerberus. Nunca se reemplaza automáticamente.

La descarga usa HTTPS con timeout por operación y tamaño acotado; las redirecciones también exigen HTTPS. Primero se verifica el TAR completo y luego todos sus archivos dentro de un temporal privado en el mismo filesystem. Solo después se publican mediante enlaces exclusivos que no reemplazan destinos existentes. Un bloqueo evita dos inicializadores simultáneos; una segunda validación detecta conflictos aparecidos durante la descarga. Se rechazan traversal, symlinks en los directorios y archivos, archivos especiales, enlaces TAR, duplicados, entradas ausentes y tamaños distintos.

Un fallo de red, corrupción, falta de espacio, excepción o cancelación atendida retira el temporal y conserva los datos existentes. Si se interrumpe durante la publicación, pueden quedar archivos completos válidos: repetir completa la muestra. Un apagado abrupto o SIGKILL puede dejar un temporal oculto `.cerberus-sample-*`; nunca se interpreta como estudio ni se borra automáticamente una carpeta desconocida. El usuario puede revisarlo cuando ningún inicializador esté activo. No se ofrece borrado automático de datos para reparar.

Los tests son sin red y verifican apertura de `001/t0` y GTV en el catálogo con NIfTI sintéticos, idempotencia, corrupción, truncamiento, conflicto, LFS, espacio, enlaces, traversal, carreras e interrupción. El inicio real mediante Docker y descarga anónima del artefacto publicado pertenecen a D3h; esta guía no declara esas verificaciones completadas.

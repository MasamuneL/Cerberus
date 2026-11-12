# D3 — Instalación y distribución sencilla de Cerberus

Estado: implementación en curso en `feat/D3-simple-setup`; evidencia y bloqueos en [QA D3](../../qa/D3_EXECUTION.md).
Fecha: 2026-11-11. Base: `main`, CP-051 (`393e202`).
Rama de trabajo e integración: `feat/D3-simple-setup`.
Responsable de ejecución: **Sol**, con subagentes por tarea cuando aporten independencia o revisión.

## 1. Resultado esperado

Una persona que quiera probar Cerberus instala Docker, descarga y descomprime una release y ejecuta
el lanzador correspondiente a su sistema. El lanzador comprueba requisitos, descarga imágenes y muestra
la URL correcta cuando la aplicación está lista. La cuenta local `demo` / `demo` y la muestra permiten
abrir el visor sin instalar Python, uv, Node, Git ni Git LFS en el host.

Compose sigue siendo una entrada soportada por sí misma: desde el paquete distribuido,
`docker compose up -d --wait` debe levantar la aplicación con configuración predeterminada si los puertos
están libres. El lanzador añade diagnóstico, elección de puertos y apertura del navegador; no concentra
lógica imprescindible de identidad o preparación de datos que falte en Compose.

Actualizar es una acción explícita, con versión identificable y conservación de cuentas, secretos,
muestras propias, trabajos y resultados. No se actualiza al iniciar ni se borra información para reparar.

## 2. Base existente y límites

A1c ya inicia OIDC y crea/adopta secretos automáticamente; sincroniza callback, conserva usuarios y crea
la cuenta demo si falta. Se reutiliza esa implementación. Los dos inicializadores con salida 0 son normales.
El backend necesita Linux amd64 por ANTs; no prometer soporte arm64 nativo sin resolver esa dependencia.
MONAI y atlas ya se descargan al usarse y se guardan en caché. No repetir ese desarrollo.

El problema del profesor incluye un servicio ajeno (`openshell-gatew`) en 8080. También hay que comprobar
8081, utilizado por Keycloak. Cambiar solo la URL del frontend no resuelve toda la configuración OIDC.
El Compose actual monta realm y tema desde `docker/keycloak/`: distribuir únicamente su YAML no basta.
La muestra `Data/001` usa LFS (~770 MB según README); validar tamaño real, procedencia y condiciones antes
de distribuir una copia. No distribuir DICOM crudo, otros pacientes ni datos locales del desarrollador.

Alcance: demo local en loopback y facilidad de instalación. No incluye despliegue hospitalario, exposición
pública, TLS remoto, entrenamiento, cambios científicos, instalador de Docker ni reemplazo de Keycloak.
A5 y la ola P siguen pendientes; las pruebas de instalación no los cierran automáticamente.

## 3. Decisiones de implementación

- Conservar `compose.yaml` del repositorio como flujo de desarrollo compatible con `--build` y `.env.auth`.
  Añadir definición de distribución sin `build`, empaquetada como `compose.yaml` en la release.
  Generar ambos desde partes compartidas o validar automáticamente su equivalencia operativa; evitar
  dos stacks mantenidos a mano que diverjan. Elegir el mecanismo en D3a según la versión mínima de Compose.
- El paquete incluye todos los recursos necesarios: YAML, lanzadores, instrucciones, manifest de versión,
  checksums y realm/tema o imagen de identidad que los contenga. Sin referencias al checkout del autor.
- Publicar imágenes versionadas en GHCR; la release fija digests compatibles entre backend, frontend y
  recursos de identidad. No usar `latest` como contrato de actualización. El backend de API, worker e
  inicializadores procede del mismo artefacto. Verificar descarga anónima desde una máquina limpia.
- Mantener nombres/identidad del proyecto y volúmenes al migrar una instalación existente. Elegir una
  carpeta persistente de instalación; extraer una release en otra carpeta no debe perder los bind mounts.
- Lanzadores pequeños: PowerShell para Windows y shell para macOS/Linux, sin Python/Node en el host.
  Reutilizar comprobaciones complejas mediante herramientas dentro de contenedores. Sin `sudo`, cambios
  globales de políticas de PowerShell ni instalación silenciosa de dependencias.
- Configuración local pública y persistente para puertos/rutas; no guardar secretos nuevos en ese archivo.
  Respetar variables explícitas y configuración existente; no ejecutar `.env` como script de shell.
- Preferir los puertos configurados. Si son predeterminados y están ocupados, buscar dos libres y persistirlos.
  Si el usuario fijó un puerto ocupado, informar y detenerse. No matar procesos ni alterar servicios ajenos.
  Reintento limitado ante carreras de reserva; no modificar el origen de una instancia activa inesperadamente.
- El diagnóstico exportado se construye con lista permitida de campos. No empaquetar logs sin filtrar,
  `.env*`, tokens, cookies, URLs con query, rutas personales, nombres de pacientes ni variables completas.

## 4. Tickets, dependencias y aceptación

### D3a — Contrato del paquete y compatibilidad

Dependencias: A1c integrado. Archivos: `compose.yaml`, nueva definición de distribución,
`tools/release/`, documentación y pruebas de configuración.

1. Definir layout del paquete, versión, digests, recursos incluidos y ubicación persistente de datos.
2. Determinar versión mínima real de Compose y matriz Windows/Docker Desktop, macOS Intel/Apple Silicon,
   Linux Docker Engine + plugin. Distinguir soporte comprobado de esperado.
3. Establecer migración desde el checkout actual: mismos volúmenes, rutas absolutas resueltas y secretos;
   detectar instalación existente antes de crear otra identidad de proyecto.
4. Resolver propiedad de directorios vacíos, UID/GID y primera escritura del worker. No aplicar chown
   recursivo a datos existentes; garantizar orden de preparación antes de que el worker escriba.

Aceptación: configuración de distribución sin build ni rutas ausentes; configuración sin secretos previos;
comparación de servicios/redes/auth con el stack actual; pruebas de rutas con espacios y de conservación.
Entregable: contrato pequeño que desbloquea los demás tickets, incorporado al plan antes de paralelizar.

### D3b — Imágenes y release reproducible

Depende de D3a. Archivos: Dockerfiles, `.dockerignore`, `.github/workflows/`, `tools/release/`.

1. Construir backend amd64 y frontend en plataformas realmente verificadas, con caché de build.
2. Etiquetar versión y revisión OCI; registrar digests en manifest. Incluir realm/tema y licencias necesarias.
3. Añadir CI para PR sin publicación y workflow de release con permisos mínimos; fijar acciones por SHA.
   Publicar candidatos identificados por commit; promover exactamente los digests probados tras D3h.
4. Generar ZIP con checksums; verificar contenido por lista permitida y ausencia de credenciales/datos ajenos.
5. Documentar visibilidad GHCR, permisos y tamaño/tiempo medidos; no asumir que un repositorio público
   implica que el paquete GHCR ya puede descargarse sin autenticación.

Aceptación: download anónimo, `up` sin compilación ni checkout, mismo commit en todos los componentes;
no publicar una release estable si falla QA. Fallos del registro no modifican la versión que estaba activa.

### D3c — Muestra automática, íntegra y repetible

Depende de D3a; D3b para publicación final. Archivos: manifest de muestra, inicializador de datos,
Compose y tests backend.

1. Verificar condiciones de distribución y citación de CFB-GBM en fuente primaria; registrar URL y decisión.
   Si no permiten el mecanismo propuesto, bloquear esa publicación y documentar la alternativa autorizada.
2. Preparar artefacto versionado con solo los NIfTI públicos necesarios de 001, sin depender de LFS del host.
   Preferir descarga de artefacto verificado para no inflar cada imagen de aplicación.
3. Declarar tamaños, SHA-256 por archivo y versión; detectar punteros LFS, corrupción, falta de espacio,
   interrupción y rutas de extracción inseguras. Descargar a temporal y publicar solo tras validar.
4. Preparar muestra antes del catálogo; repetir no descarga ni modifica archivos válidos. Datos existentes
   distintos nunca se sobrescriben: error accionable o modo explícito sin muestra para datos propios.
5. La primera instalación necesita red; si todo está presente, reiniciar no consulta la red obligatoriamente.

Aceptación: instalación sin Git LFS abre 001/t0 y GTV; prueba corrupto/truncado/sin red/archivo existente;
reintento seguro, limpieza de temporales y datos propios intactos. Manifest no incluye datos personales.

### D3d — Lanzadores y arranque comprobado

Depende de D3a; integración con D3b/D3c/D3e. Archivos: `tools/setup/`, lanzadores del paquete y tests.

1. Comprobar Docker instalado y daemon accesible, contexto adecuado, Compose mínimo, CPU/plataforma,
   RAM y disco del entorno Docker. Mostrar requisitos y remedio concretos, sin inventar cifras disponibles.
2. Comprobar ambos puertos y persistir selección. Derivar issuer, origen y callback coherentes mediante
   Compose; respetar origen explícito. Detectar respuesta de otro servicio aunque su HTTP sea 200.
3. Ejecutar descarga y arranque con espera acotada, observar inicializadores y healthchecks, y comprobar
   nginx, API y configuración OIDC. Abrir navegador solo cuando el stack esperado esté disponible.
4. Mostrar etapas (descarga, datos, identidad, aplicación), URL final y credenciales demo locales.
   Timeout devuelve salida distinta de cero y diagnóstico útil; permitir repetir sin reset.
5. Probar invocación fuera de la carpeta, espacios/Unicode, CRLF, cancelación y doble ejecución simultánea.
   Mantener una alternativa de comando si el sistema bloquea scripts descargados.

Aceptación: recorrido de primera instalación en cada plataforma declarada, sin intérpretes adicionales;
8080 y 8081 ocupados resueltos sin tocar al propietario; arranque posterior reutiliza configuración.
Compose directo sigue funcionando con puertos disponibles; no necesita ejecutar primero el lanzador.

### D3e — Diagnóstico seguro y estado comprensible

Depende de D3a. Archivos: herramientas de diagnóstico, inicializadores, tests y documentación.

1. Comando único de diagnóstico que distingue Docker detenido, puerto ajeno, imágenes antiguas,
   inicializador fallido, datos ausentes/punteros LFS, permisos, falta de recursos y proveedor no listo.
2. Mostrar servicio, estado y acción sugerida, usando el proyecto/contexto elegido; tratar setup exitoso
   como completado. No sugerir reiniciar todo ni borrar volúmenes como solución genérica.
3. Exportar reporte local opcional con versiones/digests, puertos y códigos de comprobación permitidos.
   No enviar nada automáticamente. Tests con secretos y datos personales sintéticos garantizan exclusión.

Aceptación: reproducir fallos del profesor y distinguirlos del frontend sano; reporte compartible sin
secretos; funciona parcialmente aunque el stack no haya arrancado y explica comprobaciones no disponibles.

### D3f — Versión visible y verificable

Depende de D3a y metadatos D3b. Archivos: configuración Vite, UI, imágenes y manifest.

Mostrar versión y commit de compilación en un lugar discreto, copiable para feedback. Desarrollo muestra
un valor honesto (`dev`), no una release falsa. Diagnóstico compara lo instalado con lo declarado y detecta
mezclas de imágenes. Evitar un endpoint nuevo si los metadatos existentes bastan; si se cambia una API,
actualizar `schemas.py`, `frontend/src/api/types.ts` y PLAN_MVP §7 en el mismo cambio.

Aceptación: versión visible coincide con imagen ejecutada tras actualizar; revisión visual en ambas
resoluciones y prueba de ausencia de datos de build privados en el bundle.

### D3g — Actualización, conservación y recuperación

Depende de D3b/D3d/D3e. Archivos: lanzadores, herramientas de release y guía operativa.

1. Actualización explícita a versión fija: descargar/verificar primero, comprobar trabajos activos y
   posponer si existen. Registrar versión anterior y conservar configuración, datos, modelos y secretos.
2. Definir backup consistente recuperable de PostgreSQL y sus secretos, configuración y archivos
   persistentes antes de migraciones incompatibles; tratar el backup como privado, nunca como diagnóstico.
3. Separar actualizaciones de la aplicación de upgrades de PostgreSQL/Keycloak. Fijar compatibilidad de versiones y estrategia de retorno. Volver a una imagen no revierte una
   migración de base de datos: no prometer downgrade automático; requerir restauración validada cuando aplique.
4. Proporcionar detener/iniciar sin borrar datos. No ofrecer reset destructivo como paso de instalación.
   Validar cuenta modificada, reader, usuario deshabilitado y acciones requeridas después de actualizar.

Aceptación: actualización y fallo de descarga mantienen datos; fallo posterior ofrece recuperación
probada; ejercicio de restauración en entorno aislado. Sin `down -v`, prune ni cambio de contraseñas automático.

### D3h — QA de instalación y publicación

Depende de D3b–D3g para aprobación final; preparar fixtures y CI desde D3a.

- Tests rápidos sin red para lógica, manifest, configuración, selección de puertos y redacción.
- Integración aislada con Docker/Keycloak real: instalación sin `.env.auth`, sin LFS y sin herramientas
  de desarrollo en host; login demo, visor con muestra, logout devuelve 401; reinicio sin red con cachés.
- Casos negativos: ambos puertos ocupados, proveedor lento, permisos, muestra corrupta, espacio insuficiente,
  registro inaccesible, inicializador fallido, configuración anterior y checkout con CRLF.
- Migración desde CP-051 con datos conocidos: hashes de claves/credenciales/resultados antes/después,
  rol/estado conservados, cambio de ambos puertos y actualización repetida.
- Matriz real: Linux amd64, Windows con contenedores Linux, macOS Apple Silicon; Intel Mac cuando se
  declare validado. Tests de shell o YAML no equivalen a ejecutar Docker Desktop en Windows/macOS.
  Si runners alojados no permiten Docker Linux en esos sistemas, usar equipo/runner dedicado y registrar
  evidencia manual reproducible. No marcar soporte validado hasta disponer de esa evidencia.
- Checks obligatorios del repositorio, pruebas Node/auth pertinentes, smoke Docker autenticado y
  revisión de capturas 1440×900 y 1280×800. Una prueba real de inferencia en runner apto antes de publicar
  cambios de runtime/arquitectura; no ejecutar modelos en cada PR documental.
- Medir tamaño descargado, disco máximo, RAM y tiempo hasta login/visor en arranque frío y caliente;
  publicar condiciones de medición, no prometer un tiempo universal.

Aceptación: todos los casos obligatorios pasan sobre los mismos digests que se promueven; evidencia
sin secretos, fallos visibles y limpieza restringida al proyecto QA. No tocar el Docker de uso diario.

### D3i — Documentación para usuarios y entrega

Depende del contrato D3a; cierre después de D3h. Archivos: README, guía de instalación/release,
HANDOFF y PROGRESS.

README empieza con «Usar la demo»: Docker, descargar paquete, iniciar, abrir URL e iniciar sesión.
Separar «Desarrollar» con Git/LFS/uv/Node. Explicar primera descarga y uso de modelos, requisitos reales,
actualización, detener, ubicación de datos, diagnóstico y limitaciones locales. Mantener comandos anteriores
compatibles. Incluir recorrido corto que un profesor pueda seguir desde cero sin consola administrativa.
Actualizar estados solo con pruebas realizadas; tras merge, registrar checkpoint y commit desplegado.

Aceptación: otra persona sigue el paquete sin instrucciones externas; enlaces válidos; comandos copiados
funcionan y no hay requisitos de desarrollo en el camino del usuario final.

## 5. Ejecución por Sol y subagentes

Sol coordina, decide cuántos subagentes necesita cada tarea y conserva la responsabilidad de integración.
Este documento autoriza delegación; no exige lanzar un agente por cada apartado ni mantener agentes ociosos.

1. Iniciar en `feat/D3-simple-setup`, revisar estado y fijar D3a. Crear commits pequeños por ticket.
   La petición del usuario de una rama nueva para esta iniciativa prevalece sobre abrir un PR por cada ticket.
2. Para trabajo simultáneo, usar worktrees/rama temporal derivados de esta rama; asignar propietario de
   archivos, dependencias, criterios de aceptación y comandos. No permitir ediciones concurrentes de Compose,
   lockfiles o documentos de estado. Sol integra secuencialmente y resuelve conflictos.
3. Ola 1: D3a con Sol; un subagente puede revisar migración y conservación. Arrancar diseño de QA sin mutaciones.
4. Ola 2: D3b (distribución/CI), D3c (muestra) y D3e (diagnóstico), independientes tras congelar el contrato.
   Sol integra cambios compartidos de Compose. Ajustar concurrencia a los slots y recursos disponibles.
5. Ola 3: D3d (lanzadores), D3f (UI/metadatos), preparación D3h; D3i puede redactarse contra contratos cerrados.
6. Ola 4: D3g y QA integral D3h, revisión independiente de preservación/redacción, cierre D3i.
7. Cada subagente devuelve commit, archivos, pruebas ejecutadas, fallos y límites; nunca declara pruebas
   no ejecutadas ni modifica main, publica releases o recrea el Docker diario por su cuenta.
8. Sol revisa diffs, ejecuta QA integrada y prepara PR. Publicación estable y merge solo después de cumplir
   los gates y la autorización vigente. No publicar artefactos incompletos por el mero hecho de acabar un ticket.

Bloqueos externos se registran con evidencia: visibilidad GHCR, licencia del dataset, cuota/runner disponible.
Continuar tareas independientes; no reemplazar evidencia faltante por suposiciones. Esta entrega es solo
el plan: no configura cuentas externas, no publica imágenes y no inicia implementación de D3.

## 6. Orden de entrega y definición de terminado

D3a precede a D3b/D3c/D3e; después D3d/D3f, D3g, D3h y cierre D3i. La documentación puede avanzar en paralelo.
Primera meta útil: paquete sin compilación con muestra, login y diagnóstico. Segunda: actualización y
recuperación verificadas. Ninguna se anuncia como release estable antes de sus pruebas correspondientes.

D3 termina cuando existe una release descargable y probada, arranca por Compose y lanzador, muestra la
versión real, conserva instalaciones anteriores, dispone de diagnóstico seguro y permite recuperación
validada. El README describe exactamente esa experiencia. Merge y checkpoint referencian la evidencia.

## 7. Referencias técnicas verificadas para el plan

- [Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up/): espera de servicios y
  recreación de contenedores. La salud de la aplicación se valida además de esperar contenedores.
- [Variables de Compose](https://docs.docker.com/compose/how-tos/environment-variables/envvars/):
  precedencia de proyecto y configuración; relevante para no crear volúmenes distintos al actualizar.
- [Publicación de imágenes con GitHub Actions](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images):
  flujo de publicación, permisos y fijación de acciones.

Revalidar APIs y versiones al implementar; los comandos específicos de lanzamiento que aún no existen
son requisitos de este plan, no instrucciones disponibles para el profesor hoy.

## 8. Contrato congelado D3a · ejecución 2026-11-11

Ver [contrato de paquete](../../../tools/release/CONTRACT.md). Distribución generada desde Compose
mediante `tools/release/package.py`: sin build, imágenes por digest, recursos de identidad incluidos.
Compose mínimo 2.30.0; plataformas esperadas, pendientes de evidencia D3h. Directorio de instalación
persistente, rutas absolutas para migración y nombre de proyecto conservado. Worker espera permisos;
Data se prepara solo en distribución. No se recrea el stack diario ni se publican artefactos.

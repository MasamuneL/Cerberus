# Ejecución D3 · 2026-11-11

Rama: `feat/D3-simple-setup`. Base: `0ddd560`. Sin publicación ni merge autorizados.
Docker diario conservado: seis contenedores con los mismos IDs antes y después de QA.
`.omo/` preexistente no se modifica ni se incorpora.

## Implementación y revisión

| Ticket | Estado de implementación | Evidencia / límite |
|---|---|---|
| D3a | Integrado en rama | Contrato, Compose generado, migración explícita y verificación de escritura con UID operativo |
| D3b | Integrado en rama | ZIP determinista, allowlist, OCI y workflows protegidos; GHCR pendiente |
| D3c | Integrado en rama | Cuatro NIfTI públicos, hashes y TAR determinista; artefacto remoto pendiente |
| D3d | En cierre | Lanzadores Bash/PowerShell en worktree propio; sin validación Windows real |
| D3e | Integrado en rama | Whitelist, diagnóstico parcial, metadatos públicos y `.env` migrada entre comillas |
| D3f | Integrado en rama | `dev` honesto y metadatos de compilación visibles; capturas revisadas |
| D3g | En cierre | Guardas de integridad, identidad y cola; backup/restauración en implementación |
| D3h | Parcial | Suites y Docker aislado comprobados; matriz, recuperación y digests remotos pendientes |
| D3i | Parcial | README separa usuario/desarrollo; guía y estado se cierran tras QA |

Revisión independiente de base: corregidos frontend amd64 sin `platform`, puertos migrados entre
comillas, omisión de `setup-sample` en diagnóstico y metadatos ausentes del reporte. D3g debe comprobar
también el digest del inicializador de muestra al verificar un paquete.

## Pruebas realizadas

- Suite integrada previa al cierre de lanzadores/recuperación: **915 rápidas**, 5 slow excluidas;
  Ruff, formato y Pyright correctos. Las cifras finales se registrarán al integrar ambos tickets.
- Auth: 5 pruebas de volúmenes y 10 pruebas Node; 12 escenarios UI y 8 de sesión/continuidad correctos.
- Vite/API separados del Docker diario: **33/33** comprobaciones visuales, **14 auditorías axe**
  sin violaciones automáticas; capturas 1440×900 y 1280×800 revisadas.
- Primera corrida visual se interrumpió tras descubrir que la fixture aislada no contenía resultados.
  Se copiaron resultados al almacenamiento QA, sin escribir en el original, y se repitió: 33/33.
  Los fallos de la primera corrida no se presentan como aprobación ni como cambios requeridos del producto.
- Build local de backend y frontend Linux amd64 con etiquetas `cerberus-d3-qa-*:local`, separadas
  de las imágenes diarias. Backend de QA `9747a28`; frontend de QA `ba31972`. Son revisiones locales
  distintas: esta evidencia **no** demuestra promoción de un conjunto final de digests del mismo commit.
- Compose generado de distribución, proyecto aislado `cerberus-d3-qa`, rutas y volúmenes nuevos,
  puertos 18082/18083: seis servicios sanos y tres inicializadores con salida 0.
  Muestra precargada desde el TAR verificado; no se atribuye esta prueba a una descarga fría desde GitHub.
- Login real `demo` / `demo`, rol analyst, catálogo exclusivo 001/t0, visor/GTV y logout con catálogo
  y NIfTI a 401. Smoke autenticado **15/15**, sin errores de descarga/JS; ambas resoluciones revisadas.
- Inferencia real CPU dentro del backend QA: WT 49.95 cm³, TC 30.17 cm³, ET 21.53 cm³;
  Dice TC/GTV 0.844, WT/GTV 0.725. Verificada también con `configure_threads()` antes de importar modelos.
  Resultados exclusivamente en almacenamiento QA. No constituye validación clínica ni agregada.
- Cambiados ambos puertos a 18084/18085 y reiniciado el stack QA: hashes idénticos de secretos,
  Data, resultados y modelos. Huella de usuarios/credenciales/roles conservada: contraseña demo cambiada,
  cuenta reader, usuario deshabilitado y acciones requeridas. Login con contraseña cambiada, smoke 15/15
  y logout/401 correctos después del cambio.
- Inicializador de muestra en contenedor con `--network none`: verifica archivos presentes sin descarga.
- Muestra real: 144,302,080 bytes de TAR, SHA-256
  `1d814107ba6858d4eabbb70d43ff09387349efc701cb1d29d9f8d2ddcdf4012f`.
  Procedencia/licencia y hashes por NIfTI en [D3_SAMPLE](../D3_SAMPLE.md).

## Medición local y límites

Docker Desktop, contexto `desktop-linux`, host macOS Apple Silicon, contenedores Linux amd64 emulados,
Compose 5.7.0. Arranque con imágenes y muestra precargadas: aproximadamente **40.2 s** hasta servicios
sanos (duración de escritura del log). No mide descarga fría. No se ha medido tráfico comprimido,
disco máximo ni memoria pico del conjunto; no se publican cifras universales de requisitos o tiempos.
Las capturas no demuestran por sí solas conformidad de accesibilidad completa.

## Decisiones e interfaces

- Distribución generada del Compose existente: el YAML de desarrollo y Docker diario permanecen intactos.
- API/worker/inicializadores comparten digest en el paquete. Manifest `format=1`, `state_format=1`,
  versión, revisión SHA40 e imágenes por digest. La generación ignora el proyecto y `.env` del empaquetador.
- Migración explícita preserva proyecto real y montajes absolutos; volúmenes personalizados incompatibles
  bloquean la adopción automática. El usuario conserva la instalación anterior hasta validar la nueva.
- Datos persistentes en carpeta fija. UID/GID numéricos; solo se ajustan raíces vacías, sin chown recursivo.
- Diagnóstico reconstruido por whitelist: no logs, secretos, entornos ni rutas personales. Digests sin
  nombres de registros; versión/revisión y puertos públicos validados. Modo `none` conserva datos propios.
- Publicación y promoción no ejecutadas. CI candidato exige autorización manual, pull anónimo, OCI exacta
  y muestra remota verificada antes de producir paquete. No hay release estable ni checkpoint de merge.

## Bloqueos y gates pendientes

1. Publicar muestra e imágenes requiere autorización posterior; URL de muestra aún prevista. Sin ello
   no existe instalación fría descargable ni evidencia de GHCR anónimo. No cambiar visibilidad de cuentas
   ni sustituir ese gate por imágenes locales.
2. Matriz real Linux amd64, Windows con Docker Linux, macOS Apple Silicon e Intel cuando se declare:
   solo hay evidencia Docker Desktop de este Mac; analizar scripts o ejecutar PowerShell en macOS no
   demuestra instalación en Windows. Compose mínimo declarado 2.30.0, prueba local con 5.7.0.
3. Ejercicio operativo de actualización, fallo de pull y restauración privada en proyecto aislado.
4. QA final sobre los mismos digests del mismo commit antes de promover una release; mediciones frías,
   disco máximo y memoria pico del conjunto.
5. A5 y ola P del QA previo siguen independientes; D3 no las cierra automáticamente.

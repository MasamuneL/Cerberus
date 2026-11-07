# Autenticación A1–A5 · Plan de ejecución

> **Para agentes:** ejecutar con `superpowers:executing-plans`, un ticket por rama y con revisión independiente antes de integrar.

**Objetivo:** completar el inicio de sesión de la demo según `docs/PLAN_MVP.md` §17.

**Arquitectura:** Keycloak y PostgreSQL privados en un overlay; FastAPI como cliente confidencial OIDC con
PKCE, transacciones y sesiones opacas en Redis. React consulta la sesión y refleja permisos; la API los
impone antes de leer archivos o encolar trabajos.

**Tecnologías:** Compose, Keycloak 26.8.1, PostgreSQL 18, Authlib, FastAPI, Redis, React y Playwright.

**Especificación:** [`PLAN_MVP.md` §17](../../PLAN_MVP.md#17-autenticación-para-demo-académica--oidc--keycloak).
El usuario autorizó continuar todos los tickets posibles, hacer commits/push frecuentes y ejecutar QA
antes de cada merge a `main` el 2026-11-05.

## Restricciones globales

- Respetar contratos de §6/§7 y actualizar Python/TypeScript/documentos conjuntamente cuando cambien.
- Identidad por (`issuer`, `sub`), roles `reader`/`analyst`; sin tokens OIDC en navegador ni logs.
- Transacciones de 300 s, sesión con inactividad de 1800 s y máximo absoluto de 3600 s.
- Secretos locales ignorados por Git; ninguna cuenta ni contraseña versionada.
- Publicar solo en loopback; HTTP y `start-dev` exclusivamente para esta demo.
- Un ticket por rama; reservarlo, commit/push, TDD, revisión, QA, PR/merge y checkpoint antes del siguiente.
- A5 requiere la ola P del QA; resolver sus dependencias con pruebas antes de declarar la fase terminada.

## Puntos de revisión

- Arranque repetido debe conservar cuentas, secretos y contraseñas existentes.
- Backchannel debe conservar el issuer público validado y evitar endpoints arbitrarios.
- Callbacks repetidos o iniciados en otro navegador deben fallar sin crear sesión.
- Redis caído debe denegar acceso; archivos con ETag tampoco deben escapar de la autenticación.
- Dos analistas no deben consultar ni modificar jobs o subidas ajenas, incluso tras un nuevo login.

## A1 · Proveedor reproducible

**Archivos:** `compose.auth.yaml`, `docker/keycloak/realm.json`, `tools/auth/bootstrap.py`, pruebas del bootstrap,
`.gitignore`, README, PLAN_MVP, HANDOFF y PROGRESS.

**Interfaces:** variables de A0 en API; realm `cerberus`, cliente confidencial `cerberus-web`, callback exacto
`APP_ORIGIN/api/auth/callback`, PKCE S256 obligatorio, claim `cerberus_roles` en ID Token. Bootstrap crea
`.env.auth` con permisos 0600 usando secretos del entorno o aleatorios; no sobreescribe archivos existentes.

- [x] Probar generación sin mostrar secretos, permisos, valores ambientales y repetición sin sobrescritura.
- [x] Crear overlay con PostgreSQL sin puertos, Keycloak en 8081 de loopback y healthchecks.
- [x] Crear realm sin usuarios; registro público, implicit y password grant desactivados; roles de aplicación
  y mapper limitado al cliente para excluir roles administrativos.
- [x] Validar Compose y stack real, metadata/JWKS desde API, callback/roles y persistencia tras reinicio.
- [x] Checks del repo, revisión independiente, commit/push/PR y merge solo después del QA; checkpoint.

## A2 · OIDC y sesiones

**Archivos:** `oidc.py`, `sessions.py`, `routers/auth.py`, `deps.py`, `main.py`, dependencias y tests.

**Interfaces:** `/api/auth/config`, `/login`, `/callback`, `/me`, `/logout` de §17.4. El almacén Redis consume
transacciones una sola vez y renueva sesión al autenticar; tiempos y transporte inyectables en pruebas.

- [x] Verificar Authlib instalado, licencia y avisos; añadirlo a dependencias principal/runtime.
- [x] TDD del almacén: navegador, repetición, inactividad, máximo absoluto, renovación y Redis indisponible.
- [x] TDD de OIDC: firma/algoritmo/issuer/audience/exp/nonce/azp, rotación de claves y proveedor caído.
- [x] Rutas con errores genéricos, cookies HttpOnly/Lax y logout con CSRF/Origin; modo off conserva 404.
- [x] QA de login real con Keycloak y expiración/logout; checks, revisión, publicación/merge y checkpoint.

## A3 · Permisos y propiedad

**Archivos:** `access.py`, middleware/dependencias, routers, worker, nginx, cliente y tests.

**Decisiones de implementación:**

- `create_app(settings: Settings | None = None, *, session_factory: SessionFactory | None = None)` permite
  inyectar configuración/almacén, sin modo de bypass. El estado de la app conserva ambos; `settings_dep`
  obtiene la configuración de esa app y `session_store_dep` comparte su fábrica. El pool real sigue siendo lazy.
- Middleware ASGI antes de parsear body o leer disco: auth OIDC para `/api`, salvo salud y rutas auth que
  aplican sus propias guardas. Mutaciones requieren analista y CSRF/Origin; jobs/uploads requieren analista
  y propietario. Sin metadata: 404. Archivos GET/HEAD se autentican antes de ETag/304.
- Modo local: mutaciones requieren `X-Cerberus: 1`; `Origin`, cuando venga, debe estar autorizado.
  El cliente web añade la cabecera; los tests usan Host localhost y cabeceras legítimas, con casos negativos explícitos.
- Revisión: Access y privacidad de callback usan `get_route_path(scope)` para seguir el `root_path` de Starlette
  sin permitir que un prefijo omita guardas o conserve la query sensible.
- `TrustedHostMiddleware` con origen configurado y loopbacks; nginx rechaza Host ajeno mediante servidor
  por defecto. `CallbackPrivacyMiddleware` permanece como último middleware añadido para cubrir rechazos tempranos.
- Propietarios Redis bajo `cerberus:auth:owners:jobs:<id>` y `...:uploads:<id>`, identidad serializada
  (`issuer`, `sub`), IDs UUID hex canónicos. Registrar antes de publicar/encolar; limpiar si el encolado falla.
- Hook arq `after_job_end` (verificado en 0.28) corre después de guardar resultados: alinear TTL de propietario
  con `arq:result:<id>`; conservarlo si hay reintento pendiente y quitarlo si desapareció el recurso.
  Revisión: arq omite ese hook en fallos tempranos. `OwnedWorker.finish_failed_job` cubre ese camino;
  launcher `python -m cerberus_api.worker` sustituye la CLI para ejecutar jobs (su healthcheck se conserva).
  Confirm/delete de ingesta limpia propietario después de completar la operación, con I/O en threadpool.
- JSON autenticado `no-store`; volúmenes autenticados `private, no-cache`. Swagger/ReDoc/OpenAPI desactivados en OIDC.
- QA: matriz completa offline, body no consumido ante rechazo, dos analistas, metadata ausente, TTL/limpieza,
  CSRF/Host en ambos modos y GET/HEAD condicional tras logout; luego flujo real de ingesta fallida temporal
  para probar propiedad sin ejecutar MONAI/ANTs. Validar modo local antes de merge.

- [x] TDD de la matriz completa de §17.3, incluido GET/HEAD con ETag después de logout.
- [x] Vincular propietarios antes de publicar recursos; denegar metadata ausente y accesos cruzados.
- [x] Imponer CSRF/Origin y Host antes de body/I/O/jobs; proteger también el modo local (S1/S2).
- [x] Aplicar caché privada/no-store y deshabilitar documentación pública en modo OIDC.
- [x] QA por HTTP y Docker, revisión, checks, commit/push/merge y checkpoint (PR #9, CP-045).

## A4 · Interfaz de acceso

**Archivos:** `useAuth.ts`, `LoginPanel.tsx`, `App.tsx`, cliente, hooks y paneles/visor.

**Decisiones de implementación:**

- App monta el workspace solo después de config `off` o sesión OIDC válida. Estados: carga, anónimo,
  autenticado, expirado, sin permisos y servicio indisponible. Login mediante enlace fijo `/api/auth/login`.
- CSRF y rol solo en memoria. Cliente común añade CSRF a mutaciones; 401 invalida sesión, cancela peticiones
  y desmonta workspace/polling/visor. 403 de recursos permanece como error de permisos, sin fingir expiración.
- Niivue instalado no propaga `AbortSignal` ni `buffer` desde `loadVolumes`. Descargar con cliente común,
  decodificar mediante `NVImage.loadFromUrl({url: ArrayBuffer, name, ...})` verificado y añadir volúmenes
  con `addVolume`. Conservar URL HTTP para ETag; no reemplazar fetch global ni cachear tokens/datos en storage.
- Temporizador al vencimiento efectivo con margen y comprobación `/me`; revalidación al volver a ventana,
  sin sondeo periódico que mantenga sesiones vivas. La caducidad local toma `X-Cerberus-Session-Expires-At`
  de las respuestas protegidas (milisegundos Unix); el cliente ignora generaciones anteriores. Logout retira workspace al empezar y no afirma cierre
  confirmado si Redis/red fallan; permite reintentar con CSRF conservado únicamente en memoria.
- Lector ve resultados y controles del visor; no subida ni botones de segmentación/mapeo. Analista y modo
  local conservan mutaciones. Quitar listener/caché de recursos al desmontar último consumidor.
- Ruling: navegaciones HTML con error OIDC vuelven por 303 a `/?auth_error=<código fijo>` para que la UI
  explique falta de permisos/servicio/error. Clientes JSON conservan 400/401/403/503; actualizar §7, tipos
  y tests backend en el mismo PR. La query pública no contiene identidad, code ni state.
- QA UI con respuestas HTTP controladas para RED→GREEN; luego cuentas temporales reales/Keycloak,
  lector/analista/sin rol, caducidad, descarga pendiente cancelada, logout, teclado/axe y regresiones off.

- [x] Implementar carga, anónimo, lector, analista, sin permisos y expiración, con textos españoles.
- [x] Login por redirección y logout con CSRF; 401 detiene polling/descargas y desmonta datos/visor.
- [x] Reflejar permisos en todos los controles; 403 no debe fingir expiración.
- [ ] QA real con teclado y ambos roles, modo off y sesión caducada; build, revisión, publicación/merge.

### Ampliación aprobada · 2026-11-07

El usuario autorizó incorporar las mejoras de revisión y ejecutarlas con subagentes. Se mantiene un único
PR de A4 y un coordinador de commits/QA; cada implementador tiene archivos exclusivos para evitar conflictos.

| Tarea | Responsable | Alcance verificable |
|---|---|---|
| A4.1 · visor y descargas | Subagente de medios | Cliente común y AbortSignal en NIfTI; 401 desmonta; cancelar al salir/cambiar estudio; conservar ETag, capas y nombres |
| A4.2 · sesión y red | Subagente de sesión | Timeout en cliente; logout403 recupera CSRF y reintento acotado; eventos entre pestañas sin credenciales; estados de error diferenciados |
| A4.3 · continuidad | Subagente de sesión | Aviso previo y comprobación explícita; recuperar UUID de jobs/ingestas propios después de reingresar, validando por API |
| A4.4 · presentación y proveedor | Subagente de UX/proveedor | Tema Cerberus en Keycloak; textos españoles; explicar rememberMe/prompt; actualización idempotente del realm sin tocar cuentas |
| A4.5 · pruebas e integración | Coordinador | Regresiones RED→GREEN, teclado/axe y cuentas reales; revisar errores cruzados, persistencia, timeouts y reinicios |
| A4.6 · entrega | Coordinador + revisor independiente | Checks obligatorios, visual Vite y Docker, revisión final, PR/merge después de QA y checkpoint |

- [x] Corregir 401 de NIfTI y aborto de descargas pendientes.
- [x] Recuperar CSRF tras rotación entre pestañas y diferenciar logout403/503.
- [x] Sincronizar sesión entre pestañas sin datos de identidad ni tokens.
- [x] Limitar esperas HTTP de configuración/me/logout y permitir recuperación.
- [x] Avisar antes de caducar sin sondeo que mantenga viva la sesión.
- [x] Recuperar solo referencias opacas propias; limitar tamaño/edad y descartar 403/404.
- [x] Explicar y probar rememberMe con prompt=login y límites fijos de Cerberus.
- [x] Unificar presentación/español y aplicar cambios del proveedor idempotentemente.

**Decisiones:** mantener `prompt=login` del commit 000c958 y la persistencia del proveedor, sin aumentar tiempos
Cerberus ni introducir refresh tokens. La continuidad usa únicamente UUID opacos en sessionStorage y valida
acceso antes de mostrar información; no añade endpoints ni permite adoptar recursos sin propietario.
La notificación entre pestañas solo nace de un login real (`/?auth_event=login`, señal pública fija que
se consume/borra) o de logout. Abrir otra pestaña normal no retira datos ni aborta trabajo de las existentes.
Respuestas concurrentes no pueden reducir el deadline de la misma generación: se conserva el mayor plazo,
con reinicio al autenticar otra sesión. Regresión de respuestas invertidas y cambio de generación incluida.
Los subagentes no comparten commits ni ejecutan Chrome simultáneamente: el coordinador publica y corre QA.

## Dependencias de A5 · Ola P

**Archivos:** NIfTI, DICOM, uploads, worker y tests según `QA_2026-10-29.md`.

- [ ] P1/P2/P3/P5: limpiar metadatos NIfTI y mensajes, limitar descripciones y evitar resultados sensibles en logs.
- [ ] S3/Q1/Q2/Q4: limitar tamaño/dimensiones antes de materializar vóxeles y rechazar archivos truncados.
- [ ] Q3: limpieza de temporales tras crash; coordinar con ingestas activas para no borrar trabajo válido.
- [ ] S1/S2 ya se resuelven con A3. Pruebas sin red y QA en Docker antes de integrar cada cambio.

## A5 · E2E y documentación

**Archivos:** `verify-auth.mjs`, runners existentes, README, PLAN_MVP, HANDOFF y PROGRESS.

- [ ] Automatizar cuentas de QA temporales y sesiones reales, sin bypasses de permisos.
- [ ] Probar login lector/analista, acceso directo y archivos, propiedad, CSRF, expiración y logout en 8080,
  más Vite 5173; revisar capturas y accesibilidad.
- [ ] Ejecutar regresiones previas con sesión cuando corresponda y modo off; resolver fallos observados.
- [ ] Checks, revisión independiente, QA completo, publicación/merge y checkpoint final verificable.

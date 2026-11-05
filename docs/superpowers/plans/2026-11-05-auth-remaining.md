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

- [ ] Probar generación sin mostrar secretos, permisos, valores ambientales y repetición sin sobrescritura.
- [ ] Crear overlay con PostgreSQL sin puertos, Keycloak en 8081 de loopback y healthchecks.
- [ ] Crear realm sin usuarios; registro público, implicit y password grant desactivados; roles de aplicación
  y mapper limitado al cliente para excluir roles administrativos.
- [ ] Validar Compose y stack real, metadata/JWKS desde API, callback/roles y persistencia tras reinicio.
- [ ] Checks del repo, revisión independiente, commit/push/PR y merge solo después del QA; checkpoint.

## A2 · OIDC y sesiones

**Archivos:** `oidc.py`, `sessions.py`, `routers/auth.py`, `deps.py`, `main.py`, dependencias y tests.

**Interfaces:** `/api/auth/config`, `/login`, `/callback`, `/me`, `/logout` de §17.4. El almacén Redis consume
transacciones una sola vez y renueva sesión al autenticar; tiempos y transporte inyectables en pruebas.

- [ ] Verificar Authlib instalado, licencia y avisos; añadirlo a dependencias principal/runtime.
- [ ] TDD del almacén: navegador, repetición, inactividad, máximo absoluto, renovación y Redis indisponible.
- [ ] TDD de OIDC: firma/algoritmo/issuer/audience/exp/nonce/azp, rotación de claves y proveedor caído.
- [ ] Rutas con errores genéricos, cookies HttpOnly/Lax y logout con CSRF/Origin; modo off conserva 404.
- [ ] QA de login real con Keycloak y expiración/logout; checks, revisión, publicación/merge y checkpoint.

## A3 · Permisos y propiedad

**Archivos:** `access.py`, middleware/dependencias, routers, worker, nginx, cliente y tests.

- [ ] TDD de la matriz completa de §17.3, incluido GET/HEAD con ETag después de logout.
- [ ] Vincular propietarios antes de publicar recursos; denegar metadata ausente y accesos cruzados.
- [ ] Imponer CSRF/Origin y Host antes de body/I/O/jobs; proteger también el modo local (S1/S2).
- [ ] Aplicar caché privada/no-store y deshabilitar documentación pública en modo OIDC.
- [ ] QA por HTTP y Docker, revisión, checks, commit/push/merge y checkpoint.

## A4 · Interfaz de acceso

**Archivos:** `useAuth.ts`, `LoginPanel.tsx`, `App.tsx`, cliente, hooks y paneles/visor.

- [ ] Implementar carga, anónimo, lector, analista, sin permisos y expiración, con textos españoles.
- [ ] Login por redirección y logout con CSRF; 401 detiene polling/descargas y desmonta datos/visor.
- [ ] Reflejar permisos en todos los controles; 403 no debe fingir expiración.
- [ ] QA real con teclado y ambos roles, modo off y sesión caducada; build, revisión, publicación/merge.

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

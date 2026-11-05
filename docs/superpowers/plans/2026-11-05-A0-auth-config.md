# A0 · Plan de implementación de contratos y configuración

> **Para agentes:** ejecutar con `superpowers:executing-plans`, siguiendo las tareas y comprobaciones de este documento.

**Objetivo:** preparar la configuración validada y los tipos del inicio de sesión acordado en §17.

**Arquitectura:** conservar el modo local `off` por defecto. Centralizar identidad interna en `identity.py`,
configuración privada en `Settings` y respuestas públicas en `schemas.py` y TypeScript. A0 todavía no
implementa rutas de autenticación, sesiones, protección de recursos ni interfaz de acceso.

**Tecnologías:** Python 3.11, Pydantic v2/pydantic-settings, TypeScript y pytest; sin dependencias nuevas.

**Especificación:** [`PLAN_MVP.md` §17](../../PLAN_MVP.md#17-autenticación-para-demo-académica--oidc--keycloak),
integrada por el PR #4; el usuario pidió continuar su implementación el 2026-11-05.

## Restricciones globales

- Un ticket por rama y PR; A1–A5 y las correcciones del QA quedan pendientes.
- `Role = Literal["reader", "analyst"]`; identidad estable por `issuer` y `sub`, con roles inmutables.
- Sesión prevista: inactividad de 1800 s y máximo absoluto de 3600 s; ambos positivos, absoluto ≥ inactividad.
- Secretos solo del entorno, ocultos en representación, serialización y mensajes de validación.
- HTTPS para origen e issuer públicos salvo HTTP de loopback; backchannel HTTP interno permitido explícitamente.
- Cookie insegura únicamente con origen HTTP de loopback; no comodines CORS en modo `oidc`.
- Ninguna modificación del notebook, datos, dependencias ni configuración de Compose en este ticket.

## Puntos de revisión

1. Valores ambientales de auth no deben activar auth accidentalmente en las pruebas existentes.
2. Hosts con sufijos engañosos, credenciales, rutas, query, fragmentos y puertos inválidos deben rechazarse.
3. No normalizar el issuer público ni confundirlo con el backchannel interno.
4. `AuthConfig` y `AuthSession` no deben exponer secretos ni identificadores de sesión/identidad.
5. `Principal` debe distinguir dos sujetos iguales de issuers diferentes y rechazar identidades vacías.

## Tarea 1 · Configuración e identidad

**Archivos:** modificar `backend/cerberus_api/config.py`, crear `backend/cerberus_api/identity.py` y
`backend/tests/test_auth_config.py`; aislar variables nuevas desde `backend/tests/conftest.py`.

**Interfaces:** `Settings` añade los campos de §17.2 con prefijo `CERBERUS_`; `auth_mode` acepta `off|oidc`,
`app_origin` usa `http://localhost:5173`, `oidc_client_id` usa `cerberus-web`,
`oidc_client_secret: SecretStr | None`; issuer/backchannel opcionales en modo off.
`Principal` es un modelo congelado con `issuer: str`, `sub: str`, `roles: frozenset[Role]` no vacíos.

- [ ] Escribir pruebas parametrizadas de defaults, entorno, campos obligatorios OIDC, secretos vacíos,
  timeouts cero/negativos/invertidos, seguridad de cookies y URLs válidas/engañosas.
- [ ] Ejecutar `uv run pytest backend/tests/test_auth_config.py -q`; observar fallos por funcionalidad ausente.
- [ ] Implementar validación con Pydantic instalado y análisis de URL, preservando el issuer exacto.
  Resolver backchannel omitido al issuer; no iniciar conexiones. Probar identidad inmutable y roles inválidos.
- [ ] Repetir pruebas focalizadas hasta obtener verde.

## Tarea 2 · Contratos públicos y documentación

**Archivos:** modificar `backend/cerberus_api/schemas.py`, `frontend/src/api/types.ts`,
`docs/PLAN_MVP.md`, `README.md`, `docs/HANDOFF.md`, `docs/PROGRESS.md`.

**Interfaces:** exportar `Role` y `AuthMode` compartidos; `AuthConfig(mode: AuthMode)` y
`AuthSession(roles: list[Role], expires_at: datetime con zona, csrf_token: str)`.
TypeScript usa `string` para fecha ISO-8601. `Principal` es interno y no se publica como respuesta.

- [ ] Añadir pruebas de serialización pública con fechas con zona y rechazo de roles/fechas inválidos;
  ejecutar antes de implementar los modelos.
- [ ] Implementar los modelos y su espejo TypeScript; documentar modelos disponibles y rutas pendientes A2.
- [ ] Registrar versión/licencia de Authlib consultadas en fuentes primarias; su instalación pertenece a A2.
- [ ] Ejecutar Ruff, formato, pyright, pytest rápido y build de frontend. Ejecutar el runner visual vigente
  y revisar capturas si los servicios/datos están disponibles; registrar cualquier límite real.
- [ ] Revisar el diff contra A0; commit, push y PR con criterios cumplidos. Mantener estado pendiente de
  integración hasta merge y registrar checkpoint/handoff verificables.

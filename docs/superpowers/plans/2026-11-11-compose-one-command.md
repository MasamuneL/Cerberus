# A1c: demo autenticada con un comando Compose

Solicitud: `docker compose up -d --build` debe levantar la demo con login y cuenta de prueba,
sin instalar Python en el host, generar archivos manualmente ni configurar Keycloak.

El Compose predeterminado incluirá identidad. Un servicio de inicialización generará tres secretos
aleatorios en volúmenes separados; PostgreSQL, Keycloak y API solo recibirán los archivos que necesitan.
Una `.env.auth` existente se acepta como fuente opcional de migración. Los secretos persistidos no se
sobrescriben; una base de datos previa sin secretos recuperables detiene el arranque.

Un segundo servicio de inicialización esperará a Keycloak y sincronizará presentación, cuenta demo
con SKIP y el callback exacto del cliente. El puerto público configura automáticamente origen y callback;
los cambios se limitan al cliente `cerberus-web`, conservando cuentas, credenciales y configuración ajena.
La API esperará esa sincronización antes de aceptar tráfico. El overlay antiguo seguirá siendo válido
como compatibilidad; el modo nativo de desarrollo conserva su comportamiento.

Validación: pruebas sin red de persistencia, migración, fallos y paridad de configuración; checks del
proyecto; arranque real en proyecto Compose aislado sin `.env.auth`; login con demo/demo, reinicio,
cambio de puerto y preservación de contraseña/cuentas existentes. Después, migración del Docker local
preservando volúmenes y resultados. Actualizar README, PLAN_MVP, HANDOFF y PROGRESS.

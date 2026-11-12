# Contrato D3 de distribución

Versión del formato: 1. Compose mínimo: 2.30.0 (env_file opcional y herramientas de configuración).
Backend siempre Linux amd64; frontend inicialmente Linux amd64. Windows con contenedores Linux,
macOS con Docker Desktop (Apple Silicon mediante emulación) y Linux con plugin Compose son plataformas
esperadas; ninguna se declara validada hasta ejecutar la matriz real D3h.

El ZIP contiene compose.yaml generado de la raíz (JSON compatible con YAML), release.json,
SHA256SUMS, docker/keycloak/realm.json y tema completo, tools/setup, lanzadores e instrucciones.
Imágenes backend/frontend fijadas por digest; api, worker e inicializadores comparten backend.
Redis, PostgreSQL y Keycloak conservan exactamente los digests de la base. Las versiones de identidad
no se actualizan junto con la aplicación. Metadatos: format=1, state_format=1 (compatibilidad del estado persistente), version, revision (SHA Git completo),
images={backend,frontend}, sample opcional. No se aceptan latest ni referencias sin digest.

La carpeta extraída es instalación persistente: Data/, storage/, models/ y .env local público.
No moverla ni extraer una versión encima: actualización explícita, conservando estos directorios.
Compose directo funciona sin lanzador y crea los bind mounts. setup-secrets prepara solo raíces vacías
con UID/GID configurado; worker espera su finalización. La muestra debe completarse antes del catálogo.
No se aplica chown recursivo ni se reemplazan archivos de usuario.

Migración: preparar primero la configuración desde contenedores anteriores identificables, incluso detenidos.
Después terminar trabajos y retirar explícitamente los contenedores anteriores con `docker compose down`
sin `-v`, conservando volúmenes y bind mounts, antes de iniciar desde la carpeta nueva. Resolver Data,
storage, models y .env.auth contra el checkout anterior y guardar rutas absolutas en .env del paquete;
conservar CERBERUS_UID/GID, puertos y origen personalizado. Adoptar el nombre de proyecto real obtenido
con docker compose ls/labels, nunca inventar uno distinto. COMPOSE_PROJECT_NAME debe coincidir con ese
nombre para conservar los seis volúmenes. No iniciar una segunda instancia con los mismos volúmenes.
No copiar secretos al manifest ni a diagnóstico. No inferir que una base sin sus claves está vacía.
Los lanzadores deben detectar una instancia activa del mismo proyecto y exigir usar su carpeta original.

Propietarios: coordinador integra package.py, Compose generado y documentación de estado. D3b posee
build.py, workflows y Dockerfiles; D3c sample.py, sample manifest y tests; D3e diagnostics.py y tests.
D3d posee tools/setup y lanzadores; D3f frontend; D3g update.py. Cada agente trabaja en worktree propio.
Ninguno publica, modifica main ni inicia/recrea servicios del proyecto diario cerberus.

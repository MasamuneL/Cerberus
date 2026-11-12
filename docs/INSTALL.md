# Usar la demo

El paquete D3 todavía es candidato: no hay release D3 publicada ni matriz multiplataforma aprobada.
El flujo siguiente describe el paquete generado, que debe superar los gates de
[QA D3](qa/D3_EXECUTION.md) antes de recomendarlo a otras personas.

## Primera instalación con paquete

1. Instala Docker Desktop (Windows/macOS) o Docker Engine con plugin Compose (Linux) y arráncalo.
   Se requieren contenedores Linux y Compose 2.30.0 o posterior. El backend usa Linux amd64;
   Apple Silicon requiere emulación. Las plataformas verificadas se registran en el QA, sin inferirlas
   a partir de que un script se pueda analizar.
2. Descarga el ZIP de una versión fija aprobada y comprueba SHA256SUMS. Descomprime en una carpeta
   permanente con espacio suficiente para imágenes, muestra, modelos y resultados. No necesitas
   Git, Git LFS, Python, uv ni Node para ejecutar el paquete.
3. Ejecuta `start.ps1` en Windows o `bash start.sh` en Linux/macOS. En macOS también está `start.command`.
   Desde PowerShell, si la política impide scripts descargados, revisa el archivo y usa el comando
   Compose siguiente; no es necesario cambiar la política global del equipo.
4. Espera descarga de imágenes, preparación de datos, identidad y aplicación. Abre la URL que indique
   el lanzador e inicia sesión con `demo` / `demo`.
5. Selecciona paciente 001, tiempo t0, T1 con gadolinio y activa GTV. El GTV excluye edema.

Alternativa desde la carpeta del paquete, con 8080 y 8081 disponibles:

```bash
docker compose up -d --wait --wait-timeout 600
```

Abre `http://localhost:8080`. Keycloak utiliza también 8081. Si otro programa ocupa esos puertos,
no lo detengas: el lanzador selecciona puertos predeterminados libres y conserva la selección.
Un puerto fijado explícitamente que esté ocupado requiere corregir la configuración o liberar ese
puerto por decisión del propietario. Los dos inicializadores con salida 0 son normales.

La primera descarga requiere red. La muestra se verifica por tamaño y SHA-256, sin sobrescribir
archivos distintos. Una muestra válida no vuelve a descargarse. Los modelos MONAI y atlas se
obtienen al usarlos y permanecen en caché: el primer procesamiento puede necesitar red adicional.
No hay tiempo universal de arranque ni consumo prometido; consulta mediciones reales del QA.

## Datos y reinicios

Conserva la carpeta de instalación: `Data/`, `storage/` y `models/` son persistentes; las cuentas,
trabajos y secretos utilizan volúmenes Docker del mismo proyecto. `.env` local contiene configuración
pública y rutas; `.env.auth`, si procede de una instalación anterior, contiene secretos y es privado.

Para detener sin borrar datos:

```bash
docker compose stop
```

Para iniciar otra vez, usa el lanzador o el mismo comando Compose. No extraigas otra release en una
carpeta diferente y la arranques como si fuera la misma instalación. No uses borrado de volúmenes
ni limpieza global de Docker para reparar un error.

## Diagnóstico y recuperación

Desde la carpeta del paquete, ejecuta:

```bash
bash tools/setup/diagnose.sh
```

En PowerShell: `.\tools\setup\diagnose.ps1`. Para conservar el reporte, redirige la salida a un
archivo nuevo, por ejemplo `bash tools/setup/diagnose.sh > diagnostico.json`.
El reporte compartible contiene códigos de
comprobación y acciones; no necesita contraseñas ni logs completos. No compartas `.env.auth`, backups,
cookies, tokens ni capturas con información privada. El diagnóstico no envía nada automáticamente.

Actualizar es explícito, a una versión fija verificada. El inicio normal no busca actualizaciones.
Antes de una actualización hay que terminar o posponer trabajos activos y conservar versión anterior,
configuración, datos y los seis volúmenes. PostgreSQL y Keycloak no se actualizan junto a la aplicación.
Una restauración de base exige su backup consistente y las mismas claves; cambiar una imagen no
revierte migraciones. La recuperación debe ensayarse en un proyecto aislado antes de recomendarla.

Migración desde checkout: usa la misma identidad real del proyecto y rutas absolutas a los datos
anteriores, incluida `.env.auth` cuando exista. Detén la instancia anterior antes de iniciar la nueva;
no inicies dos stacks compartiendo volúmenes. El [contrato](../tools/release/CONTRACT.md) detalla la
preservación. Si la identidad es ambigua o faltan claves, detente y recupera la configuración anterior.

Demo académica local en loopback. No constituye despliegue hospitalario ni validación clínica.
A5 y las correcciones de QA anteriores siguen teniendo sus propios criterios de aceptación.

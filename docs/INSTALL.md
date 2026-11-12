# Usar la demo

## Arranque actual: clonar y usar Docker

Instala **Docker Desktop, Git y Git LFS**. Para probar D3 en una computadora nueva:

```bash
git lfs install
git clone --branch feat/D3-simple-setup --single-branch https://github.com/MasamuneL/Cerberus.git
cd Cerberus
git lfs pull
docker compose up -d --build --wait --wait-timeout 600
```

Abre **http://localhost:8080** e inicia sesión con **demo / demo**. En Windows, selecciona
contenedores Linux. Docker construye la aplicación; no necesitas Python, Node ni uv en el host.
Estos comandos son para una instalación nueva; conserva la configuración y los datos si ya tienes una.

Para detener sin borrar datos: `docker compose stop`. Para iniciar después, desde el mismo clon:
`docker compose up -d --wait --wait-timeout 600`. Si modificaste el código, vuelve a usar `--build`.

Los puertos predeterminados son 8080 (aplicación) y 8081 (Keycloak). La primera compilación y la muestra
requieren red. Mantén la carpeta del clon: contiene Data, storage y modelos persistentes.

## Paquete ZIP: entrega posterior

Clonar el repositorio es la entrada aceptada actualmente. El paquete D3 todavía es candidato: no hay
release D3 publicada ni matriz multiplataforma aprobada. El flujo siguiente describe ese paquete futuro,
que debe superar los gates de [QA D3](qa/D3_EXECUTION.md) antes de recomendarlo a otras personas.
Los lanzadores `start.*` de la raíz corresponden al paquete, no al arranque desde el checkout.

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
puerto por decisión del propietario. Los tres inicializadores con salida 0 son normales.

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
anteriores, incluida `.env.auth` cuando exista. Primero prepara la configuración mientras existan los contenedores anteriores: la identidad real puede
haber sido elegida con `-p` y los puertos mediante variables de aquella shell. El ayudante de migración
del checkout (`uv run python tools/release/migrate.py <checkout-anterior> <paquete>`) obtiene esos valores
reales y no ejecuta servicios. Si faltan contenedores o hay más de una instalación, bloquea la adopción.
Termina trabajos y conserva un backup antes de retirar los contenedores antiguos: desde la carpeta
anterior, con su proyecto real, ejecuta `docker compose down` **sin `-v`**. Este paso conserva los
volúmenes y los archivos de datos, y permite al lanzador nuevo adoptar esa identidad; solo `stop`
deja contenedores con la carpeta antigua y el lanzador los rechazará. No inicies dos stacks compartiendo volúmenes. El [contrato](../tools/release/CONTRACT.md) detalla la
preservación. Si la identidad es ambigua o faltan claves, detente y recupera la configuración anterior.

Demo académica local en loopback. No constituye despliegue hospitalario ni validación clínica.
A5 y las correcciones de QA anteriores siguen teniendo sus propios criterios de aceptación.

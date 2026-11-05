# Archivo y cuarentena · 2026-11-05

La app web no importa el notebook ni su auxiliar Mayavi. Los originales se archivaron sin modificar
sus bytes en `../Cerberus-archivo-2026-11-05/`, dentro de la carpeta BigData. Esta copia local no se
versiona; cualquier colaborador puede recuperar los mismos archivos desde el commit `f395b40`.

| Ruta original | Destino relativo a la carpeta de archivo | Motivo |
|---|---|---|
| `cerberus_eda.py` | `referencia/cerberus_eda.py` | Referencia histórica de fórmulas; no forma parte de la app web |
| `cerberus_mayavi.py` | `referencia/cerberus_mayavi.py` | Auxiliar importado únicamente por el notebook; se conserva junto a él |
| `main.py` (raíz) | `cuarentena/main.py` | Ejemplo inicial que solo imprime «Hello from cerberus!»; la API usa `backend/cerberus_api/main.py` |
| `__marimo__/`, `__pycache__/` (raíz) | `cuarentena/` | Sesiones y cachés del notebook; conservadas por precaución |

Las citas `cerberus_eda.py:<líneas>` del backend y del plan apuntan a este original, sin cambios de numeración.
Se mantienen datos, pesos, resultados, entornos locales, configuraciones del IDE y evidencias de QA.
Los contratos de disco y API no cambian.

## Integridad y recuperación

SHA-256 de los archivos archivados:

```text
267545dec88c3a67ad2150bad9b37e4a211d733f4ff035da8f1d2e695b3e76f9  cerberus_eda.py
f1b23aa7449867fb231d917925b0410812314007298fe84e88eb95dac1c19164  cerberus_mayavi.py
349fa97a38b69e6a68025b5eed356c8192bb12bed568b24ce634c6b798738c69  main.py
```

Desde la raíz de Cerberus, para recuperar el notebook y Mayavi en otra máquina:

```bash
mkdir -p ../Cerberus-archivo-2026-11-05/referencia
git show f395b40:cerberus_eda.py > ../Cerberus-archivo-2026-11-05/referencia/cerberus_eda.py
git show f395b40:cerberus_mayavi.py > ../Cerberus-archivo-2026-11-05/referencia/cerberus_mayavi.py
ln -s ../../Cerberus/Data ../Cerberus-archivo-2026-11-05/referencia/Data
ln -s ../../Cerberus/models ../Cerberus-archivo-2026-11-05/referencia/models
```

Los enlaces a `Data/` y `models/` ya existen en el archivo local. Permiten conservar las rutas relativas
del notebook sin duplicar los datos. Para ejecutarlo, desde Cerberus:

```bash
uv run --group notebook marimo edit ../Cerberus-archivo-2026-11-05/referencia/cerberus_eda.py
uv run --group notebook marimo run ../Cerberus-archivo-2026-11-05/referencia/cerberus_eda.py
uv run --group notebook python ../Cerberus-archivo-2026-11-05/referencia/cerberus_mayavi.py escena.npz
```

Las diez dependencias directas específicas del notebook pasan al grupo opcional `notebook`.
El grupo `runtime` de Docker se conserva. Las dependencias compartidas que necesita el backend
siguen instalándose normalmente; el lockfile conserva las versiones para ambos usos.

## Ramas

Antes de borrar ramas se creó y verificó un bundle Git completo en
`../Cerberus-archivo-2026-11-05/git/cerberus-before-cleanup-2026-11-05.bundle`.
El inventario `cerberus-branches-before-cleanup-2026-11-05.json`, en la misma carpeta, conserva los
nombres y SHA completos. El bundle contiene el historial Git, no los binarios de Git LFS.

Solo se eliminan ramas cuyo tip es ancestro de `origin/main`: inicialmente 30 locales y 29 remotas.
Durante la limpieza otra sesión integró A0/A1; ambas ramas también se respaldaron y eliminaron al dejar
de estar en uso. Total: **32 ramas locales y 31 remotas eliminadas**.
Su respaldo adicional es `git/cerberus-auth-before-cleanup-2026-11-05.bundle`, con el inventario
`git/cerberus-auth-branch-2026-11-05.json` y `git/cerberus-auth-A1-branch-2026-11-05.json`.
Se conservan `main`, `feat/A2-oidc-sessions` (worktree activo) y la rama de limpieza.
Los borradores remotos `wip/d2-docker` y `wip/ux-14` conservan commits propios: quedan en cuarentena
y no se eliminan por no estar integrados, aunque la funcionalidad que proponían ya exista.

Ejemplos de recuperación desde Cerberus:

```bash
git fetch ../Cerberus-archivo-2026-11-05/git/cerberus-before-cleanup-2026-11-05.bundle refs/heads/feat/B3-volumetry:refs/heads/feat/B3-volumetry
git push origin feat/B3-volumetry  # solo si también se necesita restaurar la rama remota
```

## Graphify

El entorno no tenía CLI ni grafo previo. Se usa Graphify 0.9.102 mediante `uv run --no-project --with`,
sin añadirlo a las dependencias de Cerberus. `.graphifyignore` excluye datos, modelos, dependencias,
cachés y resultados. Los artefactos locales se generan en `graphify-out/`, ignorado por Git.

```bash
uv run --no-project --with graphifyy==0.9.102 graphify extract . --code-only --no-cluster --max-workers 2
uv run --no-project --with graphifyy==0.9.102 graphify update . --force --no-cluster
uv run --no-project --with graphifyy==0.9.102 graphify cluster-only . --no-label
```

La extracción usa AST local y omite documentos y análisis semántico por LLM. El informe y el HTML
se regeneran después de cada bloque importante. Este grafo ayuda a revisar dependencias, pero no
demuestra por sí solo que un archivo carezca de usos dinámicos.

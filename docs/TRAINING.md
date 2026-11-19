# Entrenamiento y fine-tuning (CLI `cerberus_training`)

Guía operativa del pipeline descrito en [`PLAN_PIPELINE_FINETUNING.md`](PLAN_PIPELINE_FINETUNING.md).
Este documento crece con cada ticket FT; aquí se documenta lo que existe hoy.

## Estado

| Ticket | Contenido | Estado |
|---|---|---|
| FT0 | Paquete, configuración JSON estricta, CLI base, entorno CUDA fijado, comprobación de dispositivo | implementado |
| FT1 | `inventory`, `split` | pendiente |
| FT2 | `prepare`, `preflight` | pendiente |
| FT3 | `train` (incluye `--dry-run` y `--resume`) | pendiente |
| FT4 | `evaluate`, `export` | pendiente |
| FT5 | `smoke --synthetic` y manual completo | pendiente |

Con FT0 solo funcionan `validate` y `device`. El resto de los subcomandos existe para que `--help` muestre la
interfaz prevista, valida la configuración si se pasa `--config` y termina con código 3 y un mensaje
`pendiente de FTn`. **No hay entrenamiento, evaluación ni modelo adaptado todavía**, y no se ha medido ninguna
duración ni consumo de recursos.

## Códigos de salida

| Código | Significado |
|---|---|
| 0 | correcto |
| 1 | `device --require-cuda` sin CUDA disponible |
| 2 | uso incorrecto de argumentos o configuración inválida/ilegible |
| 3 | subcomando todavía no implementado |

## Uso con el entorno normal (CPU)

El entorno de la app (`uv sync`) instala el paquete en modo editable y sirve para `--help`, validar
configuraciones y ejecutar los tests. No necesita red ni GPU y no importa torch ni MONAI al arrancar la CLI.

```bash
uv sync
uv run python -m cerberus_training --help
uv run python -m cerberus_training train --help
uv run python -m cerberus_training validate --config configs/training/gtv_binary.json
uv run python -m cerberus_training device
```

## Configuración

El ejemplo versionado es [`configs/training/gtv_binary.json`](../configs/training/gtv_binary.json); el esquema
está en `backend/cerberus_training/config.py` (pydantic, `extra="forbid"`, `schema_version` obligatorio).
Una clave desconocida, una proporción de split que no suma 1, un valor no positivo o un SHA-256 mal formado
son errores, nunca se ignoran. Puntos a tener en cuenta:

- `paths.data_root` es el dataset externo, de solo lectura; todo lo generado va bajo `paths.work_dir`
  (por defecto `storage/training/`, ignorado por Git). Las rutas relativas se resuelven contra la raíz del repo.
- `weights.path` y `weights.sha256` son obligatorios y nunca se descargan en `train`. El valor del ejemplo es un
  **marcador de posición** (64 ceros): calcule el SHA-256 real de su `model.pt` con `shasum -a 256` antes de
  entrenar y sustitúyalo; las etapas posteriores rechazarán un hash que no coincida.
- Perfil de canales estricto `[T1c, T1, T2, FLAIR]`: T1 prefiere `t1eg` y luego `t1tse`; T2 exige `t2tse`.
  `t2star_policy` solo admite `disabled`: T2* no sustituye a T2.
- Las rutas `data_root`, `work_dir` y `weights.path` no pueden ser vacías ni `.`, y `work_dir` no puede coincidir
  con `data_root` ni estar dentro o contenerlo (tras resolver y normalizar), para no escribir sobre el dataset.
- Las semillas (`split.seed` y `seeds.*`) van de 0 a 2^32 - 1.
- `preprocess.patch_size` debe ser múltiplo de 8 en cada eje: SegResNet realiza 3 submuestreos (factor 2^3).
- El JSON se valida en modo estricto, sin coerciones: `true` no vale como entero, `"1e-4"` no vale como número,
  `96.0` no vale como tamaño de parche. El archivo debe ser UTF-8.
- `training.device` es `cpu` o `cuda`; `amp` exige `cuda`. Pedir `cuda` sin GPU fallará en `train`
  (FT3), no se degrada en silencio. El ejemplo usa `cuda` + AMP por ser el uso previsto.
- Los hiperparámetros por defecto (parche 96³, batch 1, acumulación 4, AdamW 1e-4, 100 épocas, paciencia 15)
  son un punto de partida, no un óptimo validado. El tamaño final de parche y el hardware necesario se
  decidirán con un piloto futuro.

`validate --write-resolved RUTA` guarda la configuración con rutas absolutas (nunca sobrescribe un archivo
existente); es el formato que cada run archivará como `config.resolved.json`.

## Entorno CUDA independiente (`training-env/`)

Las ruedas de torch de la app apuntan al índice CPU en Linux (`pyproject.toml` raíz) y no deben cambiar.
Para entrenar en GPU se usa un proyecto `uv` aparte, [`training-env/`](../training-env/pyproject.toml), con su
propio `uv.lock` versionado:

- Depende del paquete `cerberus` por ruta (editable), de modo que ejecuta exactamente el mismo código.
- Fija `torch==2.14.1` y, en Linux y Windows, lo resuelve desde el índice `https://download.pytorch.org/whl/cu126`
  (`2.14.1+cu126`). En macOS no existe CUDA y se resuelve la rueda normal de PyPI.
- Un `override-dependencies` sustituye el requisito de torch del proyecto raíz (que lo dirigiría al índice CPU).
- No toca el `uv.lock` ni el `.venv/` de la app: su entorno virtual vive en `training-env/.venv/` (ignorado por Git).

Versiones elegidas el 2026-11-19: el índice `cu126` ofrece `2.14.1+cu126` y `cu130` ofrece `2.14.1+cu130`; `cu128`
no publica esa versión de torch. Se eligió **cu126** por requerir un controlador NVIDIA menos reciente. Las ruedas
de torch incluyen las bibliotecas CUDA, así que solo hace falta el controlador NVIDIA del sistema (consulte la
tabla de compatibilidad de NVIDIA para cu126). Si su controlador es reciente y prefiere `cu130`, cambie el nombre
y la URL del índice en `training-env/pyproject.toml` y regenere el lock.

```bash
# Instalar (reproducible; --locked falla si el lock no corresponde a los pyproject, en vez de ignorar la deriva)
uv sync --project training-env --locked

# Comprobar el dispositivo desde la raíz del repo (las rutas relativas de la config se resuelven contra el repo)
uv run --project training-env python -m cerberus_training device
uv run --project training-env python -m cerberus_training device --require-cuda   # código 1 si no hay GPU

# Ejecutar la CLI con CUDA
uv run --project training-env python -m cerberus_training validate --config configs/training/gtv_binary.json
```

`--locked` (y no `--frozen`) es deliberado: `training-env` depende del `pyproject.toml` raíz por ruta, así que
añadir o cambiar una dependencia de la app deja su lock desactualizado. `--frozen` instalaría igualmente el lock
viejo sin avisar; `--locked` aborta y obliga a ejecutar `uv lock --project training-env` y revisar el cambio.

**Advertencia sobre GPU recientes.** Las ruedas `cu126` solo incluyen kernels para ciertas arquitecturas (de
`sm_50` a `sm_90`, según la rueda); una GPU más nueva, como las RTX 50xx (Blackwell, `sm_120`), puede no
estar incluida y torch fallaría o avisaría al usarla. Ejecute `device` tras instalar: imprime la capability de
cada GPU y las arquitecturas compiladas, y añade un `AVISO` si la capability no está en la lista. En ese caso
cambie a un índice más nuevo (por ejemplo `cu130`, si ofrece la misma versión de torch) y regenere el lock.

Para regenerar el lock tras cambiar versiones (requiere red): `uv lock --project training-env`. Verifique
después con `uv lock --check --project training-env`.

`device` imprime versión de Python, plataforma, versión de torch, build CUDA, disponibilidad de CUDA, cuDNN,
bf16, nombre y capability de cada GPU, arquitecturas compiladas en la rueda y avisos; con `--json` emite el mismo informe en JSON. Nunca falla en una máquina sin GPU ni sin
torch (devuelve 0 salvo con `--require-cuda`). En el entorno de la app informará `torch con ruedas CPU`.

Nota: la instalación del entorno CUDA no se ha ejecutado en una máquina con GPU durante FT0 (el desarrollo se hizo
en macOS sin CUDA); solo se resolvió y fijó el lock. La primera comprobación real con GPU queda para el piloto.

## Tests

```bash
uv run pytest -q backend/tests/test_training_config.py backend/tests/test_training_cli.py
```

Cubren el esquema, la CLI y la ausencia de imports de torch/MONAI. No usan red, datos reales ni GPU.

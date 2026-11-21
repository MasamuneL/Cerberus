# Informe de espacios del atlas de Brodmann y registro a MNI152

**Ticket:** `ATLAS0` · **Fecha:** 2026-11-21 · **Alcance:** diagnóstico técnico, medición sobre los 8 estudios de `Data/` y comparación de opciones (sin cambios de código en este ticket).

---

## Resumen ejecutivo

En ATLAS0, el backend registraba la T1 del paciente contra la plantilla **MNI152 (`mni_icbm152_t1_tal_nlin_sym_09a`, 1 mm)** mediante ANTs SyN, y proyectaba directamente sobre el paciente las etiquetas de **`fetch_atlas_talairach("ba")`** de Nilearn (`0.14.1`), cuyo espacio declarado es **Talairach** (`template="Talairach"`, `sform_code=3`, `qform_code=3`), **sin conversión entre espacios**.

Al aplicar la transformación afín de **Lancaster et al. (2007)** (`icbm_other2tal`) sobre el mismo registro por estudio (8/8 estudios de `Data/`):

- Las áreas de Brodmann (BA) se desplazan en promedio **4.76–5.22 mm** (media global **4.99 mm**, mediana **5.08 mm**, rango **[0.56, 13.40] mm**), aproximadamente **la mitad del margen de proximidad `MARGIN_MM = 10.0 mm`**.
- Los picos corticales superan el margen completo en varios estudios (hasta **13.40 mm** en BA11 en `005/t1` y **11.90 mm** en BA25 en `002/t0`).
- **8 de 8 estudios** cambian las áreas reportadas o su clasificación (`Afectada` ↔ `Cercana`): en total **6** áreas aparecen, **29** desaparecen y **20** cambian de categoría. En **7 de 8 estudios** estos cambios involucran **áreas elocuentes** (BA1, BA2, BA3, BA6, BA17, BA22, BA40, BA41, núcleos talámicos y troncoencefálicos).

**Recomendación:** **Opción A** (aplicar la transformación afín de Lancaster `icbm_other2tal` / `tal2icbm_other`). Introduce la conversión explícita entre espacios con un desplazamiento medido de ~5 mm, conserva intactas las 71 etiquetas (42 BA + 29 subcorticales) de `area_functions.json` y mantiene estables los contratos §6/§7.

---

## 1. Atlas cargado por el backend (función, versión y espacio declarado)

- **Llamada en Cerberus:** `backend/cerberus_api/atlas.py:100-110` (`fetch_atlas`). En las líneas `105-107` importa `nilearn.datasets.fetch_atlas_talairach` y solicita el nivel `"ba"` en `models_dir / "atlas"`:
  ```python
  from nilearn.datasets import fetch_atlas_talairach
  atlas = fetch_atlas_talairach("ba", data_dir=models_dir / "atlas", verbose=0)
  ```
- **Implementación en el código instalado (`nilearn 0.14.1`):**
  - `fetch_atlas_talairach` está definida en `.venv/lib/python3.11/site-packages/nilearn/datasets/atlas.py:2203-2278`.
  - Si no está en caché, `_download_talairach` (`.venv/lib/python3.11/site-packages/nilearn/datasets/atlas.py:2171-2199`) descarga `https://www.talairach.org/talairach.nii` (línea `2175`, con respaldo en OSF `https://osf.io/x4b2w/download` ante `SSLError`, línea `2183`).
  - `_separate_talairach_levels` (`.venv/lib/python3.11/site-packages/nilearn/datasets/atlas.py:2132-2169`) separa los 5 niveles jerárquicos (`hemisphere`, `lobe`, `gyrus`, `tissue`, `ba`) leyendo la extensión de cabecera del NIfTI y guarda `ba.nii.gz` (`uint8`) y `ba-labels.json` en `models/atlas/talairach_atlas/`.
- **Versión y procedencia:** `talairach.nii` no lleva número de versión semántica en el archivo; proviene del atlas digitalizado del **Talairach Daemon / Talairach Labels** (Lancaster et al., 1997, 2000) derivado del atlas estereotáxico de **Talairach y Tournoux (1988)** (`.venv/lib/python3.11/site-packages/nilearn/datasets/description/talairach_atlas.rst:13-36`). La descripción de Nilearn deja la licencia como `unknown` (`talairach_atlas.rst:55`); el sitio oficial publica el archivo de etiquetas, pide citar Lancaster et al. (1997, 2000) para el software usado en investigación y reserva los derechos del Research Imaging Institute. La ficha del proyecto en NITRC publica los términos del Talairach Daemon, con restricciones de uso y redistribución. [Talairach Software, sección «Talairach References»](https://www.talairach.org/), [Talairach Daemon en NITRC, sección «License»](https://www.nitrc.org/projects/tal-daemon/) (consultadas el 2026-11-21).
- **Espacio declarado y geometría verificada en disco:**
  - `fetch_atlas_talairach` devuelve explícitamente `template="Talairach"` y `atlas_type="deterministic"` (`.venv/lib/python3.11/site-packages/nilearn/datasets/atlas.py:2255, 2271-2278`).
  - Inspección directa del archivo en caché (`models/atlas/talairach_atlas/ba.nii.gz`) con NiBabel:
    - Forma: `(141, 172, 110)` vóxeles, resolución `1.0 × 1.0 × 1.0 mm`.
    - Códigos NIfTI-1: `sform_code = 3` y `qform_code = 3` (`NIFTI_XFORM_TALAIRACH`), `descrip = "Talairach Image... "`.
    - Afín (`sform` / `qform`): `diag(1, 1, 1, 1)` con traslación `(-70, -102, -42)` mm → rango RAS: `x ∈ [-70, +70]`, `y ∈ [-102, +69]`, `z ∈ [-42, +67]` mm (caja estereotáxica clásica de Talairach).
    - Etiquetas: **72 entradas** (`ba-labels.json`), `"Background"` en el índice `0` y **71 regiones** anatómicas: **42 áreas de Brodmann** (`Brodmann area 1..47`) y **29 estructuras subcorticales** (`backend/tests/test_area_kb.py:11-50`).

---

## 2. Plantilla MNI152 y discrepancia observada en ATLAS0

Búsqueda en `backend/cerberus_api` (`grep -rn "MNI\|mni" backend/cerberus_api`): las referencias activas del registro viven en `backend/cerberus_api/atlas.py` (además de mensajes/comentarios en `config.py:22`, `areas.py:3`, `display.py:33`, `routers/studies.py:259` y `worker.py:114`).

- **Plantilla usada (`backend/cerberus_api/atlas.py:113-122`, `fetch_template`):**
  ```python
  from nilearn.datasets import load_mni152_brain_mask, load_mni152_template
  return load_mni152_template(resolution=1), load_mni152_brain_mask(resolution=1)
  ```
- **Definición en el código instalado (`nilearn 0.14.1`):**
  - `.venv/lib/python3.11/site-packages/nilearn/datasets/struct.py:46-50`:
    `MNI152_FILE_PATH = PACKAGE_DIRECTORY / "data" / "mni_icbm152_t1_tal_nlin_sym_09a_converted.nii.gz"`.
  - `load_mni152_template(resolution=1)` (`.venv/lib/python3.11/site-packages/nilearn/datasets/struct.py:196-251`) carga ese archivo empaquetado (línea `235`) y normaliza intensidades a `[0, 1]` (línea `241`); `load_mni152_brain_mask(resolution=1)` (`struct.py:368-411`) lo umbraliza a `> 0.2` (líneas `407-408`).
  - Inspección directa del NIfTI empaquetado: forma `(197, 233, 189)`, resolución `1.0 × 1.0 × 1.0 mm`, `sform_code = 2` (`NIFTI_XFORM_ALIGNED_ANAT`), `qform_code = 0`, afín `diag(1, 1, 1, 1)` con traslación `(-98, -134, -72)` mm y **simetría exacta izquierda-derecha** (`d == d[::-1, :, :]`, diferencia máxima `0.0`). Corresponde a la plantilla **ICBM 152 2009a no lineal simétrica** (`mni_icbm152_nlin_sym_09a`, Fonov et al., 2009, 2011; nota: `.venv/lib/python3.11/site-packages/nilearn/datasets/description/icbm152_2009.rst:9` escribe erróneamente «asymmetrical», aunque la URL fuente de la línea `61` y el archivo en `struct.py:49` son `sym_09a`).
- **Flujo de registro y proyección en `backend/cerberus_api/atlas.py` al evaluar ATLAS0:**
  1. `_register()` (`atlas.py:221-293`) selecciona la T1 móvil (`t1eg → t1tse → t1gd`, línea `39`), la enmascara con `brain_mask`, excluye el GTV dilatado `GTV_MARGIN_MM = 5.0 mm` del costo (`moving_mask`, líneas `44`, `259-266`, `278-279`) y registra hacia la plantilla MNI152 enmascarada (`fixed`, líneas `238-249`) con `ants.registration(..., type_of_transform="SyN", ...)` (`atlas.py:272-282`). En modo `full`, la T1 móvil se remuestrea a `1.5 mm` y la plantilla queda a `1.0 mm`; en modo `fast`, ambas usan `2.0 mm` (`atlas.py:68-73`, `239-245`).
  2. `map_atlas()` (`atlas.py:301-374`) separa primero el atlas Talairach por hemisferios según su coordenada `x >= 0` (`split_hemispheres` en líneas `125-157` y `328`), y luego llama a `ants.apply_transforms` (`atlas.py:341-347`) con `transformlist=inv` (las inversas paciente → MNI152 guardadas en `mni/`) e `interpolator="genericLabel"`.
  3. **Dónde ocurre la discrepancia:** `inv` lleva coordenadas físicas del paciente al espacio **MNI152 (ICBM152 2009a)**, pero `ants.apply_transforms` lee los vóxeles de `split_img` usando directamente su cabecera **Talairach** (`sform_code=3`). Asume tácitamente $\mathbf{p}_{\text{Tal}} = \mathbf{p}_{\text{MNI152}}$ (identidad). Esta suposición ya figuraba como hallazgo pendiente en `README.md:526-531` y `docs/PROGRESS.md:788-789` (`CP-047`), mientras `docs/PLAN_MVP.md:604` describe erróneamente el atlas como «espacio MNI».

---

## 3. Medición con la transformación de Lancaster en los 8 estudios

### 3.1 Transformación y matriz aplicada

Se utilizó la transformación afín de **Lancaster et al. (2007)**, *"Bias between MNI and Talairach coordinates analyzed using the ICBM-152 brain template"*, *Human Brain Mapping*, 28(11): 1194–1205.

Dado que el registro de Cerberus utiliza **ANTs SyN** sobre la plantilla ICBM152 (no SPM ni FSL FLIRT), se emplea la matriz agrupada oficial **`icbm_other2tal`** de BrainMap (`https://www.brainmap.org/icbm2tal/icbm_other2tal.m`, 2007-03-14; recomendada por Lancaster et al. para software distinto de SPM y FSL), que convierte coordenadas RAS (mm) de espacio ICBM/MNI a espacio Talairach:

$$
M_{\text{icbm\_other2tal}} =
\begin{bmatrix}
 0.9357 &  0.0029 & -0.0072 & -1.0423 \\
-0.0065 &  0.9396 & -0.0726 & -1.3940 \\
 0.0103 &  0.0752 &  0.8967 &  3.6475 \\
 0.0000 &  0.0000 &  0.0000 &  1.0000
\end{bmatrix}
$$

Su inversa $M_{\text{tal2icbm\_other}} = M_{\text{icbm\_other2tal}}^{-1}$ (`tal2icbm_other.m`) lleva coordenadas Talairach → MNI152:

$$
M_{\text{tal2icbm\_other}} \approx
\begin{bmatrix}
 1.068600 & -0.003959 &  0.008260 &  1.078156 \\
 0.006402 &  1.057407 &  0.085663 &  1.168244 \\
-0.012811 & -0.088632 &  1.107921 & -4.178049 \\
 0.000000 &  0.000000 &  0.000000 &  1.000000
\end{bmatrix}
$$

> **Nota técnica de implementación (ANTs/ITK):** `ba.nii.gz` no puede guardarse simplemente con afín $M_{\text{tal2icbm}} A_{\text{tal}}$ para pasarlo a `ants.image_read`, porque ITK rechaza cabeceras con cizallamiento (`ITK only supports orthonormal direction cosines`). En la medición se convirtió $M_{\text{icbm\_other2tal}}$ a coordenadas LPS (`ras2lps @ M @ ras2lps`, donde `ras2lps = diag(-1, -1, 1, 1)`) en un `AffineTransform` de ANTs y se compuso directamente en `ants.apply_transforms(..., transformlist=[*inv, icbm_other2tal.mat], whichtoinvert=[*which_to_invert(inv), False], interpolator="genericLabel")`. Esto conserva una **única interpolación** `genericLabel` y preserva el corte hemisférico en la línea media original de Talairach (`split_hemispheres` previo).
>
> **Verificación en la plantilla MNI152 de 1 mm:** el revisor comparó NiBabel (`resample_from_to(..., order=0)` con `tal2icbm` en la cabecera) y ANTs (afín LPS con `nearestNeighbor`). Los centroides se separaron **0.031 mm** de media (máximo **0.374 mm**) y difirió el **0.28 %** de la unión de vóxeles etiquetados. Con `genericLabel` en ANTs las cifras fueron **0.39 mm**, **2.71 mm** y **6.70 %**, respectivamente. En la medición original de ATLAS0 en MNI152 (71 regiones), la aplicación de Lancaster desplazó los centroides en promedio **4.47 mm** (mediana **4.41 mm**, rango **[0.85, 10.27] mm**).

`icbm_other2tal` se ajustó agrupando datos de SPM2 y FSL. BrainMap documenta validación para las rutas SPM2 y FSL y pide interpretar con cautela las demás. La afín agrupada carece de validación específica para ICBM152 2009a no lineal simétrica. [Método y nota de validación de BrainMap](https://www.brainmap.org/icbm2tal/).

### 3.2 Control de no determinismo (`REG1`) y reproducibilidad

En ATLAS0, el registro ANTs `full` con múltiples hilos variaba entre corridas. REG1 estaba en curso. Para **aislar exclusivamente el efecto de la transformación de Lancaster** sin mezclar variabilidad entre registros distintos:

1. En **7 de los 8 estudios** (`001/t0`, `002/t0`, `003/t0`, `003/t1`, `005/t0`, `005/t1`, `005/t2`) se reutilizaron **en solo lectura** las transformaciones `mni/pat2mni_0GenericAffine.mat` y `mni/pat2mni_1InverseWarp.nii.gz` ya almacenadas en `storage/results/<paciente>/<tiempo>/mni/`. Se verificó además que reproyectar sin Lancaster sobre esas transformaciones da **0 vóxeles de diferencia** frente a `brodmann.nii.gz` y áreas idénticas a `brodmann.json` en los 7 casos.
2. En **`004/t0`** (que no tenía carpeta `mni/` ni `brodmann.*` en `storage/`), se ejecutó `atlas.map_atlas(..., mode="full")` **una sola vez** en almacenamiento temporal y se aplicó Lancaster sobre ese mismo registro.

- **Medición reproducible:** [`tools/eval/atlas_lancaster.py`](../tools/eval/atlas_lancaster.py) aplica el mismo control con los registros de REG1 y los mapas de ATLAS1. La tabla histórica de ATLAS0 corresponde a los registros enumerados arriba. El comando con los resultados de REG1 está en §6.
- **Carga del sistema durante la tanda de ATLAS0 (`uptime`):** inicio `load averages: 11.67 13.85 11.26`, fin `load averages: 3.71 5.48 7.15`.

### 3.3 Resultados por estudio (`MARGIN_MM = 10.0 mm`, `backend/cerberus_api/areas.py:30`)

En la tabla: **Afect.** = áreas con solapamiento GTV (`overlap_gtv_cm3 > 0`); **Cerc.** = áreas sin solapamiento a distancia `≤ 10.0 mm`; **Total** = Afect. + Cerc. El desplazamiento de centroides **BA** mide únicamente las etiquetas `Brodmann area *` (por hemisferio) presentes en ambos mapas en el espacio físico RAS del paciente; **Todas** incluye también las 29 estructuras subcorticales.

| Estudio | Reg. | Sin Lancaster (Afect. / Cerc. / Total) | Con Lancaster (Afect. / Cerc. / Total) | Aparecen | Desaparecen | Cambian cat. | Desplaz. centroides BA (media ± DE · med · mín–máx mm) | Desplaz. Todas (media mm) |
|---|---|---|---|---|---|---|---|---|
| `001/t0` | `mni/` (`t1eg`) | 8 / 15 / 23 | 7 / 15 / 22 | 0 | 1 | 1 | **4.76** ± 1.81 · 4.75 · 1.35–9.37 (`n=84`) | 3.92 (`n=142`) |
| `002/t0` | `mni/` (`t1gd`) | 16 / 32 / 48 | 16 / 26 / 42 | 0 | 6 | 2 | **5.22** ± 1.99 · 5.20 · 1.40–11.90 (`n=83`) | 4.58 (`n=141`) |
| `003/t0` | `mni/` (`t1gd`) | 45 / 34 / 79 | 42 / 31 / 73 | 1 | 7 | 5 | **4.89** ± 1.58 · 5.07 · 1.34–8.67 (`n=84`) | 4.14 (`n=142`) |
| `003/t1` | `mni/` (`t1eg`) | 40 / 36 / 76 | 39 / 28 / 67 | 0 | 9 | 1 | **4.98** ± 1.70 · 5.03 · 1.27–9.04 (`n=84`) | 4.17 (`n=142`) |
| `004/t0` | Nuevo (`t1eg`) | 19 / 21 / 40 | 18 / 23 / 41 | 2 | 1 | 1 | **5.05** ± 1.63 · 5.17 · 1.14–8.73 (`n=84`) | 4.24 (`n=142`) |
| `005/t0` | `mni/` (`t1eg`) | 34 / 24 / 58 | 34 / 26 / 60 | 2 | 0 | 4 | **5.18** ± 2.09 · 5.08 · 0.56–10.08 (`n=82`) | 4.39 (`n=140`) |
| `005/t1` | `mni/` (`t1tse`) | 35 / 26 / 61 | 37 / 22 / 59 | 1 | 3 | 4 | **5.01** ± 1.97 · 5.11 · 1.64–13.40 (`n=83`) | 4.42 (`n=141`) |
| `005/t2` | `mni/` (`t1tse`) | 33 / 23 / 56 | 35 / 19 / 54 | 0 | 2 | 2 | **4.81** ± 1.77 · 4.84 · 1.16–10.46 (`n=82`) | 4.34 (`n=140`) |
| **Resumen** | **8/8** | — | — | **6** | **29** | **20** | **Media global: 4.99 mm · Máx: 13.40 mm** | **Media global: 4.28 mm** |

### 3.4 Detalle por estudio de áreas que aparecen, desaparecen o cambian de categoría

Se marcan con **`[E]`** las regiones etiquetadas como `eloquent: true` en `backend/cerberus_api/data/area_functions.json` (usadas en el semáforo de «Funciones en riesgo», `docs/PLAN_MVP.md:689-692`).

- **`001/t0`** (BA máx: BA38 der. `9.37 mm`):
  - **Aparecen (0):** —
  - **Desaparecen (1):** `Brodmann area 6` izq. **`[E]`** (antes cercana a `8.9 mm`).
  - **Cambian de categoría (1):** `Brodmann area 5` izq. (`afectada` `0.08 cm³` → `cercana` `0.5 mm`).
- **`002/t0`** (BA máx: BA25 der. `11.90 mm`):
  - **Aparecen (0):** —
  - **Desaparecen (6):** `Brodmann area 1` der. **`[E]`** (`9.2 mm`), `Ventral Posterior Lateral Nucleus` der. **`[E]`** (`8.4 mm`), `Ventral Anterior Nucleus` der. **`[E]`** (`8.5 mm`), `Brodmann area 33` izq. (`8.7 mm`), `Putamen` der. (`9.3 mm`), `Brodmann area 9` der. (`8.5 mm`).
  - **Cambian de categoría (2):** `Brodmann area 7` izq. (`cercana` `0.5 mm` → `afectada` `0.01 cm³`); `Caudate Body` der. (`afectada` `0.03 cm³` → `cercana` `0.5 mm`).
- **`003/t0`** (BA máx: BA38 der. `8.67 mm`):
  - **Aparecen (1):** `Brodmann area 29` izq. (`cercana` `9.4 mm`).
  - **Desaparecen (7):** `Brodmann area 22` der. **`[E]`** (`9.8 mm`), `Brodmann area 6` der. **`[E]`** (`9.8 mm`), `Brodmann area 2` der. **`[E]`** (`9.7 mm`), `Putamen` izq. (`9.4 mm`), `Brodmann area 20` der. (`9.4 mm`), `Brodmann area 47` der. (`9.4 mm`), `Brodmann area 37` der. (`8.5 mm`).
  - **Cambian de categoría (5):** `Ventral Lateral Nucleus` izq. **`[E]`** (`cercana` `1.4 mm` → `afectada` `0.01 cm³`); `Red Nucleus` izq. **`[E]`** (`afectada` `0.03 cm³` → `cercana` `0.5 mm`); `Brodmann area 25` izq. (`afectada` `0.0003 cm³` → `cercana` `1.2 mm`); `Amygdala` der. (`afectada` `0.02 cm³` → `cercana` `2.1 mm`); `Brodmann area 25` der. (`afectada` `0.01 cm³` → `cercana` `0.5 mm`).
- **`003/t1`** (BA máx: BA38 der. `9.04 mm`):
  - **Aparecen (0):** —
  - **Desaparecen (9):** `Brodmann area 22` der. **`[E]`** (`8.4 mm`), `Brodmann area 6` der. **`[E]`** (`8.1 mm`), `Brodmann area 3` der. **`[E]`** (`8.3 mm`), `Medial Globus Pallidus` izq. (`8.7 mm`), `Brodmann area 38` der. (`8.0 mm`), `Brodmann area 21` der. (`6.7 mm`), `Brodmann area 47` der. (`8.8 mm`), `Brodmann area 37` der. (`7.7 mm`), `Brodmann area 19` der. (`9.8 mm`).
  - **Cambian de categoría (1):** `Brodmann area 41` der. **`[E]`** (`afectada` `0.01 cm³` → `cercana` `2.2 mm`).
- **`004/t0`** (BA máx: BA38 der. `8.73 mm`):
  - **Aparecen (2):** `Brodmann area 9` izq. (`cercana` `8.1 mm`), `Brodmann area 8` der. (`cercana` `8.5 mm`).
  - **Desaparecen (1):** `Brodmann area 21` der. (`cercana` `7.6 mm`).
  - **Cambian de categoría (1):** `Brodmann area 34` der. (`afectada` `0.003 cm³` → `cercana` `3.0 mm`).
- **`005/t0`** (BA máx: BA34 der. `10.08 mm`):
  - **Aparecen (2):** `Red Nucleus` izq. **`[E]`** (`cercana` `9.6 mm`), `Anterior Commissure` der. (`cercana` `9.3 mm`).
  - **Desaparecen (0):** —
  - **Cambian de categoría (4):** `Mammillary Body` der. **`[E]`** (`cercana` `1.5 mm` → `afectada` `0.01 cm³`); `Lateral Posterior Nucleus` der. **`[E]`** (`cercana` `2.1 mm` → `afectada` `0.02 cm³`); `Brodmann area 23` der. (`afectada` `0.0003 cm³` → `cercana` `1.0 mm`); `Brodmann area 31` der. (`afectada` `0.03 cm³` → `cercana` `0.5 mm`).
- **`005/t1`** (BA máx: BA11 izq. `13.40 mm`):
  - **Aparecen (1):** `Caudate Head` der. (`cercana` `9.9 mm`).
  - **Desaparecen (3):** `Brodmann area 40` der. **`[E]`** (`7.3 mm`), `Brodmann area 31` izq. (`9.4 mm`), `Brodmann area 43` der. (`9.7 mm`).
  - **Cambian de categoría (4):** `Subthalamic Nucleus` der. **`[E]`** (`cercana` `1.7 mm` → `afectada` `0.01 cm³`); `Ventral Lateral Nucleus` der. **`[E]`** (`cercana` `2.9 mm` → `afectada` `0.0003 cm³`); `Lateral Posterior Nucleus` der. **`[E]`** (`cercana` `1.0 mm` → `afectada` `0.002 cm³`); `Brodmann area 23` der. (`afectada` `0.0003 cm³` → `cercana` `1.0 mm`).
- **`005/t2`** (BA máx: BA47 der. `10.46 mm`):
  - **Aparecen (0):** —
  - **Desaparecen (2):** `Brodmann area 17` der. **`[E]`** (`9.6 mm`), `Brodmann area 7` der. (`9.7 mm`).
  - **Cambian de categoría (2):** `Mammillary Body` der. **`[E]`** (`cercana` `1.1 mm` → `afectada` `0.01 cm³`); `Ventral Lateral Nucleus` der. **`[E]`** (`cercana` `4.7 mm` → `afectada` `0.0003 cm³`).

**Observación física:** sin la corrección de Lancaster, el cerebro del atlas Talairach es ~6–11 % más pequeño por eje y está rotado/desplazado respecto a MNI152; al expandirlo hacia MNI152 (`tal2icbm`), varias regiones corticales periféricas se desplazan fuera del margen de 10 mm (explicando las 29 salidas frente a 6 entradas), mientras que en el lóbulo temporal/frontal basal y regiones profundas cambia qué borde toca el GTV.

---

## 4. Evaluación de opciones (A, B y C)

### Opción A · Aplicar la transformación afín de Lancaster (`icbm_other2tal`)

- **Pros:**
  - Introduce la conversión de coordenadas de Lancaster et al. (2007). En los ocho estudios de ATLAS0, el desplazamiento medio medido es de **4.99 mm** (hasta **13.40 mm**).
  - Conserva **exactamente las 71 etiquetas** (42 BA + 29 subcorticales), por lo que `backend/cerberus_api/data/area_functions.json` (1,384 líneas), `area_kb.py`, `test_area_kb.py` y los contratos §6 y §7 permanecen intactos.
  - No requiere descargas nuevas, dependencias nuevas ni redistribuir archivos de terceros dentro del repositorio.
  - Sobrecoste en tiempo de ejecución prácticamente nulo (~0 s adicionales frente a `ants.registration`).
- **Contras:**
  - Es una afín global de 12 parámetros aplicada a un atlas determinista derivado de un único cerebro post mortem (Talairach y Tournoux, 1988). El atlas carece de variabilidad citoarquitectónica interindividual. La aplicación de `icbm_other2tal` a ICBM152 2009a no lineal simétrica requiere cautela según el alcance de la validación descrito en §3.1.
  - Invalida el `brodmann.nii.gz` / `brodmann.json` precalculado en `storage/results/` (pero **no** necesariamente la caché `mni/` del registro ANTs si el `AffineTransform` de Lancaster se aplica después de `inv` en `map_atlas`, ahorrando volver a registrar).
- **Coste:** **Muy bajo** (~20–40 líneas en `backend/cerberus_api/atlas.py`, tests unitarios, actualización de texto en `README.md` y `docs/PLAN_MVP.md` §13; sin cambios de frontend salvo opcionalmente indicar «Talairach-Brodmann → MNI152 (Lancaster 2007)» en el texto `registration`).
- **Licencia:** BrainMap publica `icbm_other2tal`. Nilearn descarga el atlas al preparar su caché. Los términos y la atribución del Talairach Daemon se documentan en §1. [Archivo oficial de BrainMap](https://www.brainmap.org/icbm2tal/icbm_other2tal.m).

### Opción B · Usar un atlas de Brodmann nativo en MNI152

Se revisaron los cuatro candidatos principales en espacio MNI:

| Candidato | Espacio nativo | Cobertura frente a las 71 regiones de Cerberus | Licencia verificada | Fuente |
|---|---|---|---|---|
| **1. MRIcron / MRIcroGL `brodmann.nii.gz`** (Van Essen / Krish Singh, distribuido por Rorden) | MNI / Colin27 (`ch2`) | Áreas de Brodmann corticales únicamente; **faltan las 29 estructuras subcorticales** (tálamo, putamen, núcleo rojo, sustancia negra, cuerpo calloso, etc.). | Código MRIcron/MRIcroGL bajo BSD, pero **el atlas Brodmann no tiene licencia comercial clara**: Rorden advierte en GitHub contactar a Krish Singh y recomienda alternativas (AAL/AICHA) para uso comercial. | `github.com/neurolabusc/MRIcroGL`; documentación de MRIcron (`sc.edu`). |
| **2. Pijnenburg et al. (2021)** (Dutch Connectome Lab, *NeuroImage* 239:118274) | MNI152 (volumen y superficie `fsaverage`) | **39 regiones corticales** de Brodmann; **faltan BA omitidas y las 29 estructuras subcorticales** de Cerberus. | Datos suplementarios publicados en el laboratorio; paquetes derivados en GitHub (`ggsegBrodmann`/`ggsegHistorical`) distribuidos bajo **CC BY-NC-SA 4.0** (no comercial, compartir igual) / CC BY según derivado. | Pijnenburg et al. (2021), DOI `10.1016/j.neuroimage.2021.118274`; `dutchconnectomelab.nl`. |
| **3. Yale BioImage Suite `MNI_Brodmann`** (Lacadie et al., 2008, OHBM / *NeuroImage*) | MNI152 | Áreas de Brodmann + un subconjunto propio de estructuras subcorticales, **distinto** de los 29 núcleos específicos del Talairach Daemon (p. ej. núcleos talámicos individuales, sustancia negra, núcleo rojo). | El código de BioImage Suite Web (`bisweb`) usa Apache 2.0 / GPL, pero los volúmenes `yale_broadmann_*.nii.gz` residen en paquetes legados C++/NITRC sin distribución estándar en PyPI/Nilearn. | Lacadie et al. (2008); `github.com/bioimagesuiteweb/bisweb`; NITRC. |
| **4. Julich-Brain / `nilearn.datasets.fetch_atlas_juelich`** (Amunts et al., 2020) | MNI152 (`colin27` / MNI152) | **62 regiones en la versión FSL 5.0 de Nilearn** (`.venv/.../nilearn/datasets/atlas.py:682-708`). Usa nomenclatura citoarquitectónica moderna (`hOc1`, `Area 4a/4p`, etc.), **no etiquetas BA1–47 ni las 29 subcorticales**. | **Licencia FSL** (no comercial sin acuerdo aparte) en Nilearn (`juelich.rst:38`) y **CC BY-NC-SA 4.0** en EBRAINS (`ebrains.eu`). | `.venv/.../nilearn/datasets/description/juelich.rst:12-38`; Amunts et al. (2020), *Science*. |

- **Pros:**
  - Los candidatos nativos en MNI (en particular Lacadie 2008 y Pijnenburg 2021; o Julich-Brain a nivel citoarquitectónico probabilístico) fueron construidos o alineados directamente sobre plantillas MNI, evitando la dependencia de la matriz Talairach → MNI.
  - En el caso específico de Julich-Brain, aporta mapas probabilísticos derivados de múltiples cerebros post-mortem (intervariabilidad real), a costa de abandonar la nomenclatura clásica de Brodmann.
- **Contras:**
  - **Ningún candidato cubre 1-a-1 las 71 etiquetas actuales de `area_functions.json`**, especialmente las **29 estructuras subcorticales** (tálamo, núcleos basales, cuerpo calloso, hipocampo, amígdala, tronco), que resultan determinantes en glioblastomas profundos (`003/t0`, `003/t1`, `005/t0–t2`).
  - Obligaría a rehacer o recortar `backend/cerberus_api/data/area_functions.json` (1,384 líneas curadas con fuentes bibliográficas), `test_area_kb.py` y las entradas faltantes de dominios funcionales.
  - Ninguno viene empaquetado de serie en Nilearn con áreas BA completas en MNI152 (habría que implementar descarga propia con verificación de integridad o empaquetarlo bajo restricciones no comerciales).
- **Coste:** **Alto** (descarga e integración de atlas externo, re-mapeo completo y revisión bibliográfica de `area_functions.json`, nuevos tests de cobertura de etiquetas y pérdida/redefinición de estructuras subcorticales).
- **Licencia:** Mixta y restrictiva en todos los candidatos revisados: **no comercial** (`CC BY-NC-SA 4.0` en Julich/EBRAINS y derivados de Pijnenburg, licencia FSL en `fetch_atlas_juelich`) o **procedencia comercial ambigua** (MRIcron `brodmann.nii.gz`, paquetes legados de BioImage Suite). No mejora la situación de licencia respecto al Talairach actual.

### Opción C · Mantener el atlas sin conversión y etiquetar «aproximado» en UI, README y reportes

- **Pros:**
  - Cero riesgo de regresión en el pipeline de registro ni cambios en resultados numéricos previos.
  - Coste de código muy bajo (solo textos en `frontend/src/components/AreasPanel.tsx`, `README.md` y reporte/warnings).
- **Contras:**
  - La comparación con Lancaster muestra un desplazamiento promedio de **4.99 mm** (picos de **13.40 mm**), con cambios de reporte en **8/8 estudios** y áreas **elocuentes** implicadas en **7/8 estudios**.
  - Un rótulo de «aproximado» no compensa ante el usuario clínico o académico el hecho de reportar como afectada (o dejar fuera del margen de 10 mm) una corteza elocuente cuando existe una transformación afín publicada para convertir entre los espacios (Lancaster et al., 2007).
- **Coste:** **Bajo** (solo cambios de texto en UI, README y reportes).
- **Licencia:** Se aplican los términos del Talairach Daemon documentados en §1.

---

## 5. Recomendación

Se recomienda **elegir la Opción A: aplicar la transformación afín de Lancaster (`icbm_other2tal`, Lancaster et al., 2007)**.

**Justificación cuantitativa y técnica (con base en la §3):**

1. **Desplazamiento de los mapas frente al margen de proximidad de Cerberus.** El reporte usa `MARGIN_MM = 10.0 mm` (`areas.py:30`). El sesgo por omitir la conversión Talairach → MNI152 introduce un desplazamiento medio de **4.76–5.22 mm** (media global **4.99 mm**, ~50 % del margen completo) y picos de hasta **13.40 mm** (`005/t1`, BA11), superando incluso los `10.0 mm` en `002/t0`, `005/t0`, `005/t1` y `005/t2`. La magnitud favorece la opción A frente a un cambio de texto en el panel «Funciones en riesgo».
2. **Impacto real en áreas elocuentes:** En **8 de 8 estudios** cambia el conjunto de áreas reportadas o su estado (`Afectada` ↔ `Cercana`), y en **7 de 8** (`001/t0`, `002/t0`, `003/t0`, `003/t1`, `005/t0`, `005/t1`, `005/t2`) se ven implicadas **áreas elocuentes** (incluyendo BA1, BA2, BA3, BA6, BA17, BA22, BA40, BA41, núcleo rojo, núcleo subtalámico y núcleos talámicos).
3. **Relación coste-beneficio frente a la Opción B:** Ningún atlas Brodmann nativo en MNI152 ofrece cobertura 1-a-1 de las **71 regiones** (42 BA + 29 subcorticales) curadas en `area_functions.json` ni mejora las restricciones de licencia respecto a `talairach.org`. La **Opción A** resuelve el sesgo de espacios en ~20–40 líneas dentro de `backend/cerberus_api/atlas.py`, sin tocar contratos de API (§6/§7) ni `area_functions.json`, y puede reutilizar los campos de deformación `mni/` ya calculados.
4. **Comunicación en ATLAS1.** La aplicación de la opción A declara en el reporte y el README la proyección a MNI152, la afín de Lancaster (2007, `icbm_other2tal`) y el carácter determinista de la estimación.

---

## 6. ATLAS1 · antes/después

Se ejecutó el mapeo de producción en modo `full` sobre los ocho estudios, de uno en uno. Para cada estudio, el script de evaluación volvió a proyectar el atlas omitiendo Lancaster sobre el mismo `mni/` de REG1. El reporte histórico proviene de `storage/results` y usa el registro previo a REG1. `004/t0` carece de reporte histórico.

Cada recuento muestra el total de áreas reportadas por hemisferio y el desglose (afectadas/cercanas, margen de 10 mm). Las columnas de cambios indican apariciones, desapariciones y cambios entre «Afectada» y «Cercana», en ese orden. El efecto de REG1 compara el histórico con el nuevo registro sin Lancaster. El efecto de Lancaster compara ambas proyecciones sobre el mismo registro REG1. Los centroides se miden en milímetros en el espacio del paciente para las etiquetas presentes en ambos mapas REG1. La primera media incluye solo áreas de Brodmann y la segunda incluye también las estructuras subcorticales.

| Estudio | Histórico pre-REG1 | REG1 sin Lancaster | REG1 con Lancaster | Cambios de REG1 | Cambios de Lancaster | Media centroides de Brodmann / todas (mm) | Mapeo `full` (s) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `001/t0` | 23 (8/15) | 23 (8/15) | 22 (7/15) | +0 / −0 / 0 | +0 / −1 / 1 | 4.76 / 3.92 | 87.26 |
| `002/t0` | 48 (16/32) | 48 (16/32) | 41 (16/25) | +0 / −0 / 0 | +0 / −7 / 2 | 5.24 / 4.58 | 33.90 |
| `003/t0` | 79 (45/34) | 79 (45/34) | 73 (42/31) | +0 / −0 / 0 | +1 / −7 / 5 | 4.89 / 4.14 | 33.53 |
| `003/t1` | 76 (40/36) | 76 (40/36) | 67 (38/29) | +0 / −0 / 0 | +0 / −9 / 2 | 4.99 / 4.18 | 37.67 |
| `004/t0` | — | 40 (20/20) | 41 (18/23) | — | +2 / −1 / 2 | 5.05 / 4.24 | 40.06 |
| `005/t0` | 58 (34/24) | 59 (32/27) | 60 (34/26) | +1 / −0 / 2 | +2 / −1 / 4 | 5.08 / 4.33 | 45.90 |
| `005/t1` | 61 (35/26) | 61 (35/26) | 59 (36/23) | +0 / −0 / 0 | +1 / −3 / 3 | 5.06 / 4.45 | 47.06 |
| `005/t2` | 56 (33/23) | 55 (34/21) | 54 (34/20) | +1 / −2 / 1 | +0 / −1 / 2 | 4.79 / 4.34 | 41.62 |

REG1 cambió 2 de los 7 reportes con histórico (+2 / −2 / 3). Lancaster cambió los 8 reportes (+6 / −30 / 21). La media de las ocho medias por estudio fue de **4.98 mm** para Brodmann y **4.27 mm** para todas las etiquetas. El desplazamiento máximo fue de **14.18 mm**.

Los ocho mapeos sumaron 367.00 s (mediana de 40.84 s). Cada tiempo incluye el registro `full` y el cálculo del reporte. Carga media de `uptime` (1, 5 y 15 minutos) durante el mapeo: inicio 15:48 (`5.52 7.41 7.24`), fin 15:54 (`21.68 15.23 10.76`). Durante la comparación: inicio 15:55 (`21.23 15.24 10.79`), fin 15:56 (`15.71 14.71 10.91`).

### Reproducción

Desde la raíz del repositorio, indica las rutas de los datos, los modelos y un almacenamiento de evaluación separado. El ejemplo lee los reportes históricos de `storage/results`.

```bash
export CERBERUS_DATA_DIR="$PWD/Data"
export CERBERUS_MODELS_DIR="$PWD/models"
export CERBERUS_STORAGE_DIR="$(mktemp -d)"
export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=6

uptime
uv run python - <<'PY'
from time import perf_counter

from cerberus_api import areas, catalog
from cerberus_api.config import Settings

s = Settings()
for (patient, timepoint), files in sorted(catalog._scan(s.data_dir, "*/t*/*.nii.gz").items()):
    if "gtv" in files:
        started = perf_counter()
        result = areas.run_area_mapping(files, s.results_dir / patient / timepoint, s.models_dir, "full")
        print(f"{patient}/{timepoint} {perf_counter() - started:.2f}s {len(result.areas)} áreas")
PY
uptime

uv run python tools/eval/atlas_lancaster.py \
  --data-dir "$CERBERUS_DATA_DIR" \
  --results-dir "$CERBERUS_STORAGE_DIR/results" \
  --before-results-dir storage/results \
  --out "$CERBERUS_STORAGE_DIR/atlas_lancaster.json"
uptime
```

El JSON incluye áreas por hemisferio, entradas, salidas, cambios de categoría y desplazamientos de centroides. `--before-results-dir` es opcional para medir solo el efecto de Lancaster. El mapa y el reporte se reemplazan en el próximo mapeo de cada estudio, con el nombre de atlas que identifica Lancaster. La API puede seguir mostrando el reporte histórico hasta que se vuelva a mapear el estudio. Las transformaciones REG1 se reutilizan cuando su huella coincide.

---

## Referencias

- **Código del repositorio y entorno instalado (`.venv`, `nilearn 0.14.1`):**
  - `backend/cerberus_api/atlas.py:35-49, 68-73, 100-157, 221-293, 301-374`
  - `backend/cerberus_api/areas.py:30, 91-191`
  - `backend/cerberus_api/area_kb.py:6-7` y `backend/tests/test_area_kb.py:11-54`
  - `.venv/lib/python3.11/site-packages/nilearn/datasets/atlas.py:682-810, 2132-2278`
  - `.venv/lib/python3.11/site-packages/nilearn/datasets/struct.py:46-50, 196-251, 368-411`
  - `.venv/lib/python3.11/site-packages/nilearn/datasets/description/talairach_atlas.rst:13-55`
  - `.venv/lib/python3.11/site-packages/nilearn/datasets/description/icbm152_2009.rst:9, 61, 68`
  - `.venv/lib/python3.11/site-packages/nilearn/datasets/description/juelich.rst:12-38`
  - `README.md:526-531`, `docs/PROGRESS.md:783-791`, `docs/PLAN_MVP.md:604, 689-692`
- **Bibliografía:**
  - Lancaster, J. L., Tordesillas-Gutiérrez, D., Martinez, M., Salinas, F., Evans, A., Zilles, K., Mazziotta, J. C., & Fox, P. T. (2007). *Bias between MNI and Talairach coordinates analyzed using the ICBM-152 brain template.* Human Brain Mapping, 28(11), 1194–1205. Implementación oficial `icbm_other2tal.m` / `tal2icbm_other.m` en BrainMap (`https://www.brainmap.org/icbm2tal/`).
  - Lancaster, J. L., Woldorff, M. G., Parsons, L. M., Liotti, M., Freitas, C. S., Rainey, L., Kochunov, P. V., Nickerson, D., Mikiten, S. A., & Fox, P. T. (2000). *Automated Talairach Atlas labels for functional brain mapping.* Human Brain Mapping, 10(3), 120–131. (`https://www.talairach.org`).
  - Talairach, J., & Tournoux, P. (1988). *Co-planar stereotaxic atlas of the human brain.* Thieme, New York.
  - Fonov, V., Evans, A. C., Botteron, K., Almli, C. R., McKinstry, R. C., & Collins, D. L. (2011). *Unbiased average age-appropriate atlases for pediatric studies.* NeuroImage, 54(1), 313–327 (y Fonov et al., 2009, NeuroImage 47:S102 para ICBM 2009a).
  - Pijnenburg, R., Scholtens, L. H., Ardesch, D. J., de Lange, S. C., Wei, Y., & van den Heuvel, M. P. (2021). *Myelo- and cytoarchitectonic microstructural and functional human cortical atlases reconstructed in common MRI space.* NeuroImage, 239, 118274.
  - Lacadie, C. M., Fulbright, R. K., Rajeevan, N., Constable, R. T., & Papademetris, X. (2008). *More accurate Talairach coordinates for neuroimaging using non-linear registration.* NeuroImage, 42(2), 717–725 (y resumen OHBM 2008 sobre *Brodmann Areas defined in MNI space using a new Tracing Tool in BioImage Suite*).
  - Amunts, K., Mohlberg, H., Bludau, S., & Zilles, K. (2020). *Julich-Brain: A 3D probabilistic atlas of the human brain's cytoarchitecture.* Science, 369(6506), 988–992.

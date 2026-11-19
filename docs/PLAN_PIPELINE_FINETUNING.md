# Plan de implementación: pipeline de fine-tuning CFB-GBM

Fecha: 2026-11-17. Estado: FT0–FT5 implementados y validados solo con datos sintéticos (ver `TRAINING.md`); sin entrenamiento real.

## 1. Entrega y alcance

Construir una CLI local y reproducible que permita inventariar CFB-GBM, preparar datos, dividir
pacientes, adaptar SegResNet, entrenar, reanudar y evaluar cuando se disponga de datos y cómputo.
La entrega se valida con NIfTI sintéticos y pruebas pequeñas en CPU: no requiere descargar la
colección ni ejecutar fine-tuning real. Este documento desarrolla la
[nota previa](NOTA_FINETUNING_MONAI.md) y complementa el [plan principal](PLAN_MVP.md).

Objetivo inicial propuesto: **GTV binario**, con cuatro canales de entrada y un logit de salida.
No entrenar TC/WT/ET usando GTV como etiqueta común. La predicción adaptada será un artefacto
experimental independiente. Integrarla en API/UI requerirá otro ticket y actualizar los contratos.
No se añaden jobs de entrenamiento a arq ni se modifica el modelo activo de Cerberus.

## 2. Evidencia y supuestos

La [ficha oficial de TCIA](https://www.cancerimagingarchive.net/collection/cfb-gbm/), consultada
el 17 de noviembre de 2026, publica 264 sujetos, 208.01 GB y NIfTI con imágenes y segmentaciones.
La versión 3 añadió 347 archivos GTV y 545 máscaras binarias para normalización; la versión 4
corrigió numeración de carpetas y tablas RANO. Las modalidades dependen de disponibilidad.
La licencia indicada es CC BY 4.0 y se exige citar el dataset, DOI `10.7937/v9pn-2f72`.
Estos totales publicados no representan el número de estudios utilizables para entrenamiento:
el inventario local deberá determinarlo. No mezclar versiones sin reconciliar identificadores.

Evidencia del repositorio:

- `segmentation.py` contiene SegResNet, normalización y métricas reutilizables; solo realiza inferencia.
- El bundle local contiene configuraciones de entrenamiento y evaluación. No constituyen una
  configuración lista para CFB-GBM ni garantizan carga inicial de pesos.
- La red actual usa cuatro entradas, tres salidas, 16 filtros iniciales y bloques `(1,2,2,4)` / `(1,1,1)`.
- `pyproject.toml` dirige PyTorch a ruedas CPU en Linux: el entorno actual no garantiza CUDA.
- El fallback de inferencia permite T2* como T2; el pipeline tendrá una política explícita diferente.

Sin descargar datos, quedan por verificar nombres reales de máscaras, cobertura GTV por tiempo,
coherencia geométrica, disponibilidad de secuencias, versión de pesos y compatibilidad CUDA.
No afirmar que todos los pacientes son elegibles ni estimar duración de entrenamiento sin medir.

## 3. Arquitectura y artefactos

Implementar `backend/cerberus_training/` como paquete hermano de `cerberus_api`, con `__main__.py`,
`config.py`, `inventory.py`, `splits.py`, `transforms.py`, `model.py`, `train.py`, `evaluate.py`
y `artifacts.py`. Incluirlo en el empaquetado de Hatch. Usar configuración JSON tipada y versionada;
guardar ejemplo en `configs/training/gtv_binary.json`. Mantener dependencias adicionales fuera
del runtime web cuando sea posible. Tipos y tests por cada función nueva del backend.

Directorio de trabajo configurable, por defecto `storage/training/`, ignorado por Git:

```text
inventory.jsonl             # estudios aceptados y excluidos con motivos
splits.json                 # asignación inmutable por paciente
cache/<preprocess_hash>/    # volúmenes preparados, escritura atómica
runs/<run_id>/
  config.resolved.json
  provenance.json           # commit, versiones, hashes, dispositivo, semillas
  metrics.jsonl
  checkpoints/{last,best}.pt
  threshold.json            # opcional: umbral optimizado en val (FT4)
  evaluation/<split>[-last|-baseline]/{per_study.csv,per_patient.csv,summary.json}
  export[-last]/{model.pt,export.json,model_card.md}
```

Entradas en directorio externo de solo lectura; no copiar 208 GB dentro del repositorio.
Manifest con versión de esquema, ID de estudio, paciente seudónimo, tiempo, rutas relativas,
modalidad realmente seleccionada, shape, affine, spacing, etiqueta, elegibilidad y exclusiones.
No incluir información clínica identificable. Validar identificadores con `sequences.py` antes
de construir rutas; resolver rutas bajo la raíz autorizada y rechazar escapes y symlinks externos.
NIfTI mediante `load_nifti()`. Si el formato externo difiere, implementar un adaptador explícito;
no relajar los validadores de la API. DICOM fuera de alcance.

## 4. Inventario, calidad y particiones

1. `inventory`: recorrer cabeceras y nombres sin cargar toda la colección; comprobar 3D, affine
   invertible, spacing positivo y referencias a archivos. Producir resumen por paciente/tiempo.
2. `prepare`: validar contenido finito, máscaras binarias, soporte espacial y alineación; reportar
   errores por estudio. No transformar una etiqueta ausente en máscara vacía. Una máscara vacía
   existente debe conservar su condición y someterse a revisión de calidad.
3. Perfil inicial estricto: exigir GTV, T1Gd, T1 (`t1eg`, después `t1tse`), T2 `t2tse` y FLAIR.
   T2* no sustituye T2 automáticamente. Un perfil opcional de compatibilidad deberá declarar
   sustituciones/canales cero y generar un experimento separado; nunca cambiar silenciosamente
   la cohorte si el perfil estricto encuentra pocos pacientes.
4. `split`: sobre estudios elegibles, agrupar todos los tiempos de cada paciente. Semilla 42;
   proporción inicial 70/15/15 por paciente, redondeo determinista documentado y conjuntos no vacíos.
   Fallar si no hay suficientes pacientes. Guardar listas y hash; nunca redistribuir al reanudar.
5. Detectar duplicados exactos por hashes y evitar que crucen particiones. Registrar revisión de
   posible solapamiento con preentrenamiento como verificada o desconocida, no asumir ausencia.
6. No elegir pacientes, umbrales ni hiperparámetros por resultados de prueba. Las exclusiones
   usan reglas previas de calidad, registradas antes de entrenar. Revisar estratos t0/seguimiento
   y disponibilidad de canales; no usar supervivencia ni datos clínicos como entrada.

## 5. Preprocesamiento y consumo de recursos

Orden fijo `[T1c,T1,T2,FLAIR]`, referencia T1Gd, orientación canónica y grid ortogonal de 1 mm.
Remuestrear imágenes con interpolación lineal y etiquetas/máscaras con vecino más próximo.
Remuestreo no corrige desregistro: excluir o señalar casos que requieran registro adicional.
Aplicar máscara cerebral cuando exista; si falta, registrar uso de soporte no nulo y la política
configurada. Normalizar cada canal sobre vóxeles no nulos con la función existente.
Probar identidad geométrica imagen/etiqueta y no usar GTV para normalizar o definir el recorte
de validación, prueba o inferencia.

Entrenar con parches, configuración inicial `96×96×96`, batch 1 y acumulación 4. Muestreo
positivo/negativo 1:1 en entrenamiento; si GTV está vacío, tomar negativos. Aplicar flips,
rotaciones discretas y perturbaciones suaves de intensidad solo en entrenamiento, con semilla.
Validación sobre volúmenes completos mediante ventanas deslizantes, sin augmentations.

Caché persistente opcional con claves derivadas de hashes de fuentes, configuración y versión
de transformaciones; invalidarla ante cambios. Procesar un estudio por vez, workers iniciales 0,
límite de caché configurable y comprobación de espacio libre. No cargar toda la colección en RAM.
El preflight estima tamaño descomprimido y disco de caché; no equipara tamaño comprimido con RAM.

## 6. Pesos, entrenamiento y reanudación

Exigir checkpoint local y SHA-256 esperado. No descargar pesos automáticamente en `train`.
Fijar versión/revisión del bundle y verificar sus metadatos y APIs instaladas al implementar.
Construir SegResNet compatible de tres salidas, cargar el checkpoint con correspondencia estricta,
y reemplazar únicamente la proyección final por una salida, inicializada con semilla fija.
Verificar el nombre real de esa capa en MONAI instalado. Registrar parámetros transferidos y nuevos;
no ocultar incompatibilidades mediante `strict=False` indiscriminado.

Configuración inicial ajustable, no óptimo validado: Dice + BCE con logits, AdamW, learning rate
`1e-4`, weight decay `1e-5`, máximo 100 épocas, validación cada época y parada tras 15 validaciones
sin mejora. Entrenar toda la red por defecto; permitir congelación explícita registrada.
Seleccionar `best` por Dice macro por paciente de validación; umbral inicial fijo 0.5. Si se
optimiza umbral, hacerlo exclusivamente en validación y guardarlo antes de evaluar prueba.
Sembrar Python, NumPy, PyTorch y workers; registrar límites de determinismo del dispositivo.

`last` incluye red, optimizador, scheduler si se configura, scaler AMP, época/paso, mejor métrica,
estado de parada temprana, generadores aleatorios, configuración y hashes de dataset/split.
Escritura atómica, `best` separado. Reanudar en límite de época con validación de compatibilidad;
rechazar cambios de etiquetas, canales o particiones. No sobrescribir runs existentes.
Fallar claramente ante NaN/Inf, checkpoint incompatible o CUDA solicitada pero no disponible.
No reducir batch/parches silenciosamente ante OOM.

Crear entorno de entrenamiento CUDA independiente con versiones fijadas y resolución reproducible,
sin cambiar las ruedas CPU de la app. Documentar instalación con `uv`, versión CUDA/PyTorch
compatible y comprobación de dispositivo. CPU queda soportado para tests; AMP solo si el backend
lo soporta. El hardware real y tamaño final de parches se ajustarán con un piloto futuro.

## 7. Evaluación y exportación

Reutilizar `mask_metrics` y `dice`, manteniendo las citas históricas del notebook. Reportar Dice/F1,
recall, precisión, HD95 en mm, error de volumen firmado y absoluto en cm³, por estudio y paciente.
Promediar primero tiempos dentro de paciente y después pacientes; incluir dispersión, denominadores
válidos e intervalos bootstrap por paciente. Ambos vacíos: Dice 1; HD95 null si alguna máscara
vacía; precisión/recall null cuando no hay denominador. Reportar vacíos por separado.

Evaluar predicción binaria en grid de referencia documentado, con restauración geométrica probada.
Comparar con la salida TC del modelo original como referencia imperfecta frente a GTV, nunca
como equivalencia de etiquetas. Mantener el pipeline original de baseline y registrar sus canales
y preprocesamiento; diferencias respecto al modelo adaptado deben figurar en el reporte.
La evaluación de prueba será un comando explícito, nunca parte del bucle de entrenamiento.

Exportar pesos, arquitectura, orden de canales, transformaciones, umbral, hashes, licencia/citación
y ficha del modelo. Sin puntuaciones ficticias: antes de entrenar, estado `not_evaluated`.
No exigir mejora de Dice para declarar construido el pipeline: eso será criterio del experimento
posterior, cuyo mínimo de mejora debe fijarse antes de usar el conjunto de prueba.

## 8. CLI propuesta (implementada en FT0–FT5)

```bash
uv run python -m cerberus_training inventory --data-root /ruta/CFB-GBM --output storage/training/inventory.jsonl
uv run python -m cerberus_training prepare --config configs/training/gtv_binary.json
uv run python -m cerberus_training split --config configs/training/gtv_binary.json
uv run python -m cerberus_training preflight --config configs/training/gtv_binary.json
uv run python -m cerberus_training train --config configs/training/gtv_binary.json --dry-run
# Solo en una ejecución futura solicitada:
uv run python -m cerberus_training train --config configs/training/gtv_binary.json
uv run python -m cerberus_training train --config configs/training/gtv_binary.json --resume /ruta/last.pt
uv run python -m cerberus_training evaluate --run /ruta/run --split test
uv run python -m cerberus_training export --run /ruta/run
```

`--dry-run` valida configuración, fuentes, pesos, splits y recursos sin backward, sin actualizar
pesos y sin descargar nada. `smoke --synthetic` es otro comando, con datos y pesos artificiales:
ejecuta dos pasos de optimización en CPU, guarda/reanuda y evalúa. No confundirlo con fine-tuning real.

## 9. Tickets y aceptación

Tickets incorporados a §8/§9 del [plan principal](PLAN_MVP.md#fine-tuning-ft0ft5).
Una rama y PR por ticket; dependencias previas integradas antes de iniciar el siguiente.

| Ticket | Depende de | Entrega y aceptación |
|---|---|---|
| FT0 · configuración y entorno | B5/B13 existentes | CLI instalable, esquema estricto, entorno CUDA documentado y fijado, imports sin red; `--help` funciona en CPU |
| FT1 · inventario y particiones | FT0 | NIfTI externos, exclusiones explicadas, paths seguros, split determinista por paciente, duplicados sin fuga |
| FT2 · preprocesamiento | FT1 | Canales y geometría probados, GTV binario preservado, caché invalidable, parches y límites de memoria |
| FT3 · transferencia y trainer | FT2 | Carga estricta y adaptación de cabeza verificadas, backward sintético, best/last atómicos y reanudación |
| FT4 · evaluación y exportación | FT3 | Métricas conocidas en fixtures, agregación por paciente, test aislado, exportación recargable |
| FT5 · smoke y manual | FT4 | Recorrido CLI completo offline en CPU; manual con comandos futuros, fallos y recursos; checks obligatorios verdes |

Tests sin red ni datos reales: estudios sintéticos con distintos affines/spacings, canales faltantes,
GTV ausente/vacío/no binario, archivos corruptos, NaN, traversal, duplicados, splits y caché.
Inyectar predictor para evaluación y red pequeña para trainer. Verificar actualización real de
parámetros, transferencia de tensores, head nueva y equivalencia de reanudación determinista en CPU.
Añadir prueba de cableado de SegResNet con pesos artificiales; las pruebas pesadas del modelo real
serán `slow` y opcionales. No depender de `Data/001` para CI.

Antes de cada PR: Ruff, formato, Pyright, pytest no slow y build frontend según AGENTS.md;
FT5 añade smoke offline y verificación visual existente de regresión de la app. Actualizar
PROGRESS/HANDOFF al integrar cada ticket, sin marcar entrenamiento ni evaluación real como realizados.

## 10. Definición de entrega

El pipeline estará listo cuando sus comandos y artefactos existan, pase el recorrido sintético
completo, rechace entradas incompatibles y pueda reanudar/exportar de forma reproducible.
Quedarán expresamente pendientes la auditoría del dataset completo, el piloto GPU, entrenamiento,
validación científica y eventual integración del modelo. Ninguna de esas ejecuciones es necesaria
para completar la implementación solicitada.

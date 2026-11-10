# Nota para planificar con Astra: adaptación de MONAI a CFB-GBM

Fecha: 2026-11-10. Estado: idea para evaluación y planificación posterior.
Solicitud del usuario: conservar esta discusión para generar después el plan con Astra.
Esta nota no autoriza entrenamiento, cambios de arquitectura ni nuevos tickets de implementación.

## Situación actual

Cerberus utiliza SegResNet del bundle `brats_mri_segmentation` **0.5.4**, ejecutado con
**MONAI 1.6.1** en Docker. Los metadatos del bundle declaran MONAI 1.4.0 y BraTS 2018 como
fuente de entrenamiento. Estas versiones se verificaron en el contenedor y en su `metadata.json`;
conviene comprobarlas de nuevo antes de planificar.

El proyecto realiza inferencia con pesos preentrenados; no tiene un pipeline propio de entrenamiento
ni aprendizaje automático a partir de los estudios subidos. Repetir una segmentación no modifica pesos.
La implementación está en [`segmentation.py`](../backend/cerberus_api/segmentation.py).

El bundle descargado incluye `train.json`, `evaluate.json` y `multi_gpu_train.json`.
Son una base de entrenamiento, no un fine-tuning listo para nuestros datos: hay que verificar y
configurar explícitamente la carga de pesos preentrenados, las etiquetas, los datos y la validación.

## Decisión principal: qué queremos predecir

Nuestro GTV excluye edema. Las salidas actuales son TC (núcleo), WT (núcleo más edema) y ET
(región con realce). TC tampoco equivale necesariamente a GTV. No usar la misma máscara GTV como
verdad de referencia para entrenar las tres salidas ni interpretar su concordancia como validación
independiente de WT/TC/ET.

| Alternativa | Requisito | Consecuencia |
|---|---|---|
| Conservar TC/WT/ET | Anotaciones compatibles y revisadas para cada región | Mantiene el objetivo multirregional del modelo |
| Adaptar a GTV binario | Máscaras GTV coherentes y controladas | Reutiliza pesos de SegResNet y adapta la salida; cambia el objetivo y los contratos del producto si se integra |

Propuesta preliminar para discutir con Astra: experimentar primero con **GTV binario**, manteniendo
el modelo actual como línea base. No es una decisión aprobada ni implica que GTV sustituya TC/WT/ET.
La comparación debe reconocer que el modelo actual no fue entrenado específicamente para GTV.

## Contenido que debería cubrir el plan

1. **Inventario y calidad:** contar pacientes independientes y estudios utilizables del dataset completo;
   auditar GTV, secuencias T1c/T1/T2/FLAIR, alineación, spacing, brain_mask y canales faltantes.
   La muestra local no debe confundirse con el dataset completo.
2. **Partición por paciente:** todos los tiempos del mismo paciente permanecen en una única partición.
   Separar entrenamiento, validación y prueba antes de ajustar parámetros; considerar validación cruzada
   si el tamaño lo justifica. Verificar posible solapamiento con datos de preentrenamiento.
3. **Línea base reproducible:** fijar versiones, hashes de pesos, preprocesamiento, umbral y pacientes.
   Medir el modelo original y documentar el desajuste entre sus clases y GTV.
4. **Experimento de fine-tuning:** decidir cómo reutilizar pesos y adaptar la salida, qué capas entrenar,
   pérdida, tasa de aprendizaje, augmentations, manejo de canales faltantes, recursos y criterio de parada.
   No asumir que el `train.json` original carga automáticamente nuestro checkpoint.
5. **Selección y evaluación:** elegir configuración y umbral con validación; evaluar al final en prueba
   sin usar esos pacientes para decisiones. Comparar Dice/F1, recall, precisión, HD95 en mm y error de
   volumen firmado y absoluto. Explicitar casos vacíos y definiciones de cada métrica.
6. **Incertidumbre y fallos:** reportar resultados por paciente, dispersión e intervalos de confianza
   agrupados por paciente; revisar visualmente casos desfavorables y estratificar cuando haya datos
   suficientes. Accuracy no debe ser el indicador principal por el predominio del fondo.
7. **Integración condicionada a evidencia:** conservar pesos originales y permitir volver al modelo
   anterior. Versionar el modelo adaptado y sus métricas; actualizar contratos y textos si se añade una
   predicción GTV distinta de las salidas BraTS. No reemplazar el modelo de la app durante la exploración.

## Límites y preguntas abiertas

- Unos pocos pacientes locales permiten un experimento exploratorio, no demostrar generalización.
- Entrenar más no garantiza mejorar; la mejora debe observarse en pacientes no usados para ajustar el modelo.
- Buenas métricas de segmentación no equivalen a certeza clínica ni certifican seguridad de uso clínico.
- Falta definir objetivo final, tamaño de datos etiquetados, calidad de referencia, presupuesto de cómputo,
  disponibilidad de GPU, criterios de éxito y disponibilidad de un conjunto externo de evaluación.
- Antes de proponer entrenamiento, verificar las APIs en el entorno instalado y compatibilidad del bundle
  con MONAI/PyTorch actuales. Consultar alcance y contratos de [`PLAN_MVP.md`](PLAN_MVP.md).

## Referencias para Astra

- [Configuración oficial de entrenamiento](https://github.com/Project-MONAI/model-zoo/blob/dev/models/brats_mri_segmentation/configs/train.json).
- [Bundle oficial, versión 0.5.4](https://huggingface.co/MONAI/brats_mri_segmentation/tree/370f7f9d062745fbac445e7fe6d6616d35df04ec/configs).
- [Métricas MONAI](https://monai.readthedocs.io/en/stable/metrics.html).
- [Metrics Reloaded](https://pmc.ncbi.nlm.nih.gov/articles/PMC11182665/).

Las referencias a ramas `dev` y documentación `stable` pueden cambiar; contrastarlas con los archivos
del bundle descargado. Al retomar: leer esta nota, auditar los datos disponibles y generar el plan
con Astra antes de implementar.

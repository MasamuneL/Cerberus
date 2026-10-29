# QA de UX/UI — F9 y F10

Fecha: 2026-10-29. Rama: `feature/ux-ui`. Alcance: §14 de `PLAN_MVP.md`.

**Resultado funcional: APROBADO, CP-027.** La pasada final terminó con exit 0, del
2026-10-29 17:37:35 al 17:43:15 UTC. El orquestador verificó el JSON y revisó las capturas finales.

## Verificación

| Comprobación | Resultado |
|---|---|
| `uv run ruff check backend` | Correcto |
| `uv run ruff format --check backend` | 34 archivos correctos |
| `uv run pyright` | 0 errores, 0 warnings |
| `uv run pytest -q -m "not slow"` | 425 passed, 5 deselected |
| `cd frontend && npm run build` | Correcto; aviso conocido de bundles mayores de 500 kB |
| QA Playwright en 1440×900 y 1280×800 | 33/33 checks; exit 0 |
| Axe WCAG 2.1 AA | 14 auditorías; 0 violaciones automáticas; 12 con resultados incompletos |
| Capturas | 27; visor, capas y tablas revisados a ambos tamaños |
| Red y mutaciones | 0 fallos HTTP inesperados; 4 respuestas 404 previstas; 0 mutaciones reales |

Chrome headless usa SwiftShader, Vite en `http://localhost:5180` y la API real mediante el proxy.
Se comprueban los estudios 001/t0 y 005/t0 con mapas y segmentaciones existentes, además de 002/t0 para
cambiar de estudio. No se descargan modelos ni se ejecutan ANTs o MONAI durante este QA.

La suite comprueba pestañas y foco con flechas/Home/End, botones de áreas y riesgos con Enter/Espacio,
dominios y límites de 5/10 mm, 142 colores del atlas, vistas y atajos, cursor, capas, opacidades y cambios
durante descarga, modo «Todas», tablas sin desborde, RANO longitudinal, anonimización y estados de jobs.
Los POST de los jobs se interceptan; cualquier mutación no prevista se bloquea y hace fallar el QA.

Las interacciones extendidas del visor y los jobs se prueban en 1440×900. Ambos tamaños cubren las
pestañas, tablas, datos reales, cambio de estudio, subida y auditorías de accesibilidad.

## Hallazgos corregidos

| Hallazgo | Corrección y evidencia |
|---|---|
| QA anterior usaba checkboxes y lectura de píxeles WebGL no fiable | Botones `aria-pressed`, asserts reales, capturas del compositor, exit 1 y cierre en `finally` |
| Lecturas y opacidades podían quedar obsoletas durante una descarga | Estado reiniciado, lectura bloqueada durante la carga y aplicación de la última opacidad; descarga interceptada en QA |
| Texto «dentro del GTV» tenía contraste 4.42:1 | Color de texto independiente del overlay: 6.45:1 |
| Atajos operaban el visor con foco en botones del modal de subida | Guardas para el diálogo; regresión con foco en Cerrar y tecla 2 |
| Filas con `role="button"` perdían semántica de tabla | Botones nativos dentro del encabezado de fila y encabezados por columna |
| Etapas del job se inferían por reloj | Se muestran las etapas sin inventar la activa; solo se completan cuando la API informa `complete` |
| «Todas» pintaba fondo azul y un cubo opaco en 3D | Dos guardas transparentes en el LUT evitan la mezcla del shader Niivue con la etiqueta 1; nombres conservados por etiqueta real; captura posterior revisada |
| Tabla de 005/t0 desbordaba 6 px | Columnas fijas, encabezado Hem. con nombre completo y envoltura de nombres; QA comprueba anchuras |

## Evidencia y límites

`tools/e2e/shots/report.json` registra checks, capturas, errores de red/consola, auditorías axe y sus
resultados incompletos. Los artefactos quedan ignorados por Git; se regeneran según el
[README del QA](../tools/e2e/README.md).

Se revisan manualmente las capturas del visor, el modo «Todas», el enfoque de áreas y las tablas a los
dos tamaños. **Regresión visual automática: INCONCLUSA**, porque no existe una línea base de imágenes.
Las capturas nuevas sí permiten comprobar los defectos concretos encontrados.

Axe no certifica conformidad WCAG completa. Los resultados incompletos incluyen `aria-prohibited-attr`
en tendencias heredadas de F11, `label-content-name-mismatch` en el botón de ayuda «?» y `color-contrast`
en iconos y contenido fuera del scroll. Se conservan los targets para una revisión específica. No se hizo
una sesión con lector de pantalla, una prueba móvil ni una medición de Core Web Vitals.

La revisión independiente de código no encontró bloqueantes. La observación sobre atajos dentro del
modal fue corregida antes de la pasada final. Orquestación: Terra/high para F9/F10, Sol/high para QA y
Astra/high para revisión independiente.

## Repetición

Con API, Vite y datos/resultados disponibles:

```bash
cd tools/e2e
npm ci
CERBERUS_UI=http://localhost:5180 npm run verify
```

Para aislar la regresión del fondo:

```bash
CERBERUS_UI=http://localhost:5180 node verify-background.mjs
```

No ejecutar dos instancias de Chrome/SwiftShader simultáneamente.

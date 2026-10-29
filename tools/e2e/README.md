# Verificación de UX/UI (§14)

Requiere Chrome instalado, la API y el servidor Vite de desarrollo en ejecución, y los estudios reales
001/t0 y 005/t0 con segmentación y mapa de áreas. El catálogo de referencia tiene ocho estudios.

```bash
cd tools/e2e
npm ci
CERBERUS_UI=http://localhost:5180 npm run verify
```

La URL predeterminada es `http://localhost:5173`. `CERBERUS_TIMEOUT` permite cambiar el límite de espera de
carga de volúmenes (180000 ms por defecto). No ejecutes varias instancias simultáneamente: SwiftShader usa
bastante CPU y memoria durante la carga de Niivue.

La verificación cubre 1440×900 y 1280×800, pestañas y filas con teclado, capas y lectura del cursor,
volumetría, segmentación, evolución, funciones en riesgo y límites 5/10 mm, paleta fría, aviso de
anonimización y axe con reglas WCAG 2.1 AA. Los escenarios de jobs usan `page.route`: ningún POST llega a
la API real. Las mutaciones no previstas se bloquean y hacen fallar la ejecución. No requiere Redis ni
worker para los jobs simulados; no ejecuta MONAI, ANTs ni subidas.

Las capturas y `shots/report.json` quedan ignorados por Git. Cualquier aserción fallida produce código de
salida 1; el navegador se cierra mediante `finally`. Los 404 solo son esperados para endpoints de
resultados ausentes; otros fallos HTTP, errores JavaScript y errores de consola hacen fallar la prueba.

Revisa las PNG manualmente, especialmente la imagen coronal, los ajustes abiertos y los dos tamaños de
ventana. No hay línea base visual previa: las capturas no prueban por sí solas ausencia de regresiones.
El script no lee píxeles con `drawImage(canvas)`: WebGL usa `preserveDrawingBuffer=false`. Comprueba carga
real y estado de volúmenes y conserva las capturas del compositor para revisión humana. Axe complementa
las pruebas de teclado; sus hallazgos incompletos quedan en el reporte y requieren revisión humana.

La regresión del fondo del atlas también puede repetirse aisladamente con
`CERBERUS_UI=http://localhost:5180 node verify-background.mjs`. Este comando verifica las entradas
transparentes del LUT, el fondo cero, etiquetas visibles y el nombre del área enfocada. Guarda capturas
de los modos «Todas» y «Solo afectadas», además de `shots/background-report.json`. La suite principal
incluye las mismas comprobaciones del LUT y verifica la opacidad final tras cambiarla durante una
descarga interceptada. Las interacciones extendidas del visor y los jobs se ejecutan en 1440×900;
ambos tamaños cubren pestañas, tablas, datos reales, estudio distinto, aviso de subida y axe.

## Smoke de Docker y frontend de producción

Con Docker Compose levantado y la muestra `Data/001` descargada mediante Git LFS:

```bash
cd tools/e2e
npm ci
CERBERUS_UI=http://localhost:8080 node verify-docker.mjs
```

El puerto predeterminado es `8080`; `CERBERUS_TIMEOUT` conserva el límite de 180000 ms para Niivue.
Se usa Chrome headless con SwiftShader. Ejecuta un solo navegador de QA a la vez.

Este runner funciona con los archivos compilados servidos por Nginx: no importa módulos de `/src` ni
consulta el objeto privado de Niivue. Comprueba HTML compilado, fallback SPA, proxy `/api`, salud,
catálogo dinámico, volumetría de 001/t0 (33.14 ± 0.01 cm³), cabeceras y descargas NIfTI completas,
canvas visible, carga terminada y lectura del cursor con intensidades y estado del GTV. También prueba
pestañas por teclado, atajos, opacidad, ocultar/mostrar el GTV y el formulario de subida sin enviarlo.
Solo requiere la muestra 001/t0: no exige ocho estudios ni resultados previos de MONAI o ANTs.

Guarda `shots/docker/report.json` y capturas a 1440×900 y 1280×800, ignorados por Git. Las aserciones
fallidas producen exit 1 y el navegador se cierra en `finally`. Cualquier mutación solicitada se bloquea
y hace fallar el smoke; los únicos 404 permitidos corresponden a resultados ausentes según el catálogo.
Revisa las capturas manualmente: el smoke no certifica accesibilidad ni sustituye `verify.mjs`.

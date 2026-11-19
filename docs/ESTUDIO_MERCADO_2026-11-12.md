# Estudio de mercado de Cerberus

**Fecha de corte:** 12 de noviembre de 2026.

**Decisión acordada:** definir precio y modelo de negocio.

**Región acordada:** México, con entrada por Jalisco.

**Naturaleza:** investigación documental y modelo comercial preliminar. No se han aplicado entrevistas, encuestas ni pilotos comerciales.

## 1. Recomendación ejecutiva

Recomiendo validar Cerberus como **servicio institucional de instalación, capacitación y mantenimiento para investigación y docencia en neuroimagen**, con despliegue local y cobro anual por sede. El primer comprador probable es un grupo con un proyecto financiado y acceso autorizado a imágenes; el usuario puede ser un investigador, residente o especialista. Esta es una hipótesis comercial, no una demanda demostrada.

El precio inicial que propongo probar es **$48,000 MXN por sede al año**, más **$12,000 MXN de implementación**, antes de impuestos. Un piloto de ocho semanas costaría **$9,000 MXN**, acreditables a la primera anualidad si se contrata dentro de los 30 días posteriores al piloto. Son precios experimentales construidos con supuestos de costos; no son tarifas observadas del mercado ni compromisos de entrega.

Existe competencia gratuita con funciones potentes: [3D Slicer](https://slicer.org/) e [ITK-SNAP](https://www.itksnap.org/pmwiki/pmwiki.php?n=Main.HomePage). También existe competencia especializada comercial: [Neosoma](https://www.neosomainc.com/) y [Brainlab](https://www.brainlab.com/surgery-products/overview-neurosurgery-products/cranial-planning/). Por ello, «tener IA» o «mostrar imágenes en 3D» no basta para justificar el pago. La propuesta debe demostrar menor trabajo de preparación, capacitación y mantenimiento en un flujo concreto.

El modelo base produce **$96,000 MXN de ingreso recurrente anual contratado al terminar el primer año**, correspondiente a dos sedes. No equivale a ventas realizadas ni a ingresos cobrados durante todo ese año. La prioridad es obtener evidencia de uso y presupuesto en dos instituciones; no financiar todavía una expansión clínica nacional.

## 2. Alcance y preguntas que orientan la decisión

El estudio responde estas preguntas:

1. ¿Qué institución pagaría y de qué partida saldría el presupuesto?
2. ¿Qué trabajo mejora Cerberus frente al software que esa institución ya utiliza?
3. ¿Conviene cobrar por sede, usuario, estudio o proyecto?
4. ¿Qué precio cubre soporte y adquisición de clientes sin perder atractivo frente a alternativas gratuitas?
5. ¿Cuántas sedes pueden contratarse de forma realista desde Jalisco?
6. ¿Qué debe resolverse antes de ofrecer un piloto con datos institucionales?

El horizonte comercial es de **12 meses**, con una referencia de crecimiento a **24 meses**. Ambos son horizontes de planificación. Se estudia el producto para investigación y docencia; una futura oferta para diagnóstico, tratamiento o planificación quirúrgica necesita otra evaluación de producto, evidencia y regulación.

### Método y grado de certeza

Se revisaron el repositorio local, estadísticas y publicaciones primarias, páginas oficiales de proveedores y fuentes oficiales mexicanas. Las fuentes se consultaron el 12 de noviembre de 2026. Cada enlace acompaña la afirmación que respalda.

En este documento:

- **Hecho:** información observada en el repositorio o publicada por una fuente identificada.
- **Supuesto:** valor elegido para calcular escenarios; todavía no se ha medido.
- **Inferencia:** interpretación comercial de los hechos.
- **Recomendación:** acción propuesta para obtener evidencia o decidir.

La investigación no incluye cotizaciones privadas, entrevistas ejecutadas, estudio representativo de compradores ni validación clínica. La ausencia de una función o precio en una página consultada no demuestra que el proveedor no lo ofrezca.

## 3. Qué puede ofrecer Cerberus hoy

La revisión corresponde al checkout `c189cee`, rama `feat/D3-simple-setup`. El [handoff](HANDOFF.md) identifica CP-052 como último checkpoint integrado y D3 como trabajo en rama, con publicación y verificaciones externas pendientes. No se considera disponible un paquete público descargable por el solo hecho de existir implementación local.

| Capacidad observada | Posible valor para el comprador | Límite comercial actual |
|---|---|---|
| Visor web multiplanar, capas y superficie GTV en 3D | Revisar imágenes y explicar casos desde una interfaz común | Su utilidad diferencial frente al visor existente debe medirse |
| Volumetría GTV y seguimiento longitudinal | Preparar comparaciones y actividades de investigación | Las categorías por cambio de volumen no constituyen por sí solas una evaluación clínica completa |
| Segmentación MONAI y métricas de concordancia | Explorar resultados y comparar segmentaciones | No se encontró evidencia de validación multicéntrica comercial del producto |
| Ingesta DICOM y NIfTI | Reducir pasos de preparación en un proyecto | Hay hallazgos documentados sobre metadatos, temporales y cargas que requieren cierre |
| Atlas de Brodmann y dominios funcionales | Apoyo educativo para estudiar relaciones anatómicas | Hay una discrepancia Talairach–MNI152 pendiente; no sustenta localización funcional individual |
| Docker y autenticación OIDC | Facilitar instalación y acceso a la demo | No acreditan aislamiento clínico por paciente ni preparación hospitalaria completa |

Fuentes internas: [README](../README.md), [plan](PLAN_MVP.md), [estado de implementación](HANDOFF.md) y [QA](QA_2026-10-29.md). Algunas frases generales del README y del plan están desactualizadas respecto a autenticación; para ese estado se priorizaron el tablero y los checkpoints recientes.

La función [`rano_category`](../backend/cerberus_api/volumetry.py) asigna categorías mediante umbrales de cambio frente a `t0`. El artículo original de **RANO 2.0** incorpora condiciones adicionales a la variación de volumen. Comercialmente conviene describirlo como apoyo al análisis longitudinal y delimitar expresamente su alcance. [Wen et al., JCO, 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10860967/).

**Posicionamiento propuesto:** «Cerberus ayuda a equipos de investigación y docencia a explorar estudios de glioblastoma, comparar GTV y analizar segmentaciones mediante una interfaz web local, con instalación y acompañamiento en español».

El GTV del dataset excluye edema; no debe confundirse con todas las regiones WT/TC/ET que entrega el modelo. Tampoco debe prometerse «medir pérdida funcional» a partir del solapamiento con un atlas. Estos límites están documentados en el [README](../README.md).

## 4. Segmento objetivo y comprador

### Cliente ideal inicial

**Hipótesis de perfil:** grupo de investigación o docencia asociado con un hospital de referencia o universidad del área Guadalajara–Zapopan, con un proyecto activo de neuroimagen, un responsable técnico y un presupuesto identificable. Para calificarlo comercialmente se propone exigir acceso autorizado a una cohorte o colección pública y un flujo de trabajo recurrente, no solo interés en una demostración.

| Participante | Necesidad que debe verificarse | Papel en la compra |
|---|---|---|
| Investigador principal o coordinador de proyecto | Preparación reproducible de casos y resultados | Patrocinador y posible responsable de presupuesto |
| Residente, tesista o analista de imágenes | Menos pasos manuales y menos dependencia de scripts | Usuario frecuente; normalmente no decide el gasto institucional |
| Neurorradiólogo o neurocirujano investigador | Revisión de resultados y criterios de aceptación | Referente experto; su interés no sustituye autorización de compra |
| TI o ingeniería biomédica | Instalación, mantenimiento y datos bajo control institucional | Puede habilitar o bloquear el despliegue |
| Administración o compras | Contrato, factura, presupuesto y continuidad | Comprador económico o autorizador |

**Segmentos secundarios:** enseñanza de neuroanatomía con casos públicos y proyectos de evaluación de algoritmos. **Menor prioridad inicial:** centros generales con pocos casos de neurooncología o instituciones cuyo requisito mínimo sea integración clínica completa con PACS y sistemas de tratamiento.

### Instituciones para explorar en Jalisco

Esta lista identifica posibles lugares de investigación; **no son clientes, aliados ni compradores calificados**. No se les ha contactado.

| Institución o entorno | Evidencia pública de afinidad | Qué falta verificar |
|---|---|---|
| Hospital Civil de Guadalajara | Comunica actividad de neurocirugía de lesiones cerebrales | Proyecto vigente, acceso a datos, patrocinador y presupuesto. [HCG](https://portal.hcg.gob.mx/hcg/boletin/1567) |
| CUCS, Universidad de Guadalajara | Tiene un programa de especialidad en neurocirugía vinculado al HCG | Uso docente y comprador; evitar contar dos veces el mismo presupuesto HCG–UDG. [CUCS](https://www.cucs.udg.mx/espncxnhcgjim/ingreso) |
| Instituto Jalisciense de Cancerología | Publica una coordinación de investigación y un departamento de radioterapia | Existencia de un proyecto de neuroimagen apropiado; oncología general no implica demanda de GBM. [Investigación](https://ijc.gob.mx/investigacion), [manual institucional de 2024](https://ijc.gob.mx/arc/8/lV/c/MOP_IJCancerolog%C3%ADa_20241104_TOMO%20I.pdf) |
| Centro Médico Nacional de Occidente, IMSS | Hay antecedente institucional de atención tecnológica a lesiones cerebrales | Confirmar capacidad y responsables actuales: la referencia consultada es antigua, de 2018. [IMSS](https://www.imss.gob.mx/prensa/archivo/201811/277) |

No se asigna una probabilidad de compra a estas instituciones. La región se eligió por tu preferencia y cercanía operativa, no porque se haya demostrado mayor disposición a pagar que en otros estados.

## 5. Tamaño de mercado: TAM, SAM y SOM

### 5.1. Unidad y frontera del cálculo

Se calcula **ingreso anual de servicios por sede**, en MXN antes de impuestos. Una sede significa una instalación y un alcance contractual definido; no cada usuario, equipo de RM o paciente. Un grupo hospitalario puede negociar varias sedes en un contrato y reducir el ingreso medio.

No existe en las fuentes revisadas un censo de compradores mexicanos de software de investigación de GBM. Por ello, las cifras siguientes son un **modelo aproximado de un segmento acotado**, no una medición del TAM total de Cerberus en México.

Como base observable se usa un estudio publicado en junio de 2026 que identifica **114 clínicas de radioterapia en México**, a partir de DIRAC. Se utiliza como aproximación de sedes oncológicas especializadas: no todas investigan GBM y no incluye necesariamente universidades u hospitales sin radioterapia. El artículo cita DIRAC con acceso en septiembre de 2025; no es un conteo actualizado a noviembre de 2026. [Padilla-Campoy, 2026](https://www.scielo.org.mx/scielo.php?pid=S2565-005X2026000200081&script=sci_arttext).

DIRAC advierte que su registro se alimenta de contribuciones voluntarias y puede estar incompleto. Debe usarse como punto de partida para construir una lista comercial verificable. [Metodología de DIRAC, OIEA](https://dirac.iaea.org/Home/Methodology).

### 5.2. Cálculo base

| Indicador | Definición para este estudio | Cálculo | Resultado anual |
|---|---|---|---:|
| **TAM de referencia** | Las 114 sedes del universo oncológico elegido, suponiendo que todas necesitaran y pagaran el servicio | `114 × $48,000` | **$5,472,000 MXN** |
| **SAM nacional preliminar** | Subconjunto con proyecto, datos, infraestructura y presupuesto compatibles; se supone 30% y se redondea hacia abajo | `floor(114 × 0.30) = 34; 34 × $48,000` | **$1,632,000 MXN** |
| **SAM inicial Jalisco** | Hipótesis operativa de seis sedes elegibles por identificar y verificar, dentro del SAM nacional | `6 × $48,000` | **$288,000 MXN** |
| **SOM a 12 meses** | Meta de dos sedes contratadas al cierre del año, inicialmente en Jalisco | `2 × $48,000` | **$96,000 MXN de ingreso recurrente anual contratado** |
| **SOM a 24 meses** | Meta de cuatro sedes activas; contempla expansión nacional y ausencia de bajas | `4 × $48,000` | **$192,000 MXN de ingreso recurrente anual contratado** |

El **30%**, las **seis sedes locales** y las metas de contratación son supuestos propios. No proceden de DIRAC ni de estadísticas de compra. Las seis sedes locales aún no están acreditadas por la lista de prospectos; si solo aparecen tres elegibles, el SAM local base deberá reducirse a la mitad. TAM, SAM y SOM son subconjuntos: **no se suman**.

La interpretación correcta del TAM de referencia es «techo de ingresos del universo seleccionado bajo un precio hipotético», no «114 compradores confirmados». Se excluyen implementación y pilotos porque no son ingreso recurrente. No se añade el presupuesto de docencia como si fuera un segundo mercado independiente cuando corresponde a la misma sede.

### 5.3. Sensibilidad a demanda y precio

Primero se mantiene el precio en $48,000 por año para observar únicamente cambios de elegibilidad y ventas:

| Escenario supuesto | Fracción elegible nacional | SAM nacional, sedes | SAM nacional, MXN/año | SAM Jalisco, sedes supuestas | SOM al mes 12, sedes | Ingreso recurrente anual del SOM |
|---|---:|---:|---:|---:|---:|---:|
| Sin validación comercial | Sin determinar | Sin determinar | Sin determinar | Sin determinar | 0 | $0 |
| Conservador | 15% | 17 | $816,000 | 3 | 1 | $48,000 |
| Base | 30% | 34 | $1,632,000 | 6 | 2 | $96,000 |
| Optimista | 45% | 51 | $2,448,000 | 10 | 4 | $192,000 |

Después se mantienen 114 sedes en el TAM y 34 en el SAM nacional para observar únicamente el precio:

| Precio anual supuesto | TAM de referencia | SAM nacional base | Ingreso recurrente anual de dos sedes |
|---|---:|---:|---:|
| $24,000 MXN | $2,736,000 | $816,000 | $48,000 |
| $48,000 MXN | $5,472,000 | $1,632,000 | $96,000 |
| $72,000 MXN | $8,208,000 | $2,448,000 | $144,000 |

Estas tablas no predicen que el número de compradores permanezca constante cuando suba el precio. Esa relación es precisamente lo que falta investigar.

### 5.4. Comprobación desde ventas y necesidad

Para obtener dos contratos en el primer año se propone probar este embudo, enteramente supuesto: **12 sedes contactadas × 75% con reunión × 2/3 con encaje y piloto × 1/3 que contrata = 2 sedes**. Equivale a nueve reuniones, seis pilotos y dos conversiones. Requiere prospección nacional si Jalisco no ofrece suficientes sedes; el costo de seis pilotos debe cubrirse y medirse. Los porcentajes son metas de ejecución, no tasas históricas.

Como contraste de necesidad, la ficha vigente de **GLOBOCAN 2024**, publicada en septiembre de 2026, estima **3,039 casos nuevos de cáncer de cerebro y sistema nervioso central** en México. Es una estimación modelada de una categoría más amplia que GBM; no se convierte aquí a pacientes elegibles ni a compradores. [IARC, ficha de México, página 2](https://gco.iarc.who.int/media/globocan/factsheets/populations/484-mexico-fact-sheet.pdf).

**Inferencia:** la especialización exige verificar el volumen de trabajo de cada sede; el tamaño epidemiológico no justifica por sí solo una suscripción. No se utilizan el gasto sanitario total, todos los hospitales, todos los equipos de RM ni un informe global de IA médica como sustitutos de este mercado.

## 6. Competencia: precio, funciones, público y debilidades

Los precios corresponden a páginas públicas consultadas; no se solicitaron cotizaciones. «No publicado» significa que no se encontró una tarifa en la fuente revisada. Las fricciones señaladas como hipótesis deben probarse con usuarios y demostraciones comparables.

| Alternativa y relación | Precio público observado | Funciones y público | Límite documentado o posible fricción | Implicación para Cerberus |
|---|---|---|---|---|
| **Neosoma Glioma / plataforma**. Directo funcional; comercial clínico | Tarifa no publicada en las páginas revisadas; requiere consulta comercial | Segmentación y cuantificación de gliomas, seguimiento longitudinal, plataforma web y conexión con flujos de planificación; equipos de neurooncología | La oferta pública describe una plataforma cloud. Encaje con exigencias locales de alojamiento, contratación y soporte en México pendiente de verificar | Cerberus debe demostrar valor en investigación local y acompañamiento, no alegar funciones exclusivas. [Proveedor](https://www.neosomainc.com/), [Glioma](https://www.neosomainc.com/neosoma-glioma) |
| **Brainlab Elements**. Directo en segmentación/volumetría; adyacente en planificación | Tarifa no publicada en la página revisada | Segmentación asistida por IA, volumen y crecimiento, fusión, tractografía y planificación; neurocirugía | Alcance amplio de suite. Posible exceso de alcance para un proyecto docente es una hipótesis; no hay evidencia aquí de que sea caro o difícil de usar | Evitar competir como sistema quirúrgico. [Brainlab](https://www.brainlab.com/surgery-products/overview-neurosurgery-products/cranial-planning/) |
| **DeepBraTumIA, Universidad de Berna**. Directo en investigación GBM | Acceso académico sin tarifa publicada; NITRC indica licencia de atribución, no comercial y sin derivados | Segmentación multicompartimento, volumetría, procesamiento por lotes y extracción cerebral; investigadores | Requiere T1, T2, T1 con contraste y FLAIR; la universidad indica mejor desempeño preoperatorio. Restricciones de licencia para uso comercial | La segmentación académica ya existe; Cerberus debe justificar el servicio alrededor del flujo. [Universidad de Berna](https://www.artorg.unibe.ch/research/mia/software/index_eng.html), [licencia en NITRC](https://www.nitrc.org/projects/deepbratumia/) |
| **3D Slicer**. Directo como sustituto de trabajo de investigación | **Gratis**, código abierto | Visualización, segmentación, registro, extensiones de IA y herramientas DICOM; investigación y desarrollo | Seleccionar módulos y configurar el flujo puede requerir capacitación: hipótesis de fricción, no defecto demostrado | Es el comparador mínimo de un piloto; ofrecer instalación no basta si Slicer resuelve mejor el trabajo. [3D Slicer](https://slicer.org/), [uso comercial](https://www.slicer.org/commercial-use.html) |
| **ITK-SNAP**. Directo para segmentación y revisión | **Gratis**, código abierto | Segmentación manual y semiautomática, navegación y acceso a algoritmos mediante DSS; investigadores | Su orientación principal es segmentación, no la gestión institucional específica propuesta para Cerberus. No debe describirse como carente de IA: anuncia funciones nuevas desde 2025 | Probar si Cerberus reduce pasos reales de análisis longitudinal. [ITK-SNAP](https://www.itksnap.org/pmwiki/pmwiki.php?n=Main.HomePage) |
| **NORA**. Directo como plataforma web de investigación | Tarifa no publicada en la página revisada | Visor web, datos, pipelines, estudios de lectores y despliegue local o cloud; equipos de investigación | La amplitud y personalización pueden requerir configuración: hipótesis. No se verificó costo ni soporte local | «Web y local» tampoco es diferenciador exclusivo de Cerberus. [NORA](https://www.nora-imaging.com/) |
| **OsiriX MD**. Indirecto; visor comercial y estación de trabajo | **Desde $69.99/mes**, tal como aparece en su web; moneda e impuestos deben confirmarse en la oferta. Doce mensualidades equivalen a $839.88 en esa misma moneda, no a una tarifa anual anunciada | DICOM, 2D/3D y conexión con PACS; profesionales que usan Mac | Requiere Apple Mac. La página consultada no acredita un flujo equivalente de GBM automatizado | Referencia de compra de un visor, no comparación equivalente por sede. No se convierte a MXN. [OsiriX MD](https://www.osirix-viewer.com/osirix/osirix-md/), [licencias y suscripciones](https://www.osirix-viewer.com/support/faq/) |
| **PACS existente, hojas de cálculo y scripts internos**. Indirecto y statu quo | Costo incremental potencialmente cero si ya existen licencias y personal; depende de la institución | Medición, consulta y preparación manual de resultados | Tiempo de personal, errores y mantenimiento deben observarse; no se han cuantificado | Es posible que «seguir como estamos» sea la alternativa elegida. Medir su costo antes de proponer reemplazo |

La FDA documentó la autorización 510(k) de **NS-HGlio en 2022**, con indicaciones concretas para segmentación y cuantificación en gliomas de alto grado. Ese antecedente demuestra que Cerberus compite también con productos que han recorrido una vía regulatoria; no prueba autorización mexicana ni equivalencia clínica. [FDA, K221738](https://www.accessdata.fda.gov/cdrh_docs/pdf22/K221738.pdf).

### Ventaja defendible que debe probarse

La integración de funciones, interfaz en español, instalación local y acompañamiento cercano puede resultar útil, pero ninguna se ha validado como motivo de compra. Una ventaja más sólida sería una combinación de **flujo reproducible, tiempo total menor, soporte confiable y evidencia obtenida en instituciones locales**. Utilizar MONAI no constituye por sí solo propiedad intelectual exclusiva.

No se comparan métricas Dice de diferentes productos como si fueran un ranking: los conjuntos, etiquetas y protocolos difieren. Tampoco se presenta un resultado de un paciente de Cerberus como precisión comercial generalizable.

## 7. Modelo de negocio y arquitectura de precios

### Comparación de modelos

| Modelo | Ventaja | Problema a validar | Decisión propuesta |
|---|---|---|---|
| Servicio anual por sede, instalación local | Presupuesto predecible y datos bajo infraestructura institucional | Compra anual y alcance de soporte; puede haber compras centralizadas | **Modelo inicial recomendado** |
| Cobro por usuario | Fácil de explicar | Desincentiva participación de residentes y grupos docentes | Probar solo si compras exige esta unidad |
| Cobro por estudio | Relaciona factura con actividad | Poco ingreso en grupos pequeños y cómputo local difícil de medir contractualmente | Alternativa para proyectos puntuales; todavía sin tarifa recomendada |
| Servicio por proyecto/cohorte | Encaja con subvenciones y entregables | Ingreso irregular y trabajo específico difícil de reutilizar | Canal inicial complementario, con alcance y presupuesto propios |
| SaaS centralizado | Actualizaciones centralizadas | Añade alojamiento de imágenes, transferencia de datos y costos operativos | Reevaluar después de validar demanda |
| Licencia perpetua con soporte opcional | Puede ajustarse a compras de una sola vez | Ingreso de mantenimiento incierto | No priorizar en esta etapa |

**Qué se cobraría:** configuración, capacitación, mantenimiento y soporte de un flujo definido. La autorización para distribuir o licenciar el código, modelos y datos debe aclararse antes de ofrecer un contrato. Cobrar servicios no elimina obligaciones de licencias ni de protección de datos.

### Oferta propuesta para experimentar

Todos los importes siguientes son **supuestos en MXN, antes de impuestos**, sujetos a derechos de distribución, capacidad de soporte y preparación del producto. No son planes ya implementados.

| Oferta | Precio propuesto | Alcance contractual a probar |
|---|---:|---|
| Demostración | $0 | Sesión con datos públicos, sin instalación productiva ni carga de datos identificables |
| Piloto de investigación, ocho semanas | $9,000 | Una sede, un proyecto, hasta 20 estudios previamente disociados y autorizados; instalación acotada, una capacitación y reporte de tiempos/uso. Máximo supuesto de 12 horas de servicio |
| Servicio anual de investigación | $48,000/año + $12,000 de implementación | Una instalación por sede, cuentas de su equipo, dos capacitaciones iniciales dentro de implementación y hasta 12 horas anuales de atención. Mantenimiento de la versión acordada; sin garantía clínica ni desarrollo a medida |
| Variante docente, solo para comprobar sensibilidad | $24,000/año + implementación por cotizar | Colecciones públicas y talleres, hasta cuatro horas de atención anual. Se ofrece únicamente si puede delimitarse sin subsidiar soporte intensivo |

Infraestructura, GPU, almacenamiento, respaldos operativos y TI cotidiana serían provistos por el cliente. La cotización debe explicitar versiones, recursos, responsabilidades, horario de atención y exclusiones. No se promete disponibilidad permanente ni integración PACS a estos precios.

**Ejemplo de cobro:** primer año de investigación = `$48,000 + $12,000 = $60,000`. Si ya se pagó el piloto y aplica el crédito, el saldo sería `$60,000 − $9,000 = $51,000`; el total combinado seguiría siendo $60,000. No se suman otra vez esos $9,000 como ingreso adicional del cliente convertido.

### Por qué $48,000 es una hipótesis razonable para probar

Se propone probar tres precios para **el mismo alcance anual**: $24,000, $48,000 y $72,000. La variante docente reducida es otro producto; sus respuestas no deben mezclarse con las del mismo alcance. El precio final dependerá del valor observado y de la contratación real.

Ejemplo de valor, con supuestos: `200 análisis/año × 20 minutos ahorrados ÷ 60 × $900/hora = $60,000/año`. El recurrente de $48,000 consumiría 80% de ese valor y el primer año completo consumiría 100%; **esa propuesta sería débil si el único beneficio fuera ese ahorro**. Para justificar el primer año de $60,000 solo mediante tiempo harían falta 200 análisis ahorrando 20 minutos a $900/hora; para entregar al cliente un valor equivalente al doble del costo harían falta 400 análisis. Ninguna de esas actividades ni tarifas de personal se ha medido.

Conclusión de precio: comprobar primero frecuencia, tiempo activo y costo real de trabajo. Si el cliente solo gana unas pocas horas al año, reducir alcance/precio o vender un taller/proyecto puede ser más sensato que insistir en la anualidad.

## 8. Costos, margen y punto de equilibrio

Este modelo usa **$400 MXN por hora de trabajo técnico cargada** como supuesto interno, no como salario observado. El cliente paga su infraestructura. No incluye costo de validación clínica, registro sanitario, impuestos, intereses ni desarrollo específico para un hospital.

| Concepto del servicio anual base | Supuesto | Costo anual por sede |
|---|---|---:|
| Atención al cliente | 12 h × $400 | $4,800 |
| Mantenimiento y verificación atribuibles a la sede | 12 h × $400 | $4,800 |
| **Costo directo recurrente** | 24 h en total | **$9,600** |
| **Contribución recurrente** | $48,000 − $9,600 | **$38,400; 80%** |

Implementación: `16 h × $400 = $6,400` de costo directo frente a $12,000 cobrados; contribución de $5,600, equivalente a 46.7%. Piloto: `12 h × $400 = $4,800` de costo frente a $9,000; contribución de $4,200 si no hay costos adicionales. En una conversión el piloto consume parte del ingreso total de $60,000; su costo debe contarse además del de implementación salvo que se documente trabajo reutilizado.

Adquisición de un contrato: se supone un costo de `40 h comerciales/técnicas × $400 + $2,000 de traslados = $18,000`. Las horas deben incluir prospección fallida y propuestas, y el cálculo debe absorber los pilotos que no conviertan cuando esos costos no se recuperen mediante su precio. No es un CAC medido.

Contribución mensual equivalente: `$38,400 ÷ 12 = $3,200`. Recuperación orientativa del costo de adquisición: `$18,000 ÷ $3,200 = 5.625 meses`. No representa flujo de caja mensual cuando el cliente paga anticipado ni incluye demoras de compras.

Si los gastos fijos anuales fueran **$360,000 MXN**, excluyendo trabajo variable ya contabilizado, el equilibrio recurrente sería `ceil($360,000 ÷ $38,400) = 10 sedes`. Se excluyen ingresos de instalación para no depender de ventas nuevas para sostener el negocio.

Si el costo directo sube a 60 horas anuales por sede, costaría $24,000, la contribución bajaría a 50% y harían falta 15 sedes para esos mismos gastos fijos. El principal riesgo económico es convertirse en soporte y desarrollo a medida con un precio de producto estándar.

**Inferencia:** dos contratos demuestran una señal inicial, pero no sostienen por sí solos una operación con esos gastos. El escenario base es compatible con un servicio especializado pequeño; no demuestra todavía una empresa de alto crecimiento.

## 9. Condiciones que afectan la venta y el precio

1. **Privacidad y robustez.** Antes de usar datos institucionales, cerrar y verificar los hallazgos relevantes de metadatos, archivos temporales y consumo de recursos. El [handoff](HANDOFF.md) señala A3 integrada; no debe repetirse el hallazgo histórico de «sin autenticación» como si siguiera vigente. A5 y la ola P continúan pendientes según el estado revisado. Datos locales no equivalen automáticamente a datos anonimizados.
2. **Propósito de uso.** El servicio inicial propuesto se restringe a investigación y docencia. Esa etiqueta no concede automáticamente una exención regulatoria si su uso real o promoción influye en decisiones médicas. La NOM-241-SSA1-2025 contempla software como dispositivo médico; una evolución clínica requiere determinar la ruta aplicable con asesoría regulatoria. No se asigna aquí clase de riesgo ni costo de registro. [NOM vigente consultada](https://sidof.segob.gob.mx/notas/docFuente/5754074), [guía COFEPRIS](https://www.gob.mx/cofepris/documentos/guia-para-la-obtencion-del-registro-sanitario-de-dispositivos-medicos).
3. **Datos y contrato.** Los datos de salud pueden ser sensibles conforme a la legislación mexicana. Deben definirse responsable, encargado, finalidades, acceso, conservación y base jurídica aplicable; los hospitales públicos tienen un régimen distinto al de particulares. No se supone que una firma genérica autorice todo uso. [LFPDPPP, reforma del 14-11-2025](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf), [decreto de las leyes de 2025](https://sidof.segob.gob.mx/notas/docFuente/5752569).
4. **Licencias y titularidad.** No se encontró un archivo de licencia del proyecto en la revisión de archivos. Aclarar titularidad de contribuciones y permisos de código, dependencias, pesos y datos antes de distribuir. No se verificó completamente la licencia de la colección CFB-GBM: el acceso a su ficha falló durante esta investigación. [Ficha que debe revisarse](https://www.cancerimagingarchive.net/collection/cfb-gbm/). No se deduce permiso comercial de que un recurso sea descargable.
5. **Exactitud y evidencia.** Resolver Talairach–MNI152 antes de ofrecer precisión anatómica; separar desempeño del software, utilidad para investigación y evidencia clínica. No prometer superioridad, sustitución de especialistas ni resultados clínicos a partir del QA funcional.
6. **Compra pública y continuidad.** El interés de un médico puede no traducirse en compra. Deben obtenerse requisitos de proveedor, responsable presupuestario, calendario, contrato y mantenimiento antes de considerar un prospecto como oportunidad comercial. Plazos y costos siguen sin medirse.

Estas condiciones se derivan del uso y estado concretos del proyecto y afectan qué puede venderse; no son prueba de cumplimiento ni una auditoría jurídica completa.

## 10. Investigación con usuarios: guion listo para aplicar

### Reclutamiento y registro

Se propone una primera ronda de **12 entrevistas**, de 30–40 minutos, en al menos cuatro instituciones: cuatro usuarios de análisis, cuatro responsables expertos/investigadores, dos personas de TI y dos compradores o administradores. Es una muestra cualitativa intencional, no estadística. Registrar institución con un código y separar respuestas por rol y por institución.

**Invitación sugerida, sin enviar:** «Estamos investigando cómo se preparan y analizan imágenes de glioblastoma para investigación y docencia. Nos interesa conocer su proceso actual y cómo se decide la compra de herramientas. La entrevista dura unos 35 minutos; no necesitamos datos ni imágenes identificables de pacientes».

**Apertura:** «Su participación es voluntaria y puede omitir preguntas. No buscamos evaluar su desempeño. Tomaremos notas sin información de pacientes. ¿Autoriza las notas? Si deseamos grabar, solicitaremos su autorización por separado».

### Preguntas, en orden

1. **Contexto:** ¿Cuál es su función y qué parte del análisis de imágenes realiza personalmente?
2. **Caso reciente:** Piense en el último proyecto o actividad docente con imágenes de GBM. ¿Qué necesitaba entregar y a quién?
3. **Proceso:** Describa los pasos desde que recibió las imágenes hasta que obtuvo resultados. ¿Qué herramientas y formatos utilizó?
4. **Trabajo activo:** ¿Cuánto tiempo invirtió preparando datos, revisando resultados y corrigiendo errores? Separe ese tiempo de la espera de cómputo.
5. **Frecuencia:** En los últimos tres meses, ¿cuántos estudios y cuántos pacientes distintos procesaron? ¿Cuántos eran realmente GBM?
6. **Problema:** ¿En qué paso se atoran más? Cuénteme la última vez que ocurrió y cómo lo resolvieron.
7. **Alternativas:** ¿Qué les funciona bien de sus herramientas? ¿Han probado Slicer, ITK-SNAP u otra solución? ¿Qué les impediría cambiar?
8. **Costo actual:** ¿Pagan licencias, soporte, horas de un técnico o servicios externos? Puede responder por rangos o indicar que no lo sabe.
9. **Datos e infraestructura:** ¿Quién autoriza usar imágenes para investigación y dónde deben almacenarse? ¿Qué requiere TI para instalar software local?
10. **Compra:** ¿Cómo compraron la última herramienta comparable? ¿Quién propuso, autorizó, pagó y mantuvo la solución? ¿De qué partida salió?
11. **Demostración neutral:** Mostrar durante cinco minutos el mismo flujo con datos públicos. Pedir: «Explique qué haría con esto, qué le falta y qué no le aporta». No presentar aún el precio.
12. **Condiciones de pago:** Para ese alcance, ¿qué evidencia y condiciones necesitarían para contratar? ¿Qué resultado haría que descartaran el piloto?
13. **Precio:** Presentar una sola oferta asignada previamente para el mismo alcance anual: $24,000, $48,000 o $72,000, más implementación idéntica. ¿Podría tramitarla con su presupuesto actual? ¿Qué tendría que pasar para solicitar una cotización formal? Registrar razones y autoridad real de compra.
14. **Siguiente paso verificable:** ¿Estarían dispuestos a revisar un protocolo de piloto con un responsable y una fecha? Una respuesta afirmativa no se registra como contrato.

**Preguntas adicionales para TI:** sistema operativo, recursos disponibles, respaldos, actualizaciones, acceso remoto autorizado y requisitos de proveedor. **Para compras:** facturación, condiciones de pago, contrato, documentación y fecha de disponibilidad presupuestal.

### Prueba de precio

Distribuir las tres ofertas entre instituciones comparables, sin que distintos entrevistados de una misma institución reciban precios contradictorios. Con esta muestra solo se obtienen señales cualitativas; no una curva de demanda. No variar el precio y el alcance simultáneamente. Si se presentan ofertas comerciales reales, mantener condiciones honestas, vigencia clara y registro del descuento.

**Plantilla de notas:** `Código de institución | rol | tarea reciente | estudios/mes | minutos activos | herramientas | gasto actual | problema observado | presupuesto | decisor | precio mostrado | objeción | acción comprometida | fecha | cita anonimizada`.

## 11. Encuesta corta lista para copiar

**Título:** Herramientas de neuroimagen para investigación y docencia.

**Introducción:** Encuesta voluntaria, aproximadamente cuatro minutos. No incluya nombres, identificadores ni datos de pacientes. Buscamos entender procesos y presupuesto; las respuestas no constituyen una intención de compra. Puede elegir «no sé» o saltar preguntas de presupuesto. Registrar únicamente estado, tipo de institución y rol; cualquier contacto se solicita aparte y de forma opcional.

1. **¿En qué participa?** Investigación / docencia / atención clínica sin proyecto de investigación o docencia / TI o ingeniería biomédica / administración o compras / otro. **Estado:** Jalisco / otro estado de México / fuera de México. **Institución:** pública / privada / universidad / otra. Si está fuera de México, analizar por separado; si solo realiza atención clínica, omitir la prueba de oferta investigadora.
2. **En un mes habitual, cuántos estudios de GBM utiliza su equipo para investigación o docencia?** 0 / 1–5 / 6–15 / 16–30 / más de 30 / no sé. No confundir estudios con pacientes distintos.
3. **¿Qué herramientas utiliza actualmente? Marque todas.** PACS o visor institucional / 3D Slicer / ITK-SNAP / Brainlab / Neosoma / scripts propios / otra / ninguna / no sé.
4. **¿Cuánto tiempo activo dedica habitualmente por estudio a preparar, medir y revisar resultados?** Menos de 10 minutos / 10–29 / 30–59 / 60 o más / no realizo esa tarea / no sé. Excluya espera automática de cómputo.
5. **¿Cuáles son sus dos mayores dificultades?** Preparación de datos / segmentación / revisión de resultados / comparación longitudinal / capacitación / instalación y mantenimiento / autorizaciones y datos / ninguna / otra. Máximo dos.
6. **¿Cuánto gasta actualmente su equipo al año en herramientas y soporte para este trabajo?** $0 / menos de $24,000 MXN / $24,000–47,999 / $48,000–71,999 / $72,000 o más / no sé / prefiero no responder.
7. **¿Cómo participa en la compra?** Decido presupuesto / evalúo o recomiendo / solo utilizo / autorizo instalación / no participo. **¿Hay presupuesto identificable para los próximos 12 meses?** Sí / no / depende de aprobación o convocatoria / no sé. Quien no conozca presupuesto puede omitir la pregunta 8.
8. **Oferta asignada:** «Servicio anual para investigación y docencia, una instalación local por sede, capacitación inicial y hasta 12 horas de soporte anual; el cliente aporta equipo y almacenamiento. Precio anual: **[asignar $24,000 / $48,000 / $72,000 MXN]**, más $12,000 MXN de implementación e impuestos aplicables. No incluye uso diagnóstico ni integración PACS». **¿Qué haría?** Solicitaría evaluación y cotización con un responsable / necesitaría evidencia antes de evaluar / no cabe en presupuesto / no resuelve una necesidad / no puedo evaluarlo. **Motivo principal:** respuesta breve opcional.

**Formulario separado y opcional:** «Si desea conversar sobre un piloto, deje un correo profesional y autorice que le contactemos exclusivamente para ello». Definir aviso de privacidad y responsable antes de recopilarlo; no vincular automáticamente ese correo con respuestas anónimas.

**Aplicación propuesta:** 30–50 respuestas de conveniencia para detectar patrones, registrando institución de forma no identificable para controlar duplicados. No calcular margen de error ni extrapolar porcentajes al mercado nacional. Analizar usuarios y compradores por separado; un «solicitaría cotización» es una señal declarada, no una venta.

## 12. Qué validar primero y cómo decidir

El siguiente programa es una propuesta; no se han reservado entrevistas ni comprometido fechas con terceros.

| Periodo propuesto | Trabajo | Evidencia mínima para continuar |
|---|---|---|
| Semanas 1–2 | Construir lista de sedes, revisar derechos y condiciones del piloto; realizar entrevistas sin datos de pacientes | Cuatro instituciones representadas y al menos dos compradores que identifiquen un camino presupuestario concreto |
| Semanas 3–4 | Demostración común y contraste con el proceso actual; probar oferta y alcance | Dos instituciones con problema recurrente, responsable designado y disposición a revisar una cotización formal |
| Semanas 5–12 | Hasta dos pilotos iniciales de ocho semanas, únicamente cuando el producto y permisos permitan el alcance pactado | Medición de tareas y costos, uso repetido y decisión explícita de contratación o rechazo |
| Meses 4–12 | Ajustar oferta y ampliar embudo hasta seis pilotos si los primeros justifican continuar | Dos contratos anuales y registro completo de adquisición, soporte y causas de pérdida |

### Diseño del piloto

Comparar tareas equivalentes con el proceso habitual y Cerberus, usando imágenes autorizadas previamente disociadas o públicas. Alternar el orden cuando sea posible para reducir aprendizaje. Medir carga y preparación, revisión/correcciones, espera de cómputo y tiempo activo por separado. El valor debe calcularse después de incluir correcciones y atención técnica.

Como umbrales experimentales, se propone: **reducción de al menos 25% del tiempo activo mediano**, finalización de al menos 80% de las tareas acordadas y al menos dos usuarios que repitan el flujo sin ayuda directa. Son criterios de decisión propuestos, no resultados observados ni criterios de seguridad clínica. Los resultados deben mantener la calidad de referencia acordada con expertos; ahorrar tiempo perdiendo calidad no cuenta como éxito.

Registrar también instalación, incidencias, uso semanal, horas de soporte, secuencias faltantes y decisión de compra. Las métricas de exactitud requieren un protocolo y referencias apropiadas; este piloto comercial no sustituye validación clínica.

### Reglas de decisión

- **Continuar:** dos instituciones pagan o formalizan contratos anuales, existe uso repetido y la contribución directa estimada supera 60% con el alcance sostenible. Estos umbrales son hipótesis de gestión.
- **Cambiar el modelo:** hay utilidad demostrada pero uso esporádico o solo presupuesto de proyecto; probar servicio por cohorte o talleres con cotización específica.
- **Replantear el precio:** el tiempo ahorrado y los beneficios verificables no justifican el costo total de contratación, o el soporte excede persistentemente lo previsto.
- **Detener la expansión:** no aparece comprador después de investigar instituciones elegibles o solo se pide uso clínico fuera de la capacidad validada del producto. Ausencia de presupuesto no se resuelve añadiendo funciones sin evidencia.

## 13. Conclusión para la decisión comercial

La oportunidad más plausible es un servicio pequeño de investigación y docencia que aproveche una instalación local y acompañamiento cercano. La hipótesis inicial de **$48,000 MXN anuales más $12,000 de implementación** debe probarse frente a tareas y presupuestos reales; no hay evidencia suficiente para llamarla precio de mercado.

El cálculo identifica un techo de referencia de **$5.472 millones MXN anuales** dentro de un universo oncológico elegido, un SAM nacional base supuesto de **$1.632 millones** y una meta inicial de **$96,000 de ingreso recurrente anual contratado**. El universo es una aproximación; el tamaño real sigue dependiendo de contar sedes elegibles y responsables de presupuesto. No hay todavía evidencia de una oportunidad de escala suficiente para una inversión grande.

**Primera validación:** quién paga, cuánto trabajo recurrente tiene y por qué contrataría acompañamiento frente a herramientas gratuitas. **Segunda:** si el piloto entrega valor neto y soporte rentable. **Tercera:** si ese patrón se repite fuera del primer entorno académico. El orden de estas pruebas evita convertir interés técnico en una previsión de ventas sin sustento.

## 14. Registro de fuentes y pendientes

Las referencias se enlazan junto a cada afirmación. Para actualizar el estudio, conservar esta distinción:

| Grupo de evidencia | Fuentes principales | Antigüedad o límite |
|---|---|---|
| Estado de Cerberus | README, PLAN_MVP, HANDOFF, PROGRESS, QA y volumetry.py locales | Snapshot `c189cee`; no se volvió a ejecutar el software ni su QA para este estudio |
| Universo de sedes | Padilla-Campoy, publicación de 2026 basada en DIRAC; metodología OIEA | Conteo publicado, no extracción en vivo ni padrón de compradores; acceso a DIRAC citado en 2025 |
| Contexto epidemiológico | IARC, GLOBOCAN 2024, versión de septiembre de 2026 | Estimaciones modeladas de cerebro/SNC; no dato específico de GBM |
| Funciones y precios de competidores | Sitios oficiales de Neosoma, Brainlab, Berna, Slicer, ITK-SNAP, NORA y OsiriX; NITRC | Afirmaciones de proveedores; no demostraciones independientes ni cotizaciones mexicanas |
| Antecedente regulatorio de competidor | FDA K221738, 2022 | Histórico y limitado a indicaciones y jurisdicción documentadas |
| Marco mexicano | NOM-241-SSA1-2025, COFEPRIS y leyes vigentes consultadas | Debe revisarse para el propósito final y cada comprador; sin dictamen regulatorio |
| Afinidad regional | HCG, CUCS, IJC e IMSS | No valida intención de compra; referencia IMSS de 2018 exige actualización |

**Pendientes que pueden cambiar la recomendación:** cotizaciones comparables de proveedores, padrón deduplicado de sedes y presupuestos, volumen de estudios por institución, condiciones de titularidad/licencia, costos reales de instalación y soporte, sensibilidad al precio, plazos de compras y resultados de pilotos. No se incorporó una tasa de crecimiento de mercado ni un valor de vida de cliente porque no hay evidencia suficiente para estimarlos.

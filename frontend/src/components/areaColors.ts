// Colores de las áreas del atlas (§13), compartidos por AreasPanel y Viewer.
// Valor de etiqueta = índice del atlas (hemisferio izquierdo) o índice + 100 (derecho).
//
// Regla del sistema visual (§14): rojo, naranja y amarillo son exclusivos del tumor. Las áreas solo usan
// tonos fríos: verdes (100°–160°) y cian → azul → violeta (175°–295°). Nunca 0–60° ni 330–360°.
// El tono sale del índice del atlas con la razón áurea sobre esos dos tramos (vecinos bien separados);
// el hemisferio derecho usa el mismo tono con menos luminosidad.

const GOLDEN_RATIO = 0.618033988749895;

// Tramos de tono permitidos [inicio, fin) en grados.
const HUE_BANDS: [number, number][] = [
  [100, 160], // verdes
  [175, 295], // cian, azul, violeta
];
const HUE_SPAN = HUE_BANDS.reduce((acc, [a, b]) => acc + (b - a), 0);

/** Lleva t ∈ [0, 1) a un tono dentro de los tramos fríos. */
function coolHue(t: number): number {
  let x = t * HUE_SPAN;
  for (const [a, b] of HUE_BANDS) {
    if (x < b - a) return a + x;
    x -= b - a;
  }
  return HUE_BANDS[HUE_BANDS.length - 1][1];
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  // h en grados, s y l en [0, 1]
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const hp = (((h % 360) + 360) % 360) / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  let rgb: [number, number, number];
  if (hp < 1) rgb = [c, x, 0];
  else if (hp < 2) rgb = [x, c, 0];
  else if (hp < 3) rgb = [0, c, x];
  else if (hp < 4) rgb = [0, x, c];
  else if (hp < 5) rgb = [x, 0, c];
  else rgb = [c, 0, x];
  const m = l - c / 2;
  return rgb.map((v) => Math.round((v + m) * 255)) as [number, number, number];
}

/** Tono (grados) de una etiqueta; el mismo para izquierdo y derecho. */
export function areaHue(label: number): number {
  const index = label > 100 ? label - 100 : label;
  return coolHue((index * GOLDEN_RATIO) % 1);
}

/** Color RGB (0–255) determinista para una etiqueta de brodmann.nii.gz. */
export function areaColor(label: number): [number, number, number] {
  const right = label > 100;
  const index = right ? label - 100 : label;
  // Alternar saturación evita que dos tonos cercanos se confundan.
  const sat = index % 2 === 0 ? 0.8 : 0.62;
  return hslToRgb(areaHue(label), sat, right ? 0.42 : 0.62);
}

/** El mismo color como CSS `rgb(...)`. */
export function areaColorCss(label: number): string {
  const [r, g, b] = areaColor(label);
  return `rgb(${r}, ${g}, ${b})`;
}

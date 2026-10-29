// Colores de las áreas del atlas (§13), compartidos por AreasPanel y Viewer.
// Valor de etiqueta = índice del atlas (hemisferio izquierdo) o índice + 100 (derecho).
// El tono sale del índice del atlas con el ángulo áureo (colores vecinos bien separados);
// el hemisferio derecho usa el mismo tono un poco más oscuro.

const GOLDEN_ANGLE = 137.508;

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

/** Color RGB (0–255) determinista para una etiqueta de brodmann.nii.gz. */
export function areaColor(label: number): [number, number, number] {
  const right = label > 100;
  const index = right ? label - 100 : label;
  const hue = (index * GOLDEN_ANGLE) % 360;
  // Alternar saturación evita que dos tonos cercanos se confundan.
  const sat = index % 2 === 0 ? 0.75 : 0.6;
  return hslToRgb(hue, sat, right ? 0.45 : 0.6);
}

/** El mismo color como CSS `rgb(...)`. */
export function areaColorCss(label: number): string {
  const [r, g, b] = areaColor(label);
  return `rgb(${r}, ${g}, ${b})`;
}

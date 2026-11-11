/**
 * Superficie triangulada de una máscara binaria (p. ej. el GTV) para la vista 3D.
 *
 * Niivue no trae marching cubes en el navegador, así que se usa *surface nets* (Gibson 1998):
 *   1. Recorte al bounding box de los vóxeles no cero (el GTV ocupa una fracción mínima del volumen).
 *   2. Remuestreo por bloques a ~1 mm (`stride` por eje): cada celda guarda la fracción de vóxeles
 *      dentro (0..1). Ese campo continuo suaviza la escalera de los vóxeles de 0.5 mm.
 *   3. Un vértice por cubo que cruza la isosuperficie 0.5, en el promedio de los cruces de sus aristas.
 *   4. Un quad (dos triángulos) por cada arista de la rejilla con cambio de signo.
 *   5. Suavizado de Taubin (λ/μ), que no encoge la malla como el laplaciano simple.
 *   6. Vóxel → mm con el affine NIfTI (`hdr.affine`, 4×4 por filas), igual que `computeGtvCentroidMM`.
 *   7. Si el volumen con signo sale negativo (affine con determinante negativo) se invierte el orden de
 *      los triángulos: Niivue espera caras CCW hacia fuera para la iluminación y el culling.
 *
 * Sin dependencias ni DOM para poder probarlo con Node.
 */

export interface MaskSurface {
  /** Vértices en mm (mundo, RAS), xyz intercalados. */
  pts: Float32Array;
  /** Índices de triángulos (CCW visto desde fuera). */
  tris: Uint32Array;
  /** Volumen encerrado por la malla, en mm³ (orientativo; la volumetría oficial es la del backend). */
  volumeMM3: number;
}

const ISO = 0.5;

// Las 12 aristas de un cubo como pares de esquinas; esquina k = (k&1, (k>>1)&1, (k>>2)&1).
const CUBE_EDGES: [number, number][] = [
  [0, 1], [2, 3], [4, 5], [6, 7], // eje x
  [0, 2], [1, 3], [4, 6], [5, 7], // eje y
  [0, 4], [1, 5], [2, 6], [3, 7], // eje z
];

/** Paso de remuestreo por eje para acercarse a `targetMM` sin bajar de 1 vóxel. */
export function strideForSpacing(pixDims: ArrayLike<number>, targetMM = 1): [number, number, number] {
  return [0, 1, 2].map((i) => Math.max(1, Math.round(targetMM / Math.abs(pixDims[i] || 1)))) as [
    number,
    number,
    number,
  ];
}

/**
 * @param data   vóxeles en el orden del archivo (x más rápido), como `NVImage.img`
 * @param dims   [nx, ny, nz]
 * @param affine affine NIfTI 4×4 por filas (vóxel → mm)
 * @param stride paso de remuestreo por eje (ver `strideForSpacing`)
 * @param smoothIterations pares de pasos de Taubin
 * @returns null si la máscara está vacía
 */
export function maskSurface(
  data: ArrayLike<number>,
  dims: [number, number, number],
  affine: number[][],
  stride: [number, number, number] = [1, 1, 1],
  smoothIterations = 6,
): MaskSurface | null {
  const [nx, ny, nz] = dims;
  const nxy = nx * ny;

  // 1. Bounding box
  let x0 = nx, y0 = ny, z0 = nz, x1 = -1, y1 = -1, z1 = -1;
  for (let z = 0; z < nz; z++) {
    for (let y = 0; y < ny; y++) {
      const row = z * nxy + y * nx;
      for (let x = 0; x < nx; x++) {
        if (data[row + x] !== 0) {
          if (x < x0) x0 = x;
          if (x > x1) x1 = x;
          if (y < y0) y0 = y;
          if (y > y1) y1 = y;
          if (z < z0) z0 = z;
          if (z > z1) z1 = z;
        }
      }
    }
  }
  if (x1 < 0) return null;

  // 2. Campo de ocupación por bloques, con una celda de margen vacía a cada lado (malla cerrada).
  const [sx, sy, sz] = stride;
  const gx = Math.ceil((x1 - x0 + 1) / sx) + 2;
  const gy = Math.ceil((y1 - y0 + 1) / sy) + 2;
  const gz = Math.ceil((z1 - z0 + 1) / sz) + 2;
  const gxy = gx * gy;
  const field = new Float32Array(gx * gy * gz);
  for (let cz = 1; cz < gz - 1; cz++) {
    for (let cy = 1; cy < gy - 1; cy++) {
      for (let cx = 1; cx < gx - 1; cx++) {
        let inside = 0;
        let total = 0;
        const bx = x0 + (cx - 1) * sx;
        const by = y0 + (cy - 1) * sy;
        const bz = z0 + (cz - 1) * sz;
        for (let z = bz; z < Math.min(bz + sz, nz); z++) {
          for (let y = by; y < Math.min(by + sy, ny); y++) {
            const row = z * nxy + y * nx;
            for (let x = bx; x < Math.min(bx + sx, nx); x++) {
              total++;
              if (data[row + x] !== 0) inside++;
            }
          }
        }
        field[cz * gxy + cy * gx + cx] = total > 0 ? inside / total : 0;
      }
    }
  }

  // 3. Un vértice por cubo con cambio de signo (coordenadas de rejilla).
  const cubeVertex = new Int32Array(gx * gy * gz).fill(-1);
  const verts: number[] = [];
  const corner = new Float32Array(8);
  for (let cz = 0; cz < gz - 1; cz++) {
    for (let cy = 0; cy < gy - 1; cy++) {
      for (let cx = 0; cx < gx - 1; cx++) {
        let mask = 0;
        for (let k = 0; k < 8; k++) {
          const v = field[(cz + ((k >> 2) & 1)) * gxy + (cy + ((k >> 1) & 1)) * gx + cx + (k & 1)];
          corner[k] = v;
          if (v > ISO) mask |= 1 << k;
        }
        if (mask === 0 || mask === 255) continue;
        let px = 0, py = 0, pz = 0, n = 0;
        for (const [a, b] of CUBE_EDGES) {
          const va = corner[a];
          const vb = corner[b];
          if (va > ISO === vb > ISO) continue;
          const t = (ISO - va) / (vb - va);
          px += (a & 1) + t * ((b & 1) - (a & 1));
          py += ((a >> 1) & 1) + t * (((b >> 1) & 1) - ((a >> 1) & 1));
          pz += ((a >> 2) & 1) + t * (((b >> 2) & 1) - ((a >> 2) & 1));
          n++;
        }
        cubeVertex[cz * gxy + cy * gx + cx] = verts.length / 3;
        verts.push(cx + px / n, cy + py / n, cz + pz / n);
      }
    }
  }

  // 4. Quads: la arista p → p+e_a toca los cubos con esquina mínima p, p−e_b, p−e_b−e_c, p−e_c.
  //    (a, b, c) cíclico mantiene la misma orientación relativa en los tres ejes.
  //    Se empieza en 0: la cara entre el margen vacío y la primera celda ocupada también cuenta. Con un
  //    cambio de signo, las coordenadas en b y c son ≥ 1 (el plano 0 es todo margen), así que p − e_b y
  //    p − e_c nunca salen de la rejilla.
  const step = [1, gx, gxy];
  const tris: number[] = [];
  for (let cz = 0; cz < gz - 1; cz++) {
    for (let cy = 0; cy < gy - 1; cy++) {
      for (let cx = 0; cx < gx - 1; cx++) {
        const p = cz * gxy + cy * gx + cx;
        const inP = field[p] > ISO;
        for (let a = 0; a < 3; a++) {
          if (inP === field[p + step[a]] > ISO) continue;
          const sb = step[(a + 1) % 3];
          const sc = step[(a + 2) % 3];
          const q0 = cubeVertex[p];
          const q1 = cubeVertex[p - sb];
          const q2 = cubeVertex[p - sb - sc];
          const q3 = cubeVertex[p - sc];
          if (q0 < 0 || q1 < 0 || q2 < 0 || q3 < 0) continue;
          if (inP) tris.push(q0, q1, q2, q0, q2, q3);
          else tris.push(q0, q2, q1, q0, q3, q2);
        }
      }
    }
  }
  if (tris.length === 0) return null;

  // 5. Taubin: vecinos por las aristas de los triángulos.
  const nv = verts.length / 3;
  const pos = Float64Array.from(verts);
  if (smoothIterations > 0) {
    const neighbors: Set<number>[] = Array.from({ length: nv }, () => new Set<number>());
    for (let i = 0; i < tris.length; i += 3) {
      const [a, b, c] = [tris[i], tris[i + 1], tris[i + 2]];
      neighbors[a].add(b).add(c);
      neighbors[b].add(a).add(c);
      neighbors[c].add(a).add(b);
    }
    const tmp = new Float64Array(pos.length);
    const pass = (factor: number) => {
      for (let v = 0; v < nv; v++) {
        let mx = 0, my = 0, mz = 0;
        const ns = neighbors[v];
        for (const u of ns) {
          mx += pos[u * 3];
          my += pos[u * 3 + 1];
          mz += pos[u * 3 + 2];
        }
        const k = ns.size || 1;
        tmp[v * 3] = pos[v * 3] + factor * (mx / k - pos[v * 3]);
        tmp[v * 3 + 1] = pos[v * 3 + 1] + factor * (my / k - pos[v * 3 + 1]);
        tmp[v * 3 + 2] = pos[v * 3 + 2] + factor * (mz / k - pos[v * 3 + 2]);
      }
      pos.set(tmp);
    };
    for (let i = 0; i < smoothIterations; i++) {
      pass(0.5);
      pass(-0.53);
    }
  }

  // 6. Rejilla → vóxel (centro del bloque) → mm.
  const pts = new Float32Array(nv * 3);
  for (let v = 0; v < nv; v++) {
    const vx = x0 + (pos[v * 3] - 1) * sx + (sx - 1) / 2;
    const vy = y0 + (pos[v * 3 + 1] - 1) * sy + (sy - 1) / 2;
    const vz = z0 + (pos[v * 3 + 2] - 1) * sz + (sz - 1) / 2;
    for (let r = 0; r < 3; r++) {
      pts[v * 3 + r] = affine[r][0] * vx + affine[r][1] * vy + affine[r][2] * vz + affine[r][3];
    }
  }

  // 7. Volumen con signo (teorema de la divergencia) y orientación hacia fuera.
  const triArr = Uint32Array.from(tris);
  let vol6 = 0;
  for (let i = 0; i < triArr.length; i += 3) {
    const a = triArr[i] * 3, b = triArr[i + 1] * 3, c = triArr[i + 2] * 3;
    vol6 +=
      pts[a] * (pts[b + 1] * pts[c + 2] - pts[b + 2] * pts[c + 1]) -
      pts[a + 1] * (pts[b] * pts[c + 2] - pts[b + 2] * pts[c]) +
      pts[a + 2] * (pts[b] * pts[c + 1] - pts[b + 1] * pts[c]);
  }
  if (vol6 < 0) {
    for (let i = 0; i < triArr.length; i += 3) {
      const t = triArr[i + 1];
      triArr[i + 1] = triArr[i + 2];
      triArr[i + 2] = t;
    }
  }
  return { pts, tris: triArr, volumeMM3: Math.abs(vol6) / 6 };
}

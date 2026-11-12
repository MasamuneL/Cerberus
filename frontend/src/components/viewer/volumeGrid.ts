import type { NVImage } from "@niivue/niivue";

/** Niivue modula índices crudos: exige mismas dimensiones y affine, sin registro implícito. */
export function sameVolumeGrid(a: Pick<NVImage, "hdr">, b: Pick<NVImage, "hdr">): boolean {
  const first = a.hdr;
  const second = b.hdr;
  if (!first || !second) return false;
  return [1, 2, 3].every((axis) => first.dims[axis] === second.dims[axis]) &&
    [0, 1, 2].every((row) => [0, 1, 2, 3].every((column) => {
      const x = first.affine[row]?.[column];
      const y = second.affine[row]?.[column];
      return Number.isFinite(x) && Number.isFinite(y) && Math.abs(x - y) <= 1e-4;
    }));
}

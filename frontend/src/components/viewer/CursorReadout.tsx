import type { AreaLabel } from "../../api/types";

/** Lectura en un punto del volumen; `null` = capa no cargada. */
export interface Readout {
  source: "cursor" | "mira";
  mm: [number, number, number];
  base: number | null;
  gtv: number | null;
  area: number | null;
}

function fmtMm(v: number): string {
  return v.toFixed(1).padStart(6, " ");
}

function fmtIntensity(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

interface Props {
  readout: Readout | null;
  lut: Map<number, AreaLabel>;
  areasLayer: boolean;
  gtvLayer: boolean;
}

/**
 * Barra de lectura bajo el lienzo: coordenadas mundo (mm, RAS), hemisferio, área del atlas bajo el
 * cursor, dentro/fuera del GTV e intensidad de la secuencia base.
 */
export default function CursorReadout({ readout, lut, areasLayer, gtvLayer }: Props) {
  if (!readout) {
    return (
      <div className="vw-readout" role="status" aria-live="off">
        <span className="vw-readout-empty">Pasa el cursor sobre un corte o haz clic para leer el punto.</span>
      </div>
    );
  }
  const [x, y, z] = readout.mm;
  // RAS: x negativo = hemisferio izquierdo del paciente.
  const hemi = x < 0 ? "Izq" : "Der";

  let areaText: string;
  if (!areasLayer) areaText = "capa oculta";
  else if (readout.area === null || Math.round(readout.area) <= 0) areaText = "—";
  else {
    const l = lut.get(Math.round(readout.area));
    areaText = l ? `${l.name_es} · ${l.hemisphere}` : `etiqueta ${Math.round(readout.area)}`;
  }

  let gtvText = "—";
  let gtvIn = false;
  if (!gtvLayer) gtvText = "GTV oculto";
  else if (readout.gtv !== null) {
    gtvIn = readout.gtv > 0;
    gtvText = gtvIn ? "dentro del GTV" : "fuera del GTV";
  }

  return (
    <div className="vw-readout" role="status" aria-live="off">
      <span className={`vw-readout-src is-${readout.source}`}>{readout.source === "cursor" ? "Cursor" : "Mira"}</span>
      <span className="vw-readout-seg">
        <span className="vw-k">mm</span>
        <span className="vw-v vw-pre">
          x{fmtMm(x)} y{fmtMm(y)} z{fmtMm(z)}
        </span>
      </span>
      <span className="vw-readout-seg">
        <span className="vw-k">hem</span>
        <span className="vw-v">{hemi}</span>
      </span>
      <span className="vw-readout-seg vw-readout-area" title={areaText}>
        <span className="vw-k">área</span>
        <span className="vw-v">{areaText}</span>
      </span>
      <span className="vw-readout-seg">
        <span className="vw-k">gtv</span>
        <span className={`vw-v${gtvIn ? " is-in-gtv" : ""}`}>{gtvText}</span>
      </span>
      <span className="vw-readout-seg">
        <span className="vw-k">base</span>
        <span className="vw-v">{readout.base === null ? "—" : fmtIntensity(readout.base)}</span>
      </span>
    </div>
  );
}

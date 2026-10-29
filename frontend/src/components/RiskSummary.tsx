import { useState } from "react";
import type { AffectedArea, AreasResult, Domain } from "../api/types";

/**
 * Tarjeta "Funciones en riesgo" (§14, ticket F10).
 *
 * Agrupa las áreas del mapa por dominio funcional y le asigna a cada dominio el nivel más grave de sus áreas
 * según el semáforo del plan:
 *  - Afectado: el área se solapa con el GTV y es elocuente.
 *  - Comprometido: se solapa pero no es elocuente, o es elocuente a ≤ 5 mm.
 *  - En vigilancia: a ≤ margen (10 mm) sin cumplir lo anterior.
 * Rojo, naranja y amarillo son exclusivos del tumor: la gravedad se codifica con forma del icono (● ◐ ○),
 * texto y grosor del borde, nunca con esos colores.
 */

export type Severity = 3 | 2 | 1; // 3 = Afectado, 2 = Comprometido, 1 = En vigilancia

const SEVERITY: Record<Severity, { label: string; icon: string; cls: string }> = {
  3: { label: "Afectado", icon: "●", cls: "sev-3" },
  2: { label: "Comprometido", icon: "◐", cls: "sev-2" },
  1: { label: "En vigilancia", icon: "○", cls: "sev-1" },
};

export const DOMAIN_ES: Record<Domain, string> = {
  lenguaje: "Lenguaje",
  motor: "Motor",
  sensitivo: "Sensitivo",
  vision: "Visión",
  audicion: "Audición",
  memoria: "Memoria",
  ejecutivo: "Ejecutivo",
  emocional: "Emocional",
  autonomico: "Autonómico",
  otro: "Otro",
};

const DOMAIN_ORDER = Object.keys(DOMAIN_ES) as Domain[];

/** Distancia máxima (mm) para que un área elocuente no solapada cuente como "Comprometido". */
const NEAR_ELOQUENT_MM = 5;

export const DISCLAIMER =
  "Estimación educativa basada en un atlas (Talairach-Brodmann) registrado al paciente. No sustituye fMRI, " +
  "tractografía ni mapeo cortical intraoperatorio; con tumores grandes el registro pierde precisión.";

const overlaps = (a: AffectedArea) => a.overlap_gtv_cm3 > 0;

/** Nivel del semáforo de un área (null si queda fuera del margen). */
export function areaSeverity(a: AffectedArea, marginMm: number): Severity | null {
  if (overlaps(a)) return a.eloquent ? 3 : 2;
  if (a.eloquent && a.distance_mm <= NEAR_ELOQUENT_MM) return 2;
  return a.distance_mm <= marginMm ? 1 : null;
}

/** Nombre corto: "BA40" para "Brodmann area 40"; si no, el nombre en español. */
export function shortName(a: AffectedArea): string {
  const m = /^Brodmann area (\d+)$/i.exec(a.name);
  return m ? `BA${m[1]}` : a.name_es;
}

/** Texto del chip: "BA40 izq · 63 %" si se solapa, "BA4 izq · 3.7 mm" si es cercana. */
export function chipText(a: AffectedArea): string {
  const hemi = a.hemisphere === "izquierdo" ? "izq" : "der";
  const pct = a.overlap_gtv_pct < 1 ? "<1" : a.overlap_gtv_pct.toFixed(0);
  // Espacios duros: la cifra y su unidad nunca se separan del hemisferio al hacer salto de línea.
  const metric = overlaps(a) ? `${pct}\u00a0%` : `${a.distance_mm.toFixed(1)}\u00a0mm`;
  return `${shortName(a)}\u00a0${hemi}\u00a0·\u00a0${metric}`;
}

interface Entry {
  area: AffectedArea;
  severity: Severity;
}

interface DomainGroup {
  domain: Domain;
  severity: Severity;
  entries: Entry[];
}

/** Agrupa por dominio, ordena dominios por gravedad y áreas por gravedad y cercanía. */
export function groupByDomain(result: AreasResult): DomainGroup[] {
  const map = new Map<Domain, Entry[]>();
  for (const area of result.areas) {
    const severity = areaSeverity(area, result.margin_mm);
    if (severity === null) continue;
    for (const d of area.domains ?? []) {
      const list = map.get(d) ?? [];
      list.push({ area, severity });
      map.set(d, list);
    }
  }
  const groups: DomainGroup[] = [];
  for (const [domain, entries] of map) {
    entries.sort(
      (x, y) =>
        y.severity - x.severity ||
        y.area.overlap_gtv_pct - x.area.overlap_gtv_pct ||
        x.area.distance_mm - y.area.distance_mm,
    );
    groups.push({ domain, severity: entries[0].severity, entries });
  }
  groups.sort(
    (a, b) =>
      b.severity - a.severity ||
      b.entries.length - a.entries.length ||
      DOMAIN_ORDER.indexOf(a.domain) - DOMAIN_ORDER.indexOf(b.domain),
  );
  return groups;
}

interface Props {
  result: AreasResult | null;
  focusedLabel: number | null;
  onFocusLabel: (label: number | null) => void;
}

/** Chips visibles por dominio antes de "+N más". */
const CHIP_LIMIT = 8;

export default function RiskSummary({ result, focusedLabel, onFocusLabel }: Props) {
  const [expanded, setExpanded] = useState<Partial<Record<Domain, boolean>>>({});
  // Resultados previos a B12 no traen `domains` (o vienen vacíos): se pide volver a mapear.
  const domainsMissing = !!result && result.areas.length > 0 && result.areas.every((a) => !a.domains?.length);
  const groups = result && !domainsMissing ? groupByDomain(result) : [];

  return (
    <div className="risk-wrap">
      {result && (
        <section className="risk-summary" aria-labelledby="risk-title">
          <header className="risk-head">
            <h3 id="risk-title">Funciones en riesgo</h3>
            <ul className="risk-legend" aria-label="Leyenda del semáforo">
              {([3, 2, 1] as Severity[]).map((s) => (
                <li key={s} className={SEVERITY[s].cls}>
                  <span className="risk-icon" aria-hidden="true">{SEVERITY[s].icon}</span>
                  {SEVERITY[s].label}
                </li>
              ))}
            </ul>
          </header>

          {domainsMissing && (
            <p className="note risk-empty">Dominios no disponibles: vuelve a mapear.</p>
          )}
          {!domainsMissing && groups.length === 0 && <p className="note risk-empty">Ningún dominio en riesgo.</p>}

          {groups.length > 0 && (
            <ul className="risk-list">
              {groups.map((g) => {
                const sev = SEVERITY[g.severity];
                const open = !!expanded[g.domain];
                // La lista viene ordenada por gravedad: si se recorta, nunca se oculta un área enfocada.
                const shown = open
                  ? g.entries
                  : g.entries.filter((e, i) => i < CHIP_LIMIT || e.area.label === focusedLabel);
                const hiddenCount = g.entries.length - shown.length;
                return (
                  <li key={g.domain} className={`risk-domain ${sev.cls}`}>
                    <div className="risk-domain-head">
                      <span className="risk-icon" aria-hidden="true">{sev.icon}</span>
                      <span className="risk-domain-name">{DOMAIN_ES[g.domain]}</span>
                      <span className="risk-level">{sev.label}</span>
                    </div>
                    <div className="risk-chips" role="group" aria-label={`Áreas de ${DOMAIN_ES[g.domain]}`}>
                      {shown.map(({ area, severity }) => {
                        const pressed = focusedLabel === area.label;
                        return (
                          <button
                            key={area.label}
                            type="button"
                            className={`risk-chip ${SEVERITY[severity].cls}${pressed ? " focused" : ""}`}
                            aria-pressed={pressed}
                            title={`${area.name_es} (${area.hemisphere}) · ${SEVERITY[severity].label}. Clic para enfocar en el visor.`}
                            onClick={() => onFocusLabel(pressed ? null : area.label)}
                          >
                            {chipText(area)}
                            <span className="sr-only">, {SEVERITY[severity].label.toLowerCase()}</span>
                          </button>
                        );
                      })}
                      {(hiddenCount > 0 || open) && g.entries.length > CHIP_LIMIT && (
                        <button
                          type="button"
                          className="risk-more"
                          aria-expanded={open}
                          onClick={() => setExpanded((x) => ({ ...x, [g.domain]: !open }))}
                        >
                          {open ? "Mostrar menos" : `+${hiddenCount} más`}
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}
      <p className="disclaimer">{DISCLAIMER}</p>
    </div>
  );
}

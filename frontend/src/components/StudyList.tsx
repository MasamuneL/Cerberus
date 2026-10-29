import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { getLongitudinal } from "../api/client";
import type { LongitudinalPoint, Study } from "../api/types";

export interface StudyKey {
  patient: string;
  timepoint: string;
}

interface Props {
  studies: Study[];
  selected: StudyKey | null;
  onSelect: (key: StudyKey) => void;
  loading?: boolean;
  error?: string | null;
}

// --- Serie longitudinal por paciente (GTV cm³ por tiempo + tendencia) ---
// Una sola petición por paciente da el volumen de cada tiempo y el cambio vs t0. Se cachea a nivel de
// módulo con la lista de tiempos en la clave, para que un estudio recién subido fuerce a recalcular.

type Series = LongitudinalPoint[] | null; // null = sin datos (404 o error): no se muestra nada

const MAX_CONCURRENT = 3;
const seriesCache = new Map<string, Promise<Series>>();
let running = 0;
const queue: (() => void)[] = [];

function limited<T>(task: () => Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const run = () => {
      running++;
      task()
        .then(resolve, reject)
        .finally(() => {
          running--;
          queue.shift()?.();
        });
    };
    if (running < MAX_CONCURRENT) run();
    else queue.push(run);
  });
}

function loadSeries(patient: string, timepoints: string[]): Promise<Series> {
  const key = `${patient}|${timepoints.join(",")}`;
  let p = seriesCache.get(key);
  if (!p) {
    p = limited(() => getLongitudinal(patient)).catch(() => null);
    seriesCache.set(key, p);
  }
  return p;
}

const MINUS = "−";
const fmtPct = (x: number) => `${x < 0 ? MINUS : x > 0 ? "+" : ""}${Math.abs(x).toFixed(0)} %`;

function Trend({ series }: { series: LongitudinalPoint[] }) {
  const first = series[0];
  const last = series[series.length - 1];
  const pct = last.change_vs_t0_pct;
  const arrow = pct < 0 ? "↓" : pct > 0 ? "↑" : "→";
  const label = `Cambio del GTV ${first.timepoint} → ${last.timepoint}: ${fmtPct(pct)}`;
  return (
    <span className="trend num" title={label} aria-label={label}>
      {arrow} {fmtPct(pct)}
    </span>
  );
}

function SkeletonList() {
  return (
    <div className="study-list" aria-busy="true" aria-label="Cargando estudios">
      {[2, 1, 2].map((n, g) => (
        <section key={g} className="study-group" aria-hidden="true">
          <div className="study-group-head">
            <span className="skeleton" style={{ width: "40%", height: "0.7rem" }} />
          </div>
          {Array.from({ length: n }, (_, i) => (
            <div key={i} className="study-item study-item-skeleton">
              <span className="skeleton" style={{ width: "1.4rem" }} />
              <span className="skeleton" style={{ width: "3.5rem", justifySelf: "end" }} />
              <span className="skeleton" style={{ width: "4rem" }} />
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

export default function StudyList({ studies, selected, onSelect, loading, error }: Props) {
  const listRef = useRef<HTMLDivElement>(null);
  const [series, setSeries] = useState<Record<string, Series | undefined>>({});

  // Pacientes ordenados, cada uno con sus tiempos ordenados.
  const groups = useMemo(() => {
    const m = new Map<string, Study[]>();
    for (const s of studies) m.set(s.patient, [...(m.get(s.patient) ?? []), s]);
    return [...m.keys()].sort().map((p) => ({
      patient: p,
      items: m.get(p)!.slice().sort((a, b) => a.timepoint.localeCompare(b.timepoint)),
    }));
  }, [studies]);

  useEffect(() => {
    let cancelled = false;
    for (const { patient, items } of groups) {
      if (!items.some((s) => s.has_gtv)) continue;
      loadSeries(
        patient,
        items.map((s) => s.timepoint),
      ).then((data) => {
        if (!cancelled) setSeries((prev) => ({ ...prev, [patient]: data }));
      });
    }
    return () => {
      cancelled = true;
    };
  }, [groups]);

  // Flechas ↑/↓ (e Inicio/Fin) recorren los estudios; Enter/Espacio los abre (botón nativo).
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const buttons = [...(listRef.current?.querySelectorAll<HTMLButtonElement>("button.study-item") ?? [])];
    if (buttons.length === 0) return;
    e.preventDefault();
    const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
    let next: number;
    if (e.key === "Home") next = 0;
    else if (e.key === "End") next = buttons.length - 1;
    else if (i === -1) next = 0;
    else next = (i + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next].focus();
  };

  if (loading) return <SkeletonList />;
  if (error) return <p className="error">No se pudieron cargar los estudios: {error}</p>;
  if (studies.length === 0) return <p className="placeholder">No hay estudios en Data/</p>;

  return (
    <div className="study-list" ref={listRef} onKeyDown={onKeyDown}>
      {groups.map(({ patient: p, items }) => {
        const data = series[p];
        const pending = data === undefined;
        const headingId = `study-group-${p}`;
        return (
          <section key={p} className="study-group" aria-labelledby={headingId}>
            <div className="study-group-head">
              <h3 id={headingId}>Paciente {p}</h3>
              {data && data.length >= 2 && <Trend series={data} />}
            </div>
            <ul>
              {items.map((s) => {
                const isActive = selected?.patient === p && selected.timepoint === s.timepoint;
                const vol = s.has_gtv ? data?.find((pt) => pt.timepoint === s.timepoint)?.gtv_cm3 : undefined;
                return (
                  <li key={s.timepoint}>
                    <button
                      type="button"
                      className={`study-item${isActive ? " active" : ""}`}
                      aria-current={isActive ? "true" : undefined}
                      onClick={() => onSelect({ patient: p, timepoint: s.timepoint })}
                    >
                      <span className="study-tp">{s.timepoint}</span>
                      <span className="study-vol num">
                        {vol !== undefined ? (
                          <span title="Volumen del GTV">{vol.toFixed(1)} cm³</span>
                        ) : pending && s.has_gtv ? (
                          <span className="skeleton" style={{ width: "3.5rem", marginLeft: "auto" }} aria-hidden="true" />
                        ) : null}
                      </span>
                      <span className="badges">
                        {s.has_gtv && (
                          <span className="badge badge-gtv" title="Máscara GTV disponible">
                            GTV
                          </span>
                        )}
                        {s.has_segmentation && (
                          <span className="badge badge-seg" title="Segmentación automática disponible">
                            Seg
                          </span>
                        )}
                        {s.has_areas && (
                          <span className="badge badge-areas" title="Mapa de áreas disponible">
                            Áreas
                          </span>
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

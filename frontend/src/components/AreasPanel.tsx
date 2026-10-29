import { Fragment, useEffect, useRef, useState } from "react";
import { ApiError, getAreas, startAreaMapping } from "../api/client";
import type { AffectedArea, AreasResult, JobStatus, StudyDetail } from "../api/types";
import { useJob } from "../hooks/useJob";
import { areaColorCss } from "./areaColors";

interface Props {
  study: StudyDetail;
  onCompleted: (r: AreasResult) => void;
  onFocusLabel: (label: number | null) => void;
  focusedLabel: number | null;
  /** Resultado previo leído al abrir el estudio (null si no hay o falló). */
  onLoaded?: (r: AreasResult | null) => void;
}

const TERMINAL = new Set(["complete", "failed", "not_found"]);

const DISCLAIMER =
  "Estimación educativa basada en un atlas (Talairach-Brodmann) registrado al paciente. No sustituye fMRI, " +
  "tractografía ni mapeo cortical intraoperatorio; con tumores grandes el registro pierde precisión.";

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  return e instanceof Error ? e.message : String(e);
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" });
}

/** Texto en español del estado del job. */
function statusText(s: JobStatus | null, elapsed: number): string {
  if (!s) return "Enviando…";
  switch (s.status) {
    case "queued":
      return `En cola… (${elapsed} s)`;
    case "in_progress":
      return `Procesando… (${elapsed} s)`;
    case "complete":
      return "Completado";
    case "failed":
      return `Falló: ${s.error ?? "error desconocido"}`;
    case "not_found":
      return "Job no encontrado";
  }
}

const hemiShort = (h: AffectedArea["hemisphere"]) => (h === "izquierdo" ? "Izq." : "Der.");

interface TableProps {
  rows: AffectedArea[];
  showWt: boolean;
  focusedLabel: number | null;
  onFocusLabel: (label: number | null) => void;
}

function AreasTable({ rows, showWt, focusedLabel, onFocusLabel }: TableProps) {
  if (rows.length === 0) return <p className="placeholder">Ninguna.</p>;
  return (
    <table className="data-table areas-table">
      <thead>
        <tr>
          <th colSpan={showWt ? 6 : 5}>Área · Hemisferio · % GTV · cm³ · mm {showWt && "· % WT"}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => {
          const focused = focusedLabel === a.label;
          const toggleFocus = () => onFocusLabel(focused ? null : a.label);
          return (
            <Fragment key={a.label}>
              <tr
                className={`area-row${focused ? " focused" : ""}`}
                onClick={toggleFocus}
                title={focused ? "Clic para quitar el enfoque" : "Clic para enfocar en el visor"}
              >
                <th scope="row" className="area-name-cell">
                  <div className="area-name">
                    <i className="swatch" style={{ background: areaColorCss(a.label) }} />
                    <span>{a.name_es}</span>
                    {a.eloquent && <span className="badge badge-eloquent">Elocuente</span>}
                  </div>
                </th>
                <td title={a.hemisphere} className="cell-numeric">{hemiShort(a.hemisphere)}</td>
                <td className="cell-numeric">{a.overlap_gtv_pct.toFixed(1)}</td>
                <td className="cell-numeric">{a.overlap_gtv_cm3.toFixed(2)}</td>
                <td className="cell-numeric">{a.distance_mm > 0 ? a.distance_mm.toFixed(1) : "—"}</td>
                {showWt && <td className="cell-numeric">{a.overlap_wt_pct !== null ? a.overlap_wt_pct.toFixed(1) : "—"}</td>}
              </tr>
              {a.functions.length > 0 && (
                <tr className={`area-chips-row${focused ? " focused" : ""}`} onClick={toggleFocus}>
                  <td colSpan={showWt ? 6 : 5}>
                    <div className="chips">
                      {a.functions.map((f) => (
                        <span key={f} className="chip">
                          {f}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

export default function AreasPanel({ study, onCompleted, onFocusLabel, focusedLabel, onLoaded }: Props) {
  const { patient, timepoint } = study;
  const [result, setResult] = useState<AreasResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const handledJobRef = useRef<string | null>(null);
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;

  const { status, error: pollError } = useJob(jobId);
  const running = jobId !== null && !pollError && (!status || !TERMINAL.has(status.status));
  const elapsed = startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : 0;

  // Resultado previo (404 = todavía no hay mapa de áreas). Se reinicia al cambiar de estudio
  // y se reporta a App para que el visor pueda pintar el overlay.
  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setLoadError(null);
    setLoading(true);
    setJobId(null);
    setStartError(null);
    setStartedAt(null);
    handledJobRef.current = null;
    getAreas(patient, timepoint)
      .then((r) => {
        if (cancelled) return;
        setResult(r);
        onLoadedRef.current?.(r);
      })
      .catch((e) => {
        if (cancelled) return;
        onLoadedRef.current?.(null);
        if (e instanceof ApiError && e.status === 404) return;
        setLoadError(`No se pudo leer el mapa de áreas: ${errMsg(e)}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [patient, timepoint]);

  // Cronómetro mientras el job corre.
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  // Al completarse: recarga el resultado y avisa a App (una sola vez por job).
  useEffect(() => {
    if (!jobId || status?.status !== "complete" || handledJobRef.current === jobId) return;
    handledJobRef.current = jobId;
    let cancelled = false;
    getAreas(patient, timepoint)
      .then((r) => {
        if (cancelled) return;
        setResult(r);
        setLoadError(null);
        onCompletedRef.current(r);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(`No se pudo leer el mapa de áreas: ${errMsg(e)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, status?.status, patient, timepoint]);

  const start = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const { job_id } = await startAreaMapping(patient, timepoint);
      setStartedAt(Date.now());
      setNow(Date.now());
      setJobId(job_id);
    } catch (e) {
      setStartError(errMsg(e));
    } finally {
      setStarting(false);
    }
  };

  const busy = starting || running;
  const statusClass =
    status?.status === "failed" || status?.status === "not_found"
      ? "error"
      : status?.status === "complete"
        ? "ok"
        : "";

  // El backend ya ordena: primero las solapadas y luego las cercanas.
  const affected = result ? result.areas.filter((a) => a.overlap_gtv_cm3 > 0) : [];
  const nearby = result ? result.areas.filter((a) => a.overlap_gtv_cm3 <= 0) : [];
  const showWt = result ? result.areas.some((a) => a.overlap_wt_pct !== null) : false;

  return (
    <section className="panel areas">
      <h2>Áreas de Brodmann</h2>
      <button
        type="button"
        className="btn-primary"
        disabled={busy || loading || !study.has_gtv}
        onClick={() => void start()}
      >
        {busy ? "Mapeando…" : result ? "Volver a mapear" : "Mapear áreas afectadas"}
      </button>
      {!study.has_gtv && <p className="note">Se necesita GTV para mapear áreas.</p>}

      {startError && (
        <div className="alert" role="alert">
          {startError}
        </div>
      )}
      {jobId && !pollError && <p className={`job-status ${statusClass}`}>{statusText(status, elapsed)}</p>}
      {pollError && (
        <div className="alert" role="alert">
          No se pudo consultar el job: {pollError}
        </div>
      )}
      {running && <p className="note">El registro a MNI tarda 1–3 min.</p>}

      {loading && <p className="placeholder">Buscando mapa de áreas previo…</p>}
      {loadError && <p className="error">{loadError}</p>}
      {!loading && !result && !loadError && !jobId && study.has_gtv && (
        <p className="placeholder">Este estudio todavía no tiene mapa de áreas.</p>
      )}

      {result && (
        <>
          <h3>Afectadas por el GTV</h3>
          <AreasTable rows={affected} showWt={showWt} focusedLabel={focusedLabel} onFocusLabel={onFocusLabel} />

          <h3>Cercanas (≤ {result.margin_mm} mm)</h3>
          <AreasTable rows={nearby} showWt={showWt} focusedLabel={focusedLabel} onFocusLabel={onFocusLabel} />

          <p className="note">Clic en una fila para enfocar esa área en el visor.</p>

          {result.warnings.length > 0 && (
            <ul className="warnings">
              {result.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}

          <p className="note">
            Atlas: {result.atlas}
            <br />
            Registro: {result.registration}
            <br />
            Secuencia de referencia: {result.reference_sequence} · {fmtDate(result.created_at)}
          </p>
        </>
      )}

      <p className="disclaimer">{DISCLAIMER}</p>
    </section>
  );
}

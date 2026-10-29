import { useEffect, useRef, useState } from "react";
import { ApiError, getSegmentation, startSegmentation } from "../api/client";
import type { JobStatus, SegmentationResult, StudyDetail } from "../api/types";
import { useJob } from "../hooks/useJob";

interface Props {
  study: StudyDetail;
  onCompleted: () => void;
  /** Avisa cuando una segmentación empieza o termina (indicador en la pestaña). */
  onBusyChange?: (busy: boolean) => void;
}

const TERMINAL = new Set(["complete", "failed", "not_found"]);

const fmt = (x: number, d = 2) => x.toFixed(d);

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

export default function SegmentationPanel({ study, onCompleted, onBusyChange }: Props) {
  const { patient, timepoint } = study;
  const [result, setResult] = useState<SegmentationResult | null>(null);
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
  const onBusyChangeRef = useRef(onBusyChange);
  onBusyChangeRef.current = onBusyChange;

  const { status, error: pollError } = useJob(jobId);
  const running = jobId !== null && !pollError && (!status || !TERMINAL.has(status.status));
  const elapsed = startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : 0;

  // Resultado previo (404 = todavía no hay segmentación). Se reinicia al cambiar de estudio.
  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setLoadError(null);
    setLoading(true);
    setJobId(null);
    setStartError(null);
    setStartedAt(null);
    handledJobRef.current = null;
    getSegmentation(patient, timepoint)
      .then((r) => {
        if (!cancelled) setResult(r);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) return;
        setLoadError(`No se pudo leer la segmentación: ${errMsg(e)}`);
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
    getSegmentation(patient, timepoint)
      .then((r) => {
        if (cancelled) return;
        setResult(r);
        setLoadError(null);
        onCompletedRef.current();
      })
      .catch((e) => {
        if (!cancelled) setLoadError(`No se pudo leer la segmentación: ${errMsg(e)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, status?.status, patient, timepoint]);

  const start = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const { job_id } = await startSegmentation(patient, timepoint);
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
  useEffect(() => {
    onBusyChangeRef.current?.(busy);
  }, [busy]);
  const statusClass =
    status?.status === "failed" || status?.status === "not_found"
      ? "error"
      : status?.status === "complete"
        ? "ok"
        : "";

  return (
    <section className="panel segmentation">
      <h2>Segmentación MONAI</h2>
      <button type="button" className="btn-primary" disabled={busy || loading} onClick={() => void start()}>
        {busy ? "Segmentando…" : result ? "Volver a segmentar" : "Segmentar con MONAI"}
      </button>

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
      {running && <p className="note">Una segmentación real tarda entre 15 y 60 s.</p>}

      {loading && <p className="placeholder">Buscando segmentación previa…</p>}
      {loadError && <p className="error">{loadError}</p>}
      {!loading && !result && !loadError && !jobId && (
        <p className="placeholder">Este estudio todavía no tiene segmentación.</p>
      )}

      {result && (
        <>
          <h3>Volúmenes</h3>
          <table className="data-table">
            <tbody>
              <tr><th>WT (núcleo + edema)</th><td>{fmt(result.volumes_cm3.wt)} cm³</td></tr>
              <tr><th>TC (núcleo)</th><td>{fmt(result.volumes_cm3.tc)} cm³</td></tr>
              <tr><th>ET (realce)</th><td>{fmt(result.volumes_cm3.et)} cm³</td></tr>
            </tbody>
          </table>

          <h3>Dice vs GTV</h3>
          {result.dice_vs_gtv ? (
            <>
              <table className="data-table">
                <tbody>
                  <tr><th>TC</th><td>{fmt(result.dice_vs_gtv.tc, 3)}</td></tr>
                  <tr><th>WT</th><td>{fmt(result.dice_vs_gtv.wt, 3)}</td></tr>
                </tbody>
              </table>
              <p className="note">Dice inter-observador típico en GBM: 0.72–0.88</p>
            </>
          ) : (
            <p className="placeholder">Sin GTV: no se calcula Dice.</p>
          )}

          <h3>Canales usados</h3>
          <table className="data-table">
            <thead>
              <tr><th>Canal del modelo</th><th>Secuencia</th></tr>
            </thead>
            <tbody>
              {result.channels.map((c) => (
                <tr key={c.model_channel}>
                  <th>{c.model_channel}</th>
                  <td>{c.sequence ?? "— (ceros)"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {result.warnings.length > 0 && (
            <ul className="warnings">
              {result.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}

          <div className="legend seg-legend">
            <span><i className="swatch" style={{ background: "#ffdc00" }} /> Edema</span>
            <span><i className="swatch" style={{ background: "#ff8c00" }} /> Núcleo</span>
            <span><i className="swatch" style={{ background: "#ff0000" }} /> Realce</span>
          </div>
          <p className="note">
            Dispositivo: {result.device} · {fmtDate(result.created_at)}
          </p>
        </>
      )}
    </section>
  );
}

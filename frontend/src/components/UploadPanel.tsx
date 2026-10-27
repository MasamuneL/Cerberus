import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  confirmUpload,
  deleteUpload,
  getUpload,
  isUploadCreated,
  uploadFile,
} from "../api/client";
import type { Study, UploadManifest } from "../api/types";

// Claves de SEQ_INFO (docs/PLAN_MVP.md §6) con etiqueta en español.
const SEQUENCES: { key: string; label: string }[] = [
  { key: "t1gd", label: "T1 con gadolinio (t1gd)" },
  { key: "t1eg", label: "T1 eco de gradiente (t1eg)" },
  { key: "t1tse", label: "T1 turbo spin eco (t1tse)" },
  { key: "t2tse", label: "T2 turbo spin eco (t2tse)" },
  { key: "t2star", label: "T2* (t2star)" },
  { key: "flair", label: "FLAIR (flair)" },
  { key: "adc", label: "Mapa ADC (adc)" },
  { key: "ct", label: "Tomografía (ct)" },
  { key: "rtdose", label: "Dosis de radioterapia (rtdose)" },
  { key: "brain_mask", label: "Máscara cerebral (brain_mask)" },
  { key: "gtv", label: "GTV (gtv)" },
];

const PATIENT_RE = /^\d{3}$/;
const TIMEPOINT_RE = /^t\d{1,2}$/;
const POLL_MS = 2000;

const errText = (e: unknown) =>
  e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e);

const kindOf = (f: File | null): "nifti" | "zip" | null => {
  if (!f) return null;
  const n = f.name.toLowerCase();
  if (n.endsWith(".nii") || n.endsWith(".nii.gz")) return "nifti";
  if (n.endsWith(".zip")) return "zip";
  return null;
};

const fmt = (xs: number[] | null, digits = 0) =>
  xs ? xs.map((x) => x.toFixed(digits)).join(" × ") : "—";

interface Props {
  onUploaded: (study: Study) => void;
  onClose?: () => void;
}

export default function UploadPanel({ onUploaded, onClose }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [patient, setPatient] = useState("");
  const [timepoint, setTimepoint] = useState("");
  const [sequence, setSequence] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<UploadManifest | null>(null);
  const [mapping, setMapping] = useState<Record<number, string>>({});
  const fileInput = useRef<HTMLInputElement>(null);

  const kind = kindOf(file);
  const errors: string[] = [];
  if (!file) errors.push("Selecciona un archivo.");
  else if (!kind) errors.push("El archivo debe ser .nii, .nii.gz o .zip.");
  if (!PATIENT_RE.test(patient)) errors.push("Paciente: exactamente 3 dígitos (p. ej. 001).");
  if (!TIMEPOINT_RE.test(timepoint)) errors.push("Timepoint: «t» seguida de 1 o 2 dígitos (p. ej. t0).");
  if (kind === "nifti" && !sequence) errors.push("Elige la secuencia del volumen.");
  const valid = errors.length === 0;

  // Polling del manifest mientras la conversión DICOM está en curso.
  useEffect(() => {
    if (!uploadId) return;
    let cancelled = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const m = await getUpload(uploadId);
        if (cancelled) return;
        setManifest(m);
        if (m.status === "processing") {
          timer = window.setTimeout(tick, POLL_MS);
        } else if (m.status === "ready") {
          const init: Record<number, string> = {};
          for (const s of m.series) init[s.index] = s.converted ? (s.suggested_sequence ?? "") : "";
          setMapping(init);
        }
      } catch (e) {
        if (!cancelled) setError(`Error consultando la subida: ${errText(e)}`);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [uploadId]);

  const reset = () => {
    setFile(null);
    setSequence("");
    setUploadId(null);
    setManifest(null);
    setMapping({});
    setError(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!valid || !file || busy) return;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await uploadFile(file, patient, timepoint, kind === "nifti" ? sequence : undefined);
      if (isUploadCreated(res)) {
        setManifest(null);
        setUploadId(res.upload_id);
      } else {
        setSuccess(`Volumen guardado en ${res.patient}/${res.timepoint}`);
        reset();
        onUploaded(res);
      }
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const selected = Object.entries(mapping).filter(([, v]) => v);
  const duplicates = useMemo(() => {
    const count = new Map<string, number>();
    for (const v of Object.values(mapping)) if (v) count.set(v, (count.get(v) ?? 0) + 1);
    return [...count].filter(([, n]) => n > 1).map(([k]) => k);
  }, [mapping]);
  const canConfirm = selected.length > 0 && duplicates.length === 0 && !busy;

  const confirm = async () => {
    if (!uploadId || !canConfirm) return;
    setBusy(true);
    setError(null);
    try {
      const study = await confirmUpload(uploadId, {
        patient,
        timepoint,
        mapping: Object.fromEntries(selected.map(([k, v]) => [String(k), v])),
      });
      setSuccess(`Estudio guardado en ${study.patient}/${study.timepoint}`);
      reset();
      onUploaded(study);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (uploadId) {
      setBusy(true);
      try {
        await deleteUpload(uploadId);
      } catch {
        // la limpieza del staging es best-effort
      } finally {
        setBusy(false);
      }
    }
    reset();
  };

  const inZipFlow = uploadId !== null;

  return (
    <section className="upload-panel">
      <div className="upload-head">
        <h2>Subir estudio</h2>
        {onClose && (
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cerrar
          </button>
        )}
      </div>
      <p className="upload-notice">
        Los archivos DICOM se anonimizan y se eliminan tras convertirse; no subas imágenes con texto
        identificable quemado.
      </p>

      <form className="upload-form" onSubmit={submit}>
        <label>
          Archivo (.nii, .nii.gz o .zip DICOM)
          <input
            ref={fileInput}
            type="file"
            accept=".nii,.nii.gz,.zip"
            disabled={inZipFlow || busy}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          Paciente
          <input
            value={patient}
            placeholder="001"
            maxLength={3}
            disabled={inZipFlow || busy}
            onChange={(e) => setPatient(e.target.value.trim())}
          />
        </label>
        <label>
          Timepoint
          <input
            value={timepoint}
            placeholder="t0"
            maxLength={3}
            disabled={inZipFlow || busy}
            onChange={(e) => setTimepoint(e.target.value.trim())}
          />
        </label>
        {kind === "nifti" && (
          <label>
            Secuencia
            <select value={sequence} disabled={busy} onChange={(e) => setSequence(e.target.value)}>
              <option value="">— elige —</option>
              {SEQUENCES.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        )}
        {!inZipFlow && (
          <>
            {(file || patient || timepoint) && errors.length > 0 && (
              <ul className="upload-errors">
                {errors.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            )}
            <button type="submit" disabled={!valid || busy}>
              {busy ? "Subiendo…" : "Subir"}
            </button>
          </>
        )}
      </form>

      {inZipFlow && (!manifest || manifest.status === "processing") && (
        <div className="upload-status">
          <p className="placeholder">Convirtiendo DICOM…</p>
          <button type="button" className="btn-secondary" onClick={() => void cancel()} disabled={busy}>
            Cancelar
          </button>
        </div>
      )}

      {inZipFlow && manifest?.status === "failed" && (
        <div className="upload-status">
          <p className="error">La conversión falló: {manifest.error ?? "error desconocido"}</p>
          <button type="button" className="btn-secondary" onClick={() => void cancel()} disabled={busy}>
            Cancelar
          </button>
        </div>
      )}

      {inZipFlow && manifest?.status === "ready" && (
        <div className="upload-series">
          <table>
            <thead>
              <tr>
                <th>Índice</th>
                <th>Modalidad</th>
                <th>Descripción</th>
                <th>Nº archivos</th>
                <th>Shape</th>
                <th>Spacing (mm)</th>
                <th>Convertida</th>
                <th>Secuencia</th>
              </tr>
            </thead>
            <tbody>
              {manifest.series.map((s) => (
                <tr key={s.index} className={s.converted ? "" : "muted"}>
                  <td>{s.index}</td>
                  <td>{s.modality}</td>
                  <td>{s.description || "—"}</td>
                  <td>{s.n_files}</td>
                  <td>{fmt(s.shape)}</td>
                  <td>{fmt(s.spacing_mm, 2)}</td>
                  <td>{s.converted ? "Sí" : "No"}</td>
                  <td>
                    <select
                      value={mapping[s.index] ?? ""}
                      disabled={!s.converted || busy}
                      onChange={(e) => setMapping((m) => ({ ...m, [s.index]: e.target.value }))}
                    >
                      <option value="">Ignorar</option>
                      {SEQUENCES.map((q) => (
                        <option key={q.key} value={q.key}>
                          {q.label}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {duplicates.length > 0 && (
            <p className="error">Secuencias repetidas: {duplicates.join(", ")}</p>
          )}
          {selected.length === 0 && <p className="placeholder">Asigna al menos una serie.</p>}
          <div className="upload-actions">
            <button type="button" onClick={() => void confirm()} disabled={!canConfirm}>
              {busy ? "Guardando…" : "Confirmar"}
            </button>
            <button type="button" className="btn-secondary" onClick={() => void cancel()} disabled={busy}>
              Cancelar
            </button>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}
      {success && <p className="upload-success">{success}</p>}
    </section>
  );
}

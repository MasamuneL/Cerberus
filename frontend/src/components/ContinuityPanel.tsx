import { useEffect, useState } from "react";
import { ApiError, getJob, getUpload } from "../api/client";
import { CONTINUITY_EVENT, forgetReference, readReferences, type PendingReference } from "../api/continuity";
import type { JobStatus, UploadManifest } from "../api/types";
import { useJob } from "../hooks/useJob";

interface RestoredResource { reference: PendingReference; job?: JobStatus; upload?: UploadManifest }
interface Props { onResumeUpload: (id: string) => void; onCompleted: () => void }
const JOB_LABEL = { segmentation: "Segmentación", areas: "Mapeo de áreas", upload: "Ingesta" };
const STATUS_LABEL = { queued: "en cola", in_progress: "en curso", complete: "completado", failed: "fallido", not_found: "no disponible" };

function RecoveredJob({ resource, onCompleted }: { resource: RestoredResource; onCompleted: () => void }) {
  const { status, error } = useJob(resource.reference.id);
  const job = status ?? resource.job;
  useEffect(() => {
    if (status?.status === "complete") onCompleted();
  }, [status?.status, onCompleted]);
  return <li>
    <span>{JOB_LABEL[resource.reference.kind]}: {job ? STATUS_LABEL[job.status] : "comprobando"}</span>{" "}
    {error && <span role="alert">No se pudo actualizar el trabajo. Vuelve a comprobar las referencias.</span>}
    <button type="button" className="btn-secondary" onClick={() => forgetReference(resource.reference.id)}>Ocultar trabajo</button>
  </li>;
}

/** Nunca muestra datos de una referencia guardada sin volver a comprobar acceso en la API. */
export default function ContinuityPanel({ onResumeUpload, onCompleted }: Props) {
  const [references, setReferences] = useState(readReferences);
  const [resources, setResources] = useState<RestoredResource[]>([]);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const update = () => setReferences(readReferences());
    window.addEventListener(CONTINUITY_EVENT, update);
    return () => window.removeEventListener(CONTINUITY_EVENT, update);
  }, []);
  useEffect(() => {
    let cancelled = false;
    setResources([]);
    setError(false);
    void Promise.all(references.map(async (reference): Promise<RestoredResource | null> => {
      try {
        if (reference.kind === "upload") return { reference, upload: await getUpload(reference.id) };
        const job = await getJob(reference.id);
        return job.status === "not_found" ? null : { reference, job };
      } catch (failure) {
        if (!(failure instanceof ApiError && [401, 403, 404].includes(failure.status)) && !cancelled) setError(true);
        return null;
      }
    })).then(restored => {
      if (!cancelled) setResources(restored.filter((value): value is RestoredResource => value !== null));
    });
    return () => { cancelled = true; };
  }, [references, attempt]);
  if (!resources.length && !error) return null;
  return <section className="continuity-panel" aria-label="Continuidad de trabajos">
    <h2>Trabajos recuperados</h2>
    <p>Acceso comprobado de nuevo. Los resultados terminados están disponibles en el catálogo.</p>
    <ul>{resources.map(resource => resource.upload ? <li key={resource.reference.id}>
      <span>Ingesta: {resource.upload.status === "ready" ? "lista para revisar" : resource.upload.status === "processing" ? "en curso" : "fallida"}</span>{" "}
      <button type="button" className="btn-secondary" onClick={() => onResumeUpload(resource.reference.id)}>Reanudar ingesta</button>
    </li> : <RecoveredJob key={resource.reference.id} resource={resource} onCompleted={onCompleted} />)}</ul>
    {error && <p role="alert">No se pudieron comprobar algunos trabajos. Sus referencias se conservan para reintentar.</p>}
    <button type="button" className="btn-secondary" onClick={() => { setReferences(readReferences()); setAttempt(value => value + 1); }}>Comprobar trabajos</button>
  </section>;
}

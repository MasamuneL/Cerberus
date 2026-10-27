import { useEffect, useState } from "react";
import { getJob } from "../api/client";
import type { JobStatus } from "../api/types";

const TERMINAL = new Set(["complete", "failed", "not_found"]);

/** Consulta GET /api/jobs/{id} cada `intervalMs` hasta un estado terminal o error. */
export function useJob(
  jobId: string | null,
  intervalMs = 2000,
): { status: JobStatus | null; error: string | null } {
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setStatus(null);
    setError(null);
    if (!jobId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const s = await getJob(jobId);
        if (cancelled) return;
        setStatus(s);
        if (!TERMINAL.has(s.status)) timer = setTimeout(poll, intervalMs);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      }
    };
    void poll();

    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  return { status, error };
}

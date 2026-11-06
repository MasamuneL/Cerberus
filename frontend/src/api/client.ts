// Cliente HTTP de la API (docs/PLAN_MVP.md §7).
import type {
  AuthConfig,
  AuthSession,
  ConfirmUpload,
  JobCreated,
  JobStatus,
  LongitudinalPoint,
  SegmentationResult,
  AreasResult,
  SystemInfo,
  Study,
  StudyDetail,
  UploadCreated,
  UploadManifest,
  Volumetry,
} from "./types";

const API = "/api";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const enc = encodeURIComponent;

// Solo memoria: ninguna credencial ni token CSRF se persiste en el navegador.
let csrfToken: string | null = null;
let unauthorized: (() => void) | null = null;
let generation = 0;
const pending = new Set<AbortController>();

export function clearAuthContext(): void {
  csrfToken = null;
  unauthorized = null;
  generation += 1;
  for (const controller of pending) controller.abort();
  pending.clear();
}

export function setAuthContext(token: string, onUnauthorized: () => void): void {
  if (csrfToken !== token) clearAuthContext();
  csrfToken = token;
  unauthorized = onUnauthorized;
}

async function exchange<T>(
  path: string,
  init: RequestInit | undefined,
  consume: (response: Response) => Promise<T>,
  observeUnauthorized = true,
): Promise<T> {
  const controller = new AbortController();
  const requestGeneration = generation;
  pending.add(controller);
  const headers = new Headers(init?.headers);
  if (init?.method && !["GET", "HEAD", "OPTIONS"].includes(init.method.toUpperCase())) {
    headers.set("X-Cerberus", "1");
    if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  }
  try {
    const signal = init?.signal ? AbortSignal.any([init.signal, controller.signal]) : controller.signal;
    const res = await fetch(`${API}${path}`, { ...init, headers, signal, credentials: "same-origin" });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body: unknown = await res.json();
        if (body && typeof body === "object" && "detail" in body) {
          const d = (body as { detail: unknown }).detail;
          detail = typeof d === "string" ? d : JSON.stringify(d);
        }
      } catch {
        // cuerpo no JSON: se queda statusText
      }
      if (res.status === 401 && observeUnauthorized && requestGeneration === generation && unauthorized) {
        const notify = unauthorized;
        clearAuthContext();
        notify();
      }
      throw new ApiError(res.status, detail);
    }
    return await consume(res);
  } finally {
    pending.delete(controller);
  }
}

function request<T>(path: string, init?: RequestInit, observeUnauthorized = true): Promise<T> {
  return exchange(path, init, async (res) => res.status === 204 ? undefined as T : await res.json() as T, observeUnauthorized);
}

export const getAuthConfig = (signal?: AbortSignal): Promise<AuthConfig> =>
  request("/auth/config", { signal, cache: "no-store" }, false);
export const getAuthSession = (signal?: AbortSignal): Promise<AuthSession> =>
  request("/auth/me", { signal, cache: "no-store" }, false);
export const logoutSession = (token: string): Promise<void> =>
  request("/auth/logout", { method: "POST", headers: { "X-CSRF-Token": token } }, false);

/** Descarga cancelable y revalidada; Niivue no admite AbortSignal en su cargador HTTP. */
export function fetchVolume(url: string, signal: AbortSignal): Promise<ArrayBuffer> {
  if (!url.startsWith(`${API}/`)) throw new Error("URL de volumen inválida");
  return exchange(url.slice(API.length), { signal, cache: "no-cache" }, (res) => res.arrayBuffer());
}

export const listStudies = (): Promise<Study[]> => request("/studies");

export const getStudy = (p: string, t: string): Promise<StudyDetail> =>
  request(`/studies/${enc(p)}/${enc(t)}`);

export const fileUrl = (p: string, t: string, name: string): string =>
  `${API}/studies/${enc(p)}/${enc(t)}/files/${enc(name)}.nii.gz`;

export const getVolumetry = (p: string, t: string): Promise<Volumetry> =>
  request(`/studies/${enc(p)}/${enc(t)}/volumetry`);

export const getLongitudinal = (p: string): Promise<LongitudinalPoint[]> =>
  request(`/patients/${enc(p)}/longitudinal`);

export const startSegmentation = (p: string, t: string): Promise<JobCreated> =>
  request(`/studies/${enc(p)}/${enc(t)}/segmentation`, { method: "POST" });

export const getSegmentation = (p: string, t: string): Promise<SegmentationResult> =>
  request(`/studies/${enc(p)}/${enc(t)}/segmentation`);

export const startAreaMapping = (p: string, t: string): Promise<JobCreated> =>
  request(`/studies/${enc(p)}/${enc(t)}/areas`, { method: "POST" });

export const getAreas = (p: string, t: string): Promise<AreasResult> =>
  request(`/studies/${enc(p)}/${enc(t)}/areas`);

export const getSystem = (): Promise<SystemInfo> => request("/system");

export const getJob = (id: string): Promise<JobStatus> => request(`/jobs/${enc(id)}`);

export function uploadFile(
  file: File,
  patient: string,
  timepoint: string,
  sequence?: string,
): Promise<Study | UploadCreated> {
  const form = new FormData();
  form.append("file", file);
  form.append("patient", patient);
  form.append("timepoint", timepoint);
  if (sequence) form.append("sequence", sequence);
  return request("/uploads", { method: "POST", body: form });
}

export function isUploadCreated(x: Study | UploadCreated): x is UploadCreated {
  return "upload_id" in x && "job_id" in x;
}

export const getUpload = (id: string): Promise<UploadManifest> => request(`/uploads/${enc(id)}`);

export const seriesUrl = (uploadId: string, index: number): string =>
  `${API}/uploads/${enc(uploadId)}/series/${index}.nii.gz`;

export const confirmUpload = (id: string, body: ConfirmUpload): Promise<Study> =>
  request(`/uploads/${enc(id)}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deleteUpload = (id: string): Promise<void> =>
  request(`/uploads/${enc(id)}`, { method: "DELETE" });

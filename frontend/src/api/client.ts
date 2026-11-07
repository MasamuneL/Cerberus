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

import { forgetReference, rememberReference } from "./continuity";

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

/** Error recuperable: la petición y su lectura de respuesta excedieron el plazo. */
export class RequestTimeoutError extends Error {
  constructor() {
    super("La solicitud tardó demasiado. Comprueba la conexión y reintenta.");
    this.name = "RequestTimeoutError";
  }
}

const JSON_TIMEOUT_MS = 30_000;
const AUTH_TIMEOUT_MS = 10_000;
const enc = encodeURIComponent;

// Solo memoria: ninguna credencial ni token CSRF se persiste en el navegador.
let csrfToken: string | null = null;
let unauthorized: (() => void) | null = null;
let generation = 0;
let sessionExpiry: ((expiresAt: number) => void) | null = null;
const pending = new Set<AbortController>();

export function clearAuthContext(): void {
  csrfToken = null;
  unauthorized = null;
  sessionExpiry = null;
  generation += 1;
  for (const controller of pending) controller.abort();
  pending.clear();
}

export function setAuthContext(token: string, onUnauthorized: () => void, onExpiry?: (expiresAt: number) => void): void {
  if (csrfToken !== token) clearAuthContext();
  csrfToken = token;
  unauthorized = onUnauthorized;
  sessionExpiry = onExpiry ?? null;
}

async function exchange<T>(
  path: string,
  init: RequestInit | undefined,
  consume: (response: Response) => Promise<T>,
  observeUnauthorized = true,
  timeoutMs = 0,
): Promise<T> {
  const controller = new AbortController();
  const requestGeneration = generation;
  pending.add(controller);
  let timedOut = false;
  const timer = timeoutMs > 0 ? setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs) : undefined;
  const headers = new Headers(init?.headers);
  if (init?.method && !["GET", "HEAD", "OPTIONS"].includes(init.method.toUpperCase())) {
    headers.set("X-Cerberus", "1");
    if (csrfToken && !headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", csrfToken);
  }
  try {
    const signal = init?.signal ? AbortSignal.any([init.signal, controller.signal]) : controller.signal;
    const res = await fetch(`${API}${path}`, { ...init, headers, signal, credentials: "same-origin" });
    const expiresAt = Number(res.headers.get("X-Cerberus-Session-Expires-At"));
    if (requestGeneration === generation && !controller.signal.aborted && Number.isFinite(expiresAt) && expiresAt > 0) {
      sessionExpiry?.(expiresAt);
    }
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
  } catch (error) {
    if (timedOut) throw new RequestTimeoutError();
    throw error;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    pending.delete(controller);
  }
}

function request<T>(path: string, init?: RequestInit, observeUnauthorized = true, timeoutMs = JSON_TIMEOUT_MS): Promise<T> {
  return exchange(path, init, async (res) => res.status === 204 ? undefined as T : await res.json() as T, observeUnauthorized, timeoutMs);
}

export const getAuthConfig = (signal?: AbortSignal): Promise<AuthConfig> =>
  request("/auth/config", { signal, cache: "no-store" }, false, AUTH_TIMEOUT_MS);
export const getAuthSession = (signal?: AbortSignal): Promise<AuthSession> =>
  request("/auth/me", { signal, cache: "no-store" }, false, AUTH_TIMEOUT_MS);
export async function logoutSession(token: string, signal?: AbortSignal): Promise<void> {
  const send = (csrf: string) => request<void>("/auth/logout", {
    method: "POST", headers: { "X-CSRF-Token": csrf }, signal,
  }, false, AUTH_TIMEOUT_MS);
  try {
    await send(token);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 403) throw error;
    // Otra pestaña puede haber rotado la cookie. Recuperar CSRF una vez, sin bucles.
    const session = await getAuthSession(signal);
    if (!session.csrf_token) throw error;
    await send(session.csrf_token);
  }
}

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

export async function startSegmentation(p: string, t: string): Promise<JobCreated> {
  const created = await request<JobCreated>(`/studies/${enc(p)}/${enc(t)}/segmentation`, { method: "POST" });
  rememberReference(created.job_id, "segmentation");
  return created;
}

export const getSegmentation = (p: string, t: string): Promise<SegmentationResult> =>
  request(`/studies/${enc(p)}/${enc(t)}/segmentation`);

export async function startAreaMapping(p: string, t: string): Promise<JobCreated> {
  const created = await request<JobCreated>(`/studies/${enc(p)}/${enc(t)}/areas`, { method: "POST" });
  rememberReference(created.job_id, "areas");
  return created;
}

export const getAreas = (p: string, t: string): Promise<AreasResult> =>
  request(`/studies/${enc(p)}/${enc(t)}/areas`);

export const getSystem = (): Promise<SystemInfo> => request("/system");

async function ownedResource<T>(id: string, path: string, init?: RequestInit, timeoutMs = JSON_TIMEOUT_MS): Promise<T> {
  try {
    return await request<T>(path, init, true, timeoutMs);
  } catch (error) {
    if (error instanceof ApiError && [403, 404].includes(error.status)) forgetReference(id);
    throw error;
  }
}

export async function getJob(id: string): Promise<JobStatus> {
  const job = await ownedResource<JobStatus>(id, `/jobs/${enc(id)}`);
  if (job.status === "not_found") forgetReference(id);
  return job;
}

export async function uploadFile(
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
  const created = await request<Study | UploadCreated>("/uploads", { method: "POST", body: form }, true, 0);
  if (isUploadCreated(created)) rememberReference(created.upload_id, "upload");
  return created;
}

export function isUploadCreated(x: Study | UploadCreated): x is UploadCreated {
  return "upload_id" in x && "job_id" in x;
}

export const getUpload = (id: string): Promise<UploadManifest> => ownedResource(id, `/uploads/${enc(id)}`);

export const seriesUrl = (uploadId: string, index: number): string =>
  `${API}/uploads/${enc(uploadId)}/series/${index}.nii.gz`;

export const confirmUpload = async (id: string, body: ConfirmUpload): Promise<Study> => {
  const study = await ownedResource<Study>(id, `/uploads/${enc(id)}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }, 0);
  forgetReference(id);
  return study;
};

export const deleteUpload = async (id: string): Promise<void> => {
  await ownedResource<void>(id, `/uploads/${enc(id)}`, { method: "DELETE" });
  forgetReference(id);
};

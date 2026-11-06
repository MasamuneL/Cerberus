// Cliente HTTP de la API (docs/PLAN_MVP.md §7).
import type {
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.method && !["GET", "HEAD", "OPTIONS"].includes(init.method.toUpperCase())) {
    headers.set("X-Cerberus", "1");
  }
  const res = await fetch(`${API}${path}`, { ...init, headers });
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
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
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

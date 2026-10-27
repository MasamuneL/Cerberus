// Tipos de la API. DEBEN reflejar exactamente backend/cerberus_api/schemas.py y docs/PLAN_MVP.md §7.
// Si cambias uno, actualiza también schemas.py y el §7 del plan en el mismo PR.

export type RanoCategory = "PD" | "PR" | "MR" | "SD";
export type JobState = "queued" | "in_progress" | "complete" | "failed" | "not_found";
export type UploadState = "processing" | "ready" | "failed";
export type ModelChannel = "T1c" | "T1" | "T2" | "FLAIR";

export interface Study {
  patient: string;
  timepoint: string;
  sequences: string[];
  has_gtv: boolean;
  has_brain_mask: boolean;
  has_segmentation: boolean;
}

export interface VolumeInfo {
  sequence: string;
  label: string;
  shape: number[];
  spacing_mm: number[];
  dtype: string;
}

export interface StudyDetail extends Study {
  volumes: VolumeInfo[];
}

export interface Volumetry {
  gtv_cm3: number;
  brain_cm3: number;
  fraction_pct: number;
  lr_mm: number;
  ap_mm: number;
  si_mm: number;
  abc2_cm3: number;
  abc2_error_pct: number;
  components: number;
  rano_measurable: boolean;
  spacing_ok: boolean;
}

export interface LongitudinalPoint {
  timepoint: string;
  gtv_cm3: number;
  change_vs_t0_pct: number;
  rano: RanoCategory | null;
}

export interface ChannelUsed {
  model_channel: ModelChannel;
  sequence: string | null;
}

export interface SegmentationVolumes {
  wt: number;
  tc: number;
  et: number;
}

export interface DiceVsGtv {
  tc: number;
  wt: number;
}

export interface SegmentationResult {
  device: string;
  created_at: string; // ISO 8601
  channels: ChannelUsed[];
  volumes_cm3: SegmentationVolumes;
  dice_vs_gtv: DiceVsGtv | null;
  warnings: string[];
}

export interface JobCreated {
  job_id: string;
}

export interface JobStatus {
  job_id: string;
  status: JobState;
  result: unknown | null;
  error: string | null;
}

export interface UploadCreated {
  upload_id: string;
  job_id: string;
}

export interface SeriesInfo {
  index: number;
  modality: string;
  description: string;
  n_files: number;
  shape: number[] | null;
  spacing_mm: number[] | null;
  converted: boolean;
  suggested_sequence: string | null;
}

export interface UploadManifest {
  upload_id: string;
  status: UploadState;
  error: string | null;
  series: SeriesInfo[];
}

export interface ConfirmUpload {
  patient: string;
  timepoint: string;
  mapping: Record<string, string>; // índice de serie (texto) → secuencia
}

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
  has_areas: boolean; // existe brodmann.nii.gz (§13)
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

// --- §13 · Áreas de Brodmann y estructuras afectadas ---

export type Hemisphere = "izquierdo" | "derecho";
export type AreaKind = "cortical" | "subcortical";
/** Dominios funcionales para el resumen "Funciones en riesgo" (§14). */
export type Domain =
  | "lenguaje"
  | "motor"
  | "sensitivo"
  | "vision"
  | "audicion"
  | "memoria"
  | "ejecutivo"
  | "emocional"
  | "autonomico"
  | "otro";

/** Entrada del LUT de brodmann.nii.gz: valor = índice del atlas (+100 si es hemisferio derecho). */
export interface AreaLabel {
  label: number;
  name: string;
  name_es: string;
  hemisphere: Hemisphere;
  kind: AreaKind;
}

export interface AffectedArea extends AreaLabel {
  area_cm3: number;
  overlap_gtv_cm3: number;
  overlap_gtv_pct: number;
  overlap_wt_cm3: number | null;
  overlap_wt_pct: number | null;
  distance_mm: number; // 0 si se solapa con el GTV
  functions: string[];
  eloquent: boolean;
  domains: Domain[]; // según hemisferio (§14)
}

export interface AreasResult {
  atlas: string;
  registration: string;
  reference_sequence: string;
  margin_mm: number;
  created_at: string; // ISO-8601
  areas: AffectedArea[];
  lut: AreaLabel[];
  warnings: string[];
}

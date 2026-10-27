"""Modelos Pydantic de la API: contrato de docs/PLAN_MVP.md §7.

`frontend/src/api/types.ts` debe reflejar exactamente estos modelos. Si cambias uno, actualiza también
`types.ts` y el §7 del plan en el mismo PR.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

RanoCategory = Literal["PD", "PR", "MR", "SD"]
JobState = Literal["queued", "in_progress", "complete", "failed", "not_found"]
UploadState = Literal["processing", "ready", "failed"]


class Study(BaseModel):
    patient: str
    timepoint: str
    sequences: list[str]  # ordenadas alfabéticamente
    has_gtv: bool
    has_brain_mask: bool
    has_segmentation: bool


class VolumeInfo(BaseModel):
    sequence: str
    label: str  # descripción en español de SEQ_INFO
    shape: list[int]
    spacing_mm: list[float]
    dtype: str


class StudyDetail(Study):
    volumes: list[VolumeInfo]


class Volumetry(BaseModel):
    """Volumetría del GTV a resolución nativa (portado de cerberus_eda.py:209-235)."""

    gtv_cm3: float
    brain_cm3: float
    fraction_pct: float
    lr_mm: float
    ap_mm: float
    si_mm: float
    abc2_cm3: float
    abc2_error_pct: float
    components: int
    rano_measurable: bool
    spacing_ok: bool


class LongitudinalPoint(BaseModel):
    timepoint: str
    gtv_cm3: float
    change_vs_t0_pct: float  # 0.0 en t0
    rano: RanoCategory | None  # None en t0


class ChannelUsed(BaseModel):
    model_channel: Literal["T1c", "T1", "T2", "FLAIR"]
    sequence: str | None  # None = canal faltante (ceros)


class SegmentationVolumes(BaseModel):
    wt: float
    tc: float
    et: float


class DiceVsGtv(BaseModel):
    tc: float
    wt: float


class SegmentationResult(BaseModel):
    device: str
    created_at: datetime
    channels: list[ChannelUsed]
    volumes_cm3: SegmentationVolumes
    dice_vs_gtv: DiceVsGtv | None
    warnings: list[str]


class JobCreated(BaseModel):
    job_id: str


class JobStatus(BaseModel):
    job_id: str
    status: JobState
    result: Any | None = None
    error: str | None = None


class UploadCreated(BaseModel):
    upload_id: str
    job_id: str


class SeriesInfo(BaseModel):
    index: int
    modality: str
    description: str
    n_files: int
    shape: list[int] | None
    spacing_mm: list[float] | None
    converted: bool
    suggested_sequence: str | None


class UploadManifest(BaseModel):
    upload_id: str
    status: UploadState
    error: str | None = None
    series: list[SeriesInfo]


class ConfirmUpload(BaseModel):
    patient: str
    timepoint: str
    mapping: dict[str, str]  # índice de serie (como texto) → secuencia

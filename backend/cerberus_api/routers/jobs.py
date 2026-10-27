"""Estado de jobs arq (docs/PLAN_MVP.md §7, ticket B6).

`Job(job_id, redis).status()`; si está `complete`, `result_info()` distingue éxito de fallo
(`success=False` → `failed`, con el `str` de la excepción en `error`).
"""

from arq.jobs import Job
from arq.jobs import JobStatus as ArqJobStatus
from fastapi import APIRouter, HTTPException
from redis.exceptions import RedisError

from cerberus_api.deps import REDIS_UNAVAILABLE, RedisDep
from cerberus_api.schemas import JobState, JobStatus

router = APIRouter(tags=["jobs"])

# Estados de arq que no son `complete` → estado del contrato
_STATE_MAP: dict[ArqJobStatus, JobState] = {
    ArqJobStatus.deferred: "queued",
    ArqJobStatus.queued: "queued",
    ArqJobStatus.in_progress: "in_progress",
    ArqJobStatus.not_found: "not_found",
}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, redis: RedisDep) -> JobStatus:
    """Estado de un job: queued | in_progress | complete | failed | not_found."""
    job = Job(job_id, redis)
    try:
        status = await job.status()
        if status != ArqJobStatus.complete:
            return JobStatus(job_id=job_id, status=_STATE_MAP[status])
        info = await job.result_info()
    except (RedisError, OSError) as exc:
        raise HTTPException(status_code=503, detail=REDIS_UNAVAILABLE) from exc
    if info is None:
        # El resultado expiró (keep_result) entre status() y result_info()
        return JobStatus(job_id=job_id, status="not_found")
    if not info.success:
        return JobStatus(job_id=job_id, status="failed", error=str(info.result))
    return JobStatus(job_id=job_id, status="complete", result=info.result)

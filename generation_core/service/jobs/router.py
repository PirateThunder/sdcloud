import hashlib
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from pipeline.analysis_schemas import CalibrationRequest, ScenarioRunRequest, SensitivityRequest
from pipeline.schemas import ConversationRequest, GenerationRequest

from ..database import DbDep
from ..exceptions import QueueUnavailableError
from . import service
from .dependencies import DispatcherDep, SettingsDep, ValidJobDep
from .models import Job
from .schemas import ImportRequest, JobCreated, JobInfo, JobKind, SimulationRequest

router = APIRouter(tags=["jobs"])
IdempotencyKeyDep = Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)]


async def _dispatch(db: DbDep, dispatch: DispatcherDep, job: Job) -> None:
    try:
        await dispatch(job.id)
    except Exception as exc:
        await service.mark_dispatch_failed(db, job, exc)
        raise QueueUnavailableError("job queue is unavailable") from exc


def _created(job: Job) -> dict:
    return {
        "job_id": job.id,
        "status": job.status,
        "status_url": f"/api/v1/jobs/{job.id}",
    }


@router.post("/models", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreated)
async def create_generation(
    request: GenerationRequest,
    db: DbDep,
    settings: SettingsDep,
    dispatch: DispatcherDep,
    response: Response,
    idempotency_key: IdempotencyKeyDep = None,
) -> dict:
    job, created = await service.create_job(
        db, settings, JobKind.GENERATE, request, idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        return _created(job)
    await _dispatch(db, dispatch, job)
    return _created(job)


@router.post("/chat", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreated)
async def create_chat_message(
    request: ConversationRequest,
    db: DbDep,
    settings: SettingsDep,
    dispatch: DispatcherDep,
    response: Response,
    idempotency_key: IdempotencyKeyDep = None,
) -> dict:
    job, created = await service.create_job(db, settings, JobKind.CHAT, request, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
        return _created(job)
    await _dispatch(db, dispatch, job)
    return _created(job)


@router.post("/models/import", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreated)
async def create_import(
    db: DbDep,
    settings: SettingsDep,
    dispatch: DispatcherDep,
    response: Response,
    file: Annotated[UploadFile, File()],
    idempotency_key: IdempotencyKeyDep = None,
) -> dict:
    filename = file.filename or "model"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".mdl", ".xmile"}:
        raise HTTPException(status_code=422, detail="only .mdl and .xmile files are supported")
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="model file exceeds 5 MiB")
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="model must be UTF-8 text") from exc
    payload = ImportRequest(
        filename=Path(filename).name,
        file_format="xmile" if suffix == ".xmile" else "vensim",
        source_sha256=hashlib.sha256(content).hexdigest(),
    )
    job, created = await service.create_job(
        db, settings, JobKind.IMPORT, payload, idempotency_key, source=content
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        return _created(job)
    await _dispatch(db, dispatch, job)
    return _created(job)


@router.post("/simulations", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreated)
async def create_simulation(
    request: SimulationRequest,
    db: DbDep,
    settings: SettingsDep,
    dispatch: DispatcherDep,
    response: Response,
    idempotency_key: IdempotencyKeyDep = None,
) -> dict:
    job, created = await service.create_job(
        db, settings, JobKind.SIMULATE, request, idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        return _created(job)
    await _dispatch(db, dispatch, job)
    return _created(job)


@router.post("/scenario-runs", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreated)
async def create_scenario_run(
    request: ScenarioRunRequest,
    db: DbDep,
    settings: SettingsDep,
    dispatch: DispatcherDep,
    response: Response,
    idempotency_key: IdempotencyKeyDep = None,
) -> dict:
    job, created = await service.create_job(
        db, settings, JobKind.SCENARIO, request, idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        return _created(job)
    await _dispatch(db, dispatch, job)
    return _created(job)


@router.post("/sensitivity-runs", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreated)
async def create_sensitivity_run(
    request: SensitivityRequest,
    db: DbDep,
    settings: SettingsDep,
    dispatch: DispatcherDep,
    response: Response,
    idempotency_key: IdempotencyKeyDep = None,
) -> dict:
    job, created = await service.create_job(
        db, settings, JobKind.SENSITIVITY, request, idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        return _created(job)
    await _dispatch(db, dispatch, job)
    return _created(job)


@router.post("/calibrations", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreated)
async def create_calibration(
    request: CalibrationRequest,
    db: DbDep,
    settings: SettingsDep,
    dispatch: DispatcherDep,
    response: Response,
    idempotency_key: IdempotencyKeyDep = None,
) -> dict:
    job, created = await service.create_job(
        db, settings, JobKind.CALIBRATION, request, idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        return _created(job)
    await _dispatch(db, dispatch, job)
    return _created(job)


@router.get("/jobs", response_model=list[JobInfo])
async def list_jobs(
    db: DbDep,
    settings: SettingsDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    jobs = await service.list_jobs(db, status_filter, limit, offset)
    return [await run_in_threadpool(service.job_to_info, job, settings) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobInfo)
async def get_job_info(job: ValidJobDep, settings: SettingsDep) -> dict:
    return await run_in_threadpool(service.job_to_info, job, settings)


@router.get("/jobs/{job_id}/result")
async def get_result(job: ValidJobDep, settings: SettingsDep) -> JSONResponse:
    content = await run_in_threadpool(service.read_result, settings, job)
    return JSONResponse(content)


@router.get("/jobs/{job_id}/log")
async def get_log(
    job: ValidJobDep,
    settings: SettingsDep,
    tail: Annotated[int, Query(ge=1, le=5000)] = 200,
) -> PlainTextResponse:
    content = await run_in_threadpool(service.log_tail, settings, job, tail)
    return PlainTextResponse(content)


@router.get("/jobs/{job_id}/files/{filename}")
async def get_file(job: ValidJobDep, settings: SettingsDep, filename: str) -> FileResponse:
    path = await run_in_threadpool(service.resolve_file, settings, job, filename)
    return FileResponse(path, filename=path.name)


@router.post("/jobs/{job_id}/retry", response_model=JobCreated)
async def retry_job(
    job: ValidJobDep,
    db: DbDep,
    settings: SettingsDep,
    dispatch: DispatcherDep,
) -> dict:
    job = await service.retry_job(db, settings, job)
    await _dispatch(db, dispatch, job)
    return _created(job)

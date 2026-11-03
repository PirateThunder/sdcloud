import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.io import read_json, write_json_atomic

from ..config import ROOT, Settings
from ..exceptions import ConflictError, NotFoundError
from .models import Job
from .schemas import JobKind, JobStatus

_RESULT_FILES = {
    JobKind.GENERATE: "model.json",
    JobKind.CHAT: "response.json",
    JobKind.SIMULATE: "simulation.json",
    JobKind.IMPORT: "model.json",
    JobKind.SCENARIO: "scenarios.json",
    JobKind.SENSITIVITY: "sensitivity.json",
    JobKind.CALIBRATION: "calibration.json",
}
_ALLOWED_FILES = {
    "response.json",
    "model.json",
    "model.py",
    "model.mdl",
    "model.xmile",
    "simulation.json",
    "simulation.csv",
    "scenarios.json",
    "comparison.csv",
    "sensitivity.json",
    "sensitivity.csv",
    "calibration.json",
    "calibration.csv",
    "fitted_model.json",
    "manifest.json",
    "job.log",
}


def now() -> datetime:
    return datetime.now(UTC)


def job_dir(settings: Settings, job_id: str) -> Path:
    return settings.jobs_root / job_id


def result_name(kind: JobKind) -> str:
    return _RESULT_FILES[kind]


def _payload_hash(payload: dict) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def build_argv(kind: JobKind, directory: Path) -> list[str]:
    common = [sys.executable]
    if kind is JobKind.GENERATE:
        return [
            *common,
            str(ROOT / "generate.py"),
            "--input",
            str(directory / "generation_request.json"),
            "--workdir",
            str(directory / "work"),
            "--output",
            str(directory / "model.json"),
            "--manifest",
            str(directory / "manifest.json"),
        ]
    if kind is JobKind.CHAT:
        return [
            *common,
            str(ROOT / "chat.py"),
            "--input",
            str(directory / "conversation_request.json"),
            "--workdir",
            str(directory / "work"),
            "--output",
            str(directory / "response.json"),
            "--manifest",
            str(directory / "manifest.json"),
        ]
    if kind is JobKind.IMPORT:
        return [
            *common,
            str(ROOT / "convert.py"),
            "import",
            "--input",
            str(
                directory / "source.xmile"
                if directory.joinpath("source.xmile").exists()
                else directory / "source.mdl"
            ),
            "--workdir",
            str(directory / "work"),
            "--output",
            str(directory / "model.json"),
            "--manifest",
            str(directory / "manifest.json"),
        ]
    if kind in {JobKind.SCENARIO, JobKind.SENSITIVITY, JobKind.CALIBRATION}:
        script, input_option, output = {
            JobKind.SCENARIO: ("scenarios.py", "--scenarios", "scenarios.json"),
            JobKind.SENSITIVITY: ("sensitivity.py", "--config", "sensitivity.json"),
            JobKind.CALIBRATION: ("calibrate.py", "--observations", "calibration.json"),
        }[kind]
        return [
            *common,
            str(ROOT / script),
            "--model",
            str(directory / "input_model.json"),
            input_option,
            str(directory / "analysis_request.json"),
            "--workdir",
            str(directory / "work"),
            "--output",
            str(directory / output),
            "--manifest",
            str(directory / "manifest.json"),
        ]
    return [
        *common,
        str(ROOT / "simulate.py"),
        "--model",
        str(directory / "input_model.json"),
        "--params",
        str(directory / "params.json"),
        "--workdir",
        str(directory / "work"),
        "--output",
        str(directory / "simulation.json"),
        "--manifest",
        str(directory / "manifest.json"),
    ]


def prepare_files(settings: Settings, job: Job, source: bytes | None = None) -> None:
    directory = job_dir(settings, job.id)
    directory.mkdir(parents=True, exist_ok=True)
    kind = JobKind(job.kind)
    write_json_atomic(directory / "request.json", job.request)
    if kind is JobKind.GENERATE:
        write_json_atomic(directory / "generation_request.json", job.request)
    elif kind is JobKind.CHAT:
        write_json_atomic(directory / "conversation_request.json", job.request)
    elif kind is JobKind.IMPORT:
        suffix = ".xmile" if job.request["file_format"] == "xmile" else ".mdl"
        if source is not None:
            (directory / f"source{suffix}").write_bytes(source)
        if not (directory / f"source{suffix}").is_file():
            raise RuntimeError("import source is missing")
    elif kind in {JobKind.SCENARIO, JobKind.SENSITIVITY, JobKind.CALIBRATION}:
        write_json_atomic(directory / "input_model.json", job.request["model"])
        write_json_atomic(
            directory / "analysis_request.json",
            {key: value for key, value in job.request.items() if key != "model"},
        )
    else:
        write_json_atomic(directory / "input_model.json", job.request["model"])
        write_json_atomic(directory / "params.json", job.request["parameters"])
    write_json_atomic(directory / "argv.json", {"argv": build_argv(kind, directory)})


async def create_job(
    session: AsyncSession,
    settings: Settings,
    kind: JobKind,
    payload: BaseModel,
    idempotency_key: str | None,
    *,
    source: bytes | None = None,
) -> tuple[Job, bool]:
    request = payload.model_dump(mode="json")
    request_hash = _payload_hash(request)
    if idempotency_key:
        existing = await session.scalar(
            select(Job).where(Job.kind == kind.value, Job.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("Idempotency-Key was already used with a different request")
            return existing, False
    job = Job(
        id=str(uuid.uuid4()),
        kind=kind.value,
        status=JobStatus.PENDING.value,
        request=request,
        request_hash=request_hash,
        idempotency_key=idempotency_key,
        attempt=1,
    )
    prepare_files(settings, job, source)
    session.add(job)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if not idempotency_key:
            raise
        existing = await session.scalar(
            select(Job).where(Job.kind == kind.value, Job.idempotency_key == idempotency_key)
        )
        if existing is None or existing.request_hash != request_hash:
            raise ConflictError("Idempotency-Key conflict") from None
        return existing, False
    return job, True


async def mark_dispatch_failed(session: AsyncSession, job: Job, error: Exception) -> None:
    job.status = JobStatus.ERROR.value
    job.error = f"failed to enqueue job: {error}"[:2000]
    job.finished_at = now()
    await session.commit()


async def retry_job(session: AsyncSession, settings: Settings, job: Job) -> Job:
    if job.status != JobStatus.ERROR.value:
        raise ConflictError("only failed jobs can be retried")
    directory = job_dir(settings, job.id)
    log = directory / "job.log"
    if log.is_file():
        log.replace(directory / f"job.attempt-{job.attempt}.log")
    for name in (
        result_name(JobKind(job.kind)),
        "simulation.csv",
        "comparison.csv",
        "sensitivity.csv",
        "calibration.csv",
        "fitted_model.json",
        "manifest.json",
        "work/stage.json",
    ):
        (directory / name).unlink(missing_ok=True)
    job.attempt += 1
    job.status = JobStatus.PENDING.value
    job.stage = None
    job.manifest = None
    job.returncode = None
    job.error = None
    job.started_at = None
    job.finished_at = None
    prepare_files(settings, job)
    await session.commit()
    return job


async def list_jobs(
    session: AsyncSession, status: str | None, limit: int, offset: int
) -> list[Job]:
    statement = select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)
    if status:
        statement = statement.where(Job.status == status)
    return list((await session.scalars(statement)).all())


def load_argv(settings: Settings, job: Job) -> list[str] | None:
    try:
        value = read_json(job_dir(settings, job.id) / "argv.json")["argv"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return value


def read_manifest(settings: Settings, job: Job) -> dict | None:
    try:
        value = read_json(job_dir(settings, job.id) / "manifest.json")
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def log_tail(settings: Settings, job: Job, lines: int = 200) -> str:
    path = job_dir(settings, job.id) / "job.log"
    if not path.is_file():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def job_to_info(job: Job, settings: Settings) -> dict:
    directory = job_dir(settings, job.id)
    files = (
        sorted(
            path.name
            for path in directory.iterdir()
            if path.is_file() and path.name in _ALLOWED_FILES
        )
        if directory.is_dir()
        else []
    )
    stage = job.stage
    stage_path = directory / "work" / "stage.json"
    if stage_path.is_file():
        try:
            stage = read_json(stage_path).get("stage") or stage
        except (OSError, json.JSONDecodeError, AttributeError):
            stage = job.stage
    return {
        "job_id": job.id,
        "kind": job.kind,
        "status": job.status,
        "stage": stage,
        "attempt": job.attempt,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "files": files,
        "file_urls": [f"/api/v1/jobs/{job.id}/files/{name}" for name in files],
        "manifest": job.manifest,
        "error": job.error,
    }


def read_result(settings: Settings, job: Job) -> dict:
    if job.status != JobStatus.DONE.value:
        raise ConflictError("job result is not ready")
    path = job_dir(settings, job.id) / result_name(JobKind(job.kind))
    if not path.is_file():
        raise NotFoundError("job result not found")
    return read_json(path)


def resolve_file(settings: Settings, job: Job, filename: str) -> Path:
    if filename not in _ALLOWED_FILES:
        raise NotFoundError("file not found")
    directory = job_dir(settings, job.id).resolve()
    path = (directory / filename).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise NotFoundError("file not found")
    return path

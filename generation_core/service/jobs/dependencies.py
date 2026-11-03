from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from ..config import Settings, get_settings
from ..database import DbDep
from ..exceptions import NotFoundError
from .models import Job
from .tasks import dispatch


async def get_job(job_id: str, db: DbDep) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise NotFoundError("job not found")
    return job


def get_dispatcher() -> Callable[[str], Awaitable[None]]:
    return dispatch


SettingsDep = Annotated[Settings, Depends(get_settings)]
ValidJobDep = Annotated[Job, Depends(get_job)]
DispatcherDep = Annotated[Callable[[str], Awaitable[None]], Depends(get_dispatcher)]

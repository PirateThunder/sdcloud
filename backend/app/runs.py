from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    SUBMITTED = "submitted"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


ACTIVE_STATUSES = (RunStatus.QUEUED.value, RunStatus.SUBMITTED.value, RunStatus.RUNNING.value)

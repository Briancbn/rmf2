from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from rmf2_scheduler import Scheduler


def get_scheduler(request: Request) -> Scheduler:
    """Read the Scheduler from app.state.

    The scheduler is created and started in the FastAPI lifespan (app.py),
    and stopped again on shutdown.
    """
    scheduler: Scheduler | None = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not ready")
    return scheduler


SchedulerDep = Annotated[Scheduler, Depends(get_scheduler)]

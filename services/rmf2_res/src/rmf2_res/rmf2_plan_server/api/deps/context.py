from typing import Annotated

from fastapi import Depends, Request

from rmf2_res.rmf2_plan_server.plan_server import RESPlanServerContext


def get_context(request: Request) -> RESPlanServerContext:
    return request.app.state.context


ContextDeps = Annotated[RESPlanServerContext, Depends(get_context)]

from typing import Annotated

from fastapi import Depends, Request

from rmf2_res.rmf2_plan_executor.plan_executor import RESPlanExecutorTransport


def get_transport(request: Request) -> RESPlanExecutorTransport:
    return request.app.state.context.transport


TransportDeps = Annotated[RESPlanExecutorTransport, Depends(get_transport)]

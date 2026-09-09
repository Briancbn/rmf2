from typing import Annotated

from fastapi import Depends, Request

from rmf2_plan_executor.transport.amqp import AmqpExecutorTransport


def get_transport(request: Request) -> AmqpExecutorTransport:
    return request.app.state.transport


TransportDeps = Annotated[AmqpExecutorTransport, Depends(get_transport)]
